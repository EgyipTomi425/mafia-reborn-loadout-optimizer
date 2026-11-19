"""Export the verified Rogue experiment as browser-readable Snappy Parquet.

No GPU is needed: reconstruct each matrix from the saved, audited item sets,
then check every score against the original rankings before writing anything.
"""
import csv
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from analyze_counters import fighter
from render_results import effect_text, NAMES

OUT = ROOT / 'docs' / 'data'
EPS = 1e-10


def export_category(kind):
    source = ROOT / 'results'
    scenario = json.loads((source / f'{kind}_results.json').read_text())
    assert scenario['level'] == 200 and scenario['attack'] == scenario['endurance'] == 10000
    assert scenario['hp'] == 7738500 and scenario['ammo_tier'] == 'gold1'
    setups = [json.loads(line) for line in (source / f'{kind}_valid_setups.jsonl').read_text().splitlines()]
    scores = {int(r['candidate_id']): r for r in csv.DictReader((source / f'{kind}_rankings.csv').open())}
    fs = [fighter(s, scenario) for s in setups]
    n = len(setups)
    accuracy, dodge, camo = [np.array([f[k] for f in fs]) for k in ('accuracy', 'dodge', 'camouflage')]
    vest = np.array([f['vest'] for f in fs])
    landed = np.array([f['landed'] for f in fs])
    net = np.empty((n, n), dtype=np.float64)
    for i in range(n):
        outgoing = np.clip(accuracy[i] - camo, 0, 1) * (1 - dodge) * landed[i, vest]
        incoming = np.clip(accuracy - camo[i], 0, 1) * (1 - dodge[i]) * landed[:, vest[i]]
        net[i] = 100 * (outgoing - incoming) / scenario['hp']
    assert np.all(np.isfinite(net))
    assert np.max(np.abs(net + net.T)) < EPS
    assert np.max(np.abs(net.diagonal())) < EPS
    wins, losses = (net > EPS).sum(axis=1), (net < -EPS).sum(axis=1)
    ties = n - 1 - wins - losses
    means = net.sum(axis=1) / (n - 1)
    weights = wins.astype(np.float64)
    denominators = weights.sum() - weights
    wr = np.divide((net > EPS) @ weights, denominators, out=wins.astype(float)/(n-1), where=denominators > 0)
    wm = np.divide(net @ weights, denominators, out=means.copy(), where=denominators > 0)
    rows = []
    for i, s in enumerate(setups):
        r = scores[s['candidate_id']]
        assert (wins[i], ties[i], losses[i]) == (int(r['wins']), int(r['ties']), int(r['losses']))
        assert abs(means[i] - float(r['mean_net_hp_pp'])) < 1e-9
        assert abs(wr[i] - float(r['weighted_win_rate'])) < 1e-12
        assert abs(wm[i] - float(r['weighted_mean_net_hp_pp'])) < 1e-9
        # Validate saved placements, not just the total area.
        occupied = set()
        for item in s['items']:
            w, h = CATALOG[item['id']]['size']
            cells = {(x, y) for x in range(item['x'], item['x'] + w) for y in range(item['y'], item['y'] + h)}
            assert all(0 <= x < 12 and 0 <= y < 8 for x, y in cells)
            assert not occupied & cells
            occupied |= cells
        assert len(occupied) == s['area'] and 92 <= s['area'] <= 96
        rows.append(dict(row_index=i, candidate_id=s['candidate_id'], area=s['area'],
                         item_ids=[x['id'] for x in s['items']], xs=[x['x'] for x in s['items']], ys=[x['y'] for x in s['items']],
                         wins=int(wins[i]), ties=int(ties[i]), losses=int(losses[i]),
                         win_rate=float(wins[i]/(n-1)), mean_net_hp_pp=float(means[i]),
                         weighted_win_rate=float(wr[i]), weighted_mean_net_hp_pp=float(wm[i]),
                         accuracy=fs[i]['accuracy'], dodge=fs[i]['dodge'], camouflage=fs[i]['camouflage'],
                         vest=int(vest[i]), landed_no_vest=float(landed[i, 0]), landed_vest=float(landed[i, 1])))
    metadata = {b'model': b'level-200 Rogue, 10000 ATK/END, Epic1 gear, Gold1 ammo',
                b'orientation': b'row=our setup; list index=opponent row_index',
                b'units': b'net HP percentage points', b'tie_epsilon': str(EPS).encode()}
    folder = OUT / kind
    folder.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows).replace_schema_metadata(metadata), folder / 'loadouts.parquet', compression='snappy')
    folder.joinpath('matchups').mkdir(exist_ok=True)
    keep = set()
    for i, setup in enumerate(setups):
        name = f"{setup['candidate_id']}.parquet"
        table = pa.table({'row_index': pa.array([i], type=pa.int32()),
                          'candidate_id': pa.array([setup['candidate_id']], type=pa.int32()),
                          'net_hp_pp': pa.array([net[i].tolist()], type=pa.list_(pa.float64()))}).replace_schema_metadata(metadata)
        path = folder / 'matchups' / f'{i // 100:03}' / name
        keep.add(path.relative_to(folder / 'matchups'))
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, path, compression='snappy')
        restored = pq.read_table(path)['net_hp_pp'].to_pylist()
        assert np.array_equal(np.array(restored[0]), net[i])
    for path in folder.joinpath('matchups').rglob('*.parquet'):
        if path.relative_to(folder / 'matchups') not in keep:
            path.unlink()
    for directory in sorted(folder.joinpath('matchups').iterdir()):
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
    winners = {k: scenario[k]['candidate_id'] for k in ('most_wins', 'best_mean_trade', 'best_weighted_win_rate', 'best_weighted_mean_trade')}
    for path in folder.glob('matrix-*.parquet'):
        path.unlink()
    print(f'{kind}: {n:,} loadouts, {n*n:,} double-precision matrix entries, all scores verified', flush=True)
    return {'count': n, 'opponents_per_setup': n-1, 'loadouts': f'{kind}/loadouts.parquet',
            'matrix_directory': f'{kind}/matchups/', 'winners': winners, 'hp': scenario['hp'],
            'source_sha256': hashlib.sha256((source / f'{kind}_valid_setups.jsonl').read_bytes()).hexdigest()}, {x['id'] for s in setups for x in s['items']}


