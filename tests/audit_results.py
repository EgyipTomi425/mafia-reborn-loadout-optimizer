"""Independent CPU audit of every trade score and every distinct geometry.

Optional audit dependencies: locally installed numpy/scipy (not needed by C++).
Run from any cwd: python tests/audit_results.py [--skip-milp]
"""
import concurrent.futures
import csv
import json
from pathlib import Path
import sys
import warnings

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

warnings.filterwarnings('ignore', message="Unrecognized options detected:.*threads", category=RuntimeWarning)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
VARIANTS = {(v['id'], v['tier']): v for v in json.loads((DATA / 'variants.json').read_text())}


def geometry_milp(job):
    geometry, expected = job
    rows, cols = [], []
    n = len(geometry)
    column = 0
    for i, (w, h) in enumerate(geometry):
        for y in range(9 - h):
            for x in range(13 - w):
                rows.append(i)
                cols.append(column)
                for yy in range(y, y + h):
                    for xx in range(x, x + w):
                        rows.append(n + yy * 12 + xx)
                        cols.append(column)
                column += 1
    matrix = coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(n + 96, column)).tocsr()
    result = milp(np.zeros(column), integrality=np.ones(column),
                  bounds=Bounds(np.zeros(column), np.ones(column)),
                  constraints=LinearConstraint(matrix, np.r_[np.ones(n), np.zeros(96)], np.ones(n + 96)),
                  options={'time_limit': 120, 'threads': 1})
    if result.x is not None:
        actual = 'valid'
    elif result.status == 2:
        actual = 'impossible'
    else:
        raise RuntimeError(f'Unresolved MILP: {geometry}, status={result.status}')
    if actual != expected:
        raise AssertionError((geometry, expected, actual))
    return actual


def variant(ident):
    return VARIANTS[ident, 'gold1' if ident.startswith(('full_metal_', 'soft_nosed_', 'tracer_')) else 'epic1']