CATALOG = {r['id']: r for r in json.loads((ROOT / 'data/catalog.json').read_text())}
if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    categories, ids = {}, set()
    for kind in ('submachine', 'rifle'):
        categories[kind], used = export_category(kind)
        ids |= used
    items = []
    for ident in sorted(ids):
        c = CATALOG[ident]
        tier = 'gold1' if c.get('kind') == 'ammo' else 'epic1'
        def icon(path):
            return 'icons/' + path.split('/item/')[1].replace('/', '_') if path else None
        items.append({'id': ident, 'name': {'accuracy_all': 'Universal Accuracy', 'accuracy_rifle': 'Rifle Accuracy'}.get(ident, NAMES.get(ident, c['name'])), 'width': c['size'][0], 'height': c['size'][1],
                      'type': c['type'], 'kind': c.get('kind'), 'tier': tier, 'effects': effect_text(ident),
                      'image': icon(c.get('imgGold') if tier == 'gold1' else c['img']), 'overlay': icon(c.get('imgIcon'))})
    manifest = {'schema_version': 1, 'scenario': {'class': 'Rogue', 'level': 200, 'attack': 10000, 'endurance': 10000,
                'base_crit': .5, 'anti_crit': .4, 'min_area': 92, 'max_area': 96, 'width': 12, 'height': 8},
                'tie_epsilon': EPS, 'categories': categories, 'items': items,
                'matrix_orientation': 'row = our setup; list index = opponent row_index; positive = our advantage',
                'weighting': 'opponent unweighted wins; exclude self; draws contribute zero; all-zero weights fall back to uniform'}
    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Total Parquet size:', sum(p.stat().st_size for p in OUT.rglob('*.parquet')), 'bytes')