def audit(kind):
    rows = list(csv.DictReader((ROOT / 'results' / f'{kind}_candidates.csv').open()))
    summary = json.loads((ROOT / 'results' / f'{kind}_results.json').read_text())
    geometry = {}
    for row in rows:
        ids = row['item_ids'].split(';')
        assert 'riot_shield' not in ids
        ammo = [i for i in ids if variant(i)['kind'] == 'ammo']
        assert len(ammo) <= 1
        for ident in ids:
            compatible = variant(ident).get('compatibleWeapons', [])
            assert not compatible or kind in compatible
        for ident in ammo:
            assert ident.startswith(('soft_nosed_bullet_', 'tracer_ammunition_'))
            assert ident.endswith('_small' if kind == 'submachine' else '_large')
            assert variant(ident)['tier'] == 'gold1'
        key = tuple(sorted((variant(x)['width'], variant(x)['height']) for x in row['item_ids'].split(';')))
        assert sum(w * h for w, h in key) == int(row['area'])
        assert 92 <= int(row['area']) <= 96
        assert row['status'] in ('valid', 'impossible')
        assert key not in geometry or geometry[key] == row['status']
        geometry[key] = row['status']
    assert summary['excluded_items'] == ['riot_shield']
    assert summary['optional_items'] == 15 and summary['all_combinations'] == 98304
    assert summary['ammo_choices_including_none'] == 3 and summary['ammo_tier'] == 'gold1'
    assert len(rows) == (7852 if kind == 'submachine' else 9616)
    print(kind, len(geometry), 'distinct geometries', flush=True)
    if '--skip-milp' not in sys.argv:
        with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
            for count, _ in enumerate(pool.map(geometry_milp, geometry.items()), 1):
                if count % 25 == 0:
                    print(kind, 'MILP checked', count, flush=True)
    valid = [r for r in rows if r['status'] == 'valid']
    rankings = {int(r['candidate_id']): r for r in csv.DictReader((ROOT / 'results' / f'{kind}_rankings.csv').open())}
    by_wins = min(rankings, key=lambda i: (-int(rankings[i]['wins']), -float(rankings[i]['mean_net_hp_pp']), i))
    by_mean = min(rankings, key=lambda i: (-float(rankings[i]['mean_net_hp_pp']), -int(rankings[i]['wins']), i))
    assert summary['most_wins']['candidate_id'] == by_wins
    assert summary['best_mean_trade']['candidate_id'] == by_mean
    by_weighted_wins = min(rankings, key=lambda i: (-float(rankings[i]['weighted_win_rate']), -float(rankings[i]['weighted_mean_net_hp_pp']), i))
    by_weighted_mean = min(rankings, key=lambda i: (-float(rankings[i]['weighted_mean_net_hp_pp']), -float(rankings[i]['weighted_win_rate']), i))
    assert summary['best_weighted_win_rate']['candidate_id'] == by_weighted_wins
    assert summary['best_weighted_mean_trade']['candidate_id'] == by_weighted_mean
    layouts = [json.loads(line) for line in (ROOT / 'results' / f'{kind}_valid_setups.jsonl').open()]
    assert len(valid) == len(rankings) == len(layouts) == summary['valid_setups']
    for layout in layouts:
        occupied = set()
        for item in layout['items']:
            v = variant(item['id'])
            x, y = item['x'], item['y']
            assert 0 <= x <= 12 - v['width'] and 0 <= y <= 8 - v['height']
            cells = {(xx, yy) for yy in range(y, y + v['height']) for xx in range(x, x + v['width'])}
            assert not cells & occupied
            occupied |= cells
        assert len(occupied) == layout['area']
    # Independent NumPy computation, all rolls and both crit branches, then all opponents.
    raw = 8.5 * summary['level'] * 1.15
    low = int(np.floor(raw / 2.12))
    roll = np.arange(low, int(np.floor(raw + .5)) - low + 1, dtype=float)
    accuracy, dodge, camouflage, vest, landed = [], [], [], [], []
    for row in valid:
        s = {}
        for ident in row['item_ids'].split(';'):
            for key, value in variant(ident)['effects'].items():
                s[key] = s.get(key, 0) + value
        accuracy.append(1.17 + s.get('accuracyBuffPerc', 0))
        dodge.append(.101 + s.get('dodgeBuffPerc', 0))
        camouflage.append(s.get('hitChanceReductionPerc', 0))
        vest.append(int(s.get('damageResistancePerc', 0) > 0))
        pre = np.floor(.055 * summary['attack'] * (1 + s.get('damageBuffPerc', 0)) * roll[:, None]
                       * np.array([1, 2 + s.get('critDamageBuffPerc', 0)])[None, :]
                       * (1 + s.get('damageVsRoguePerc', 0)) + .5)
        probabilities = np.array([1 - (.5 + s.get('critChanceBuffPerc', 0)) * .6,
                                 (.5 + s.get('critChanceBuffPerc', 0)) * .6])
        means = []
        for resistance in (0, .14):
            damage = np.floor(np.maximum(2, pre * (1 - .25 - resistance)) + .5)
            # Integrate rounded uniform bonus without calling the C++ formula.
            lo, hi = damage * .1, damage * .2
            # E[round(U)] = E[U] + periodic rounding correction integral.
            def correction(x):
                fraction = x + .5 - np.floor(x + .5)
                return .5 * (fraction - fraction * fraction)
            bonus = (lo + hi) / 2 + (correction(hi) - correction(lo)) / (hi - lo)
            total = damage + s.get('doubleShotChanceBuffPerc', 0) * bonus * (damage < summary['hp'])
            means.append(float(np.mean(total @ probabilities)))
        landed.append(means)
    accuracy, dodge, camouflage = map(np.array, (accuracy, dodge, camouflage))
    vest, landed = np.array(vest), np.array(landed)
    weights = np.array([int(rankings[int(row['candidate_id'])]['wins']) for row in valid], dtype=float)
    for i, row in enumerate(valid):
        outgoing = np.clip(accuracy[i] - camouflage, 0, 1) * (1 - dodge) * landed[i, vest]
        incoming = np.clip(accuracy - camouflage[i], 0, 1) * (1 - dodge[i]) * landed[:, vest[i]]
        net = 100 * (outgoing - incoming) / summary['hp']
        actual = rankings[int(row['candidate_id'])]
        assert np.count_nonzero(net > 1e-10) == int(actual['wins'])
        assert np.count_nonzero(net < -1e-10) == int(actual['losses'])
        assert np.count_nonzero(abs(net) <= 1e-10) - 1 == int(actual['ties'])
        assert abs(net.sum() / (len(valid) - 1) - float(actual['mean_net_hp_pp'])) < 1e-9
        denominator = weights.sum() - weights[i]
        if denominator > 0:
            weighted_rate = weights[net > 1e-10].sum() / denominator
            weighted_mean = np.dot(weights, net) / denominator
        else:
            weighted_rate = np.count_nonzero(net > 1e-10) / (len(valid) - 1)
            weighted_mean = net.sum() / (len(valid) - 1)
        assert abs(weighted_rate - float(actual['weighted_win_rate'])) < 1e-12
        assert abs(weighted_mean - float(actual['weighted_mean_net_hp_pp'])) < 1e-9
    print(kind, 'all placements and all trade rankings independently verified', flush=True)
    return {'category': kind, 'area_candidates': len(rows), 'distinct_geometries': len(geometry),
            'valid_setups': len(valid), 'milp_checked': '--skip-milp' not in sys.argv,
            'all_placements_checked': True, 'all_trade_rankings_checked': True,
            'all_weighted_rankings_checked': True, 'all_four_winner_selections_checked': True}


if __name__ == '__main__':
    report = [audit(kind) for kind in ('submachine', 'rifle')]
    (ROOT / 'results' / 'audit.json').write_text(json.dumps(report, indent=2) + '\n')
