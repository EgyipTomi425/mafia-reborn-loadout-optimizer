"""Rebuild all outcomes and opponent weights on CPU, without trusting GPU wins.

Uses only saved item lists and scenario parameters as combat inputs. GPU CSV
scores are opened AFTER the CPU matrices and all four scores are computed.
"""
import csv
from fractions import Fraction
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from analyze_counters import fighter


def recheck(kind):
    out = ROOT / 'results'
    scenario = json.loads((out / f'{kind}_results.json').read_text())
    setups = [json.loads(line) for line in (out / f'{kind}_valid_setups.jsonl').open()]
    n = len(setups)
    fighters = [fighter(row, scenario) for row in setups]
    accuracy = np.array([f['accuracy'] for f in fighters])
    dodge = np.array([f['dodge'] for f in fighters])
    camouflage = np.array([f['camouflage'] for f in fighters])
    vest = np.array([f['vest'] for f in fighters])
    landed = np.array([f['landed'] for f in fighters])
    net = np.empty((n, n))
    for i in range(n):
        outgoing = np.clip(accuracy[i] - camouflage, 0, 1) * (1 - dodge) * landed[i, vest]
        incoming = np.clip(accuracy - camouflage[i], 0, 1) * (1 - dodge[i]) * landed[:, vest[i]]
        net[i] = 100 * (outgoing - incoming) / scenario['hp']
    assert np.max(np.abs(net + net.T)) < 1e-10
    assert np.max(np.abs(np.diag(net))) < 1e-10
    won = net > 1e-10
    wins = won.sum(axis=1)
    losses = (net < -1e-10).sum(axis=1)
    ties = n - 1 - wins - losses
    means = net.sum(axis=1) / (n - 1)
    # Entirely CPU-derived integer strengths. The common divisor N-1 cancels.
    strengths = wins.astype(np.int64)
    denominators = strengths.sum() - strengths
    numerators = won @ strengths
    weighted_wins = np.divide(numerators, denominators,
                              out=wins.astype(float) / (n - 1), where=denominators > 0)
    weighted_means = np.divide(net @ strengths, denominators,
                               out=means.copy(), where=denominators > 0)
    rates = wins / (n - 1)
    # Equal weights must recover the unweighted definitions exactly.
    uniform = np.ones(n)
    assert np.allclose((won @ uniform)/(n-1), rates, rtol=0, atol=1e-14)
    assert np.allclose((net @ uniform)/(n-1), means, rtol=0, atol=1e-9)
    ids = [s['candidate_id'] for s in setups]
    # Inspect GPU results only after weights and every CPU score exist.
    gpu = {int(r['candidate_id']): r for r in csv.DictReader((out / f'{kind}_rankings.csv').open())}
    max_rate_error = max_mean_error = 0.0
    for i, ident in enumerate(ids):
        r = gpu[ident]
        assert (int(r['wins']), int(r['ties']), int(r['losses'])) == (wins[i], ties[i], losses[i])
        assert abs(float(r['mean_net_hp_pp']) - means[i]) < 1e-9
        er = abs(float(r['weighted_win_rate']) - weighted_wins[i])
        em = abs(float(r['weighted_mean_net_hp_pp']) - weighted_means[i])
        assert er < 1e-12 and em < 1e-9
        max_rate_error = max(max_rate_error, er)
        max_mean_error = max(max_mean_error, em)
    index = {ident: i for i, ident in enumerate(ids)}
    def exact_rate(i):
        return Fraction(int(numerators[i]), int(denominators[i])) if denominators[i] else Fraction(int(wins[i]), n-1)
    plans = {
        'most_wins': (rates, lambda i: (-int(wins[i]), -means[i], ids[i])),
        'best_mean_trade': (means, lambda i: (-means[i], -int(wins[i]), ids[i])),
        'best_weighted_win_rate': (weighted_wins, lambda i: (-exact_rate(i), -weighted_means[i], ids[i])),
        'best_weighted_mean_trade': (weighted_means, lambda i: (-weighted_means[i], -exact_rate(i), ids[i])),
    }
    report = {'category': kind, 'setups': n, 'unordered_pairs': n * (n-1) // 2,
              'weights_derived_from_cpu_outcomes_only': True,
              'max_weighted_win_rate_error_percentage_points': 100 * max_rate_error,
              'max_weighted_mean_error_hp_pp': max_mean_error, 'objectives': {}}
    for objective, (values, sorter) in plans.items():
        order = sorted(range(n), key=sorter)
        selected = index[scenario[objective]['candidate_id']]
        top = order[0]
        assert values[top] - values[selected] < 1e-10
        primary_ties = [i for i in order if abs(values[i] - values[top]) <= 1e-12]
        if objective == 'best_weighted_win_rate':
            assert max(weighted_means[i] for i in primary_ties) - weighted_means[selected] < 1e-9
        if objective == 'best_weighted_mean_trade':
            assert max(weighted_wins[i] for i in primary_ties) - weighted_wins[selected] < 1e-12
        runner = next((i for i in order if values[top] - values[i] > 1e-12), None)
        factor = 100 if 'win' in objective else 1
        entry = {'gpu_selected_id': ids[selected], 'cpu_selected_id': ids[top],
                 'gpu_selected_is_cpu_optimum': True,
                 'primary_metric_ties_within_1e_minus_12': len(primary_ties),
                 'gap_to_next_distinct_primary_score_pp': None if runner is None else float(factor * (values[top] - values[runner])),
                 'next_distinct_primary_score_id': None if runner is None else ids[runner],
                 'top_5': [{'id': ids[i], 'win_rate_percent': float(100*rates[i]),
                            'weighted_win_rate_percent': float(100*weighted_wins[i]),
                            'mean_net_hp_pp': float(means[i]),
                            'weighted_mean_net_hp_pp': float(weighted_means[i])} for i in order[:5]]}
        report['objectives'][objective] = entry
        print(kind, objective, 'GPU', ids[selected], 'CPU', ids[top],
              'gap', entry['gap_to_next_distinct_primary_score_pp'], 'pp', flush=True)
    raw_win_order = sorted(range(n), key=plans['most_wins'][1])
    weighted_win_order = sorted(range(n), key=plans['best_weighted_win_rate'][1])
    raw_mean_order = sorted(range(n), key=plans['best_mean_trade'][1])
    weighted_mean_order = sorted(range(n), key=plans['best_weighted_mean_trade'][1])
    def compare_orders(before, after):
        positions_before = {i: pos for pos, i in enumerate(before)}
        positions_after = {i: pos for pos, i in enumerate(after)}
        changed = [i for i in range(n) if positions_before[i] != positions_after[i]]
        largest = sorted(changed, key=lambda i: -abs(positions_before[i]-positions_after[i]))[:5]
        return {'changed_positions': len(changed),
                'largest_changes': [{'id': ids[i], 'unweighted_rank': positions_before[i]+1,
                                     'weighted_rank': positions_after[i]+1} for i in largest]}
    report['win_rate_ranking_changes'] = compare_orders(raw_win_order, weighted_win_order)
    report['mean_trade_ranking_changes'] = compare_orders(raw_mean_order, weighted_mean_order)
    print(kind, 'changed rankings:', report['win_rate_ranking_changes']['changed_positions'],
          'win-rate positions,', report['mean_trade_ranking_changes']['changed_positions'], 'mean-trade positions', flush=True)
    assert not np.allclose(rates, weighted_wins, rtol=0, atol=1e-10)
    assert not np.allclose(means, weighted_means, rtol=0, atol=1e-10)
    return report


def synthetic_checks():
    # The user's 99% versus 1% example: direction of the opponent weighting.
    assert abs(np.dot([True, False], [99, 1])/100 - .99) < 1e-15
    assert abs(np.dot([False, True], [99, 1])/100 - .01) < 1e-15
    # A fixed-seed tournament demonstrates that weighting CAN change the winner.
    rng = np.random.default_rng(20261107)
    for _ in range(10000):
        upper = np.triu(rng.choice([-1, 1], size=(7, 7)), 1)
        matrix = upper - upper.T
        wins = (matrix > 0).sum(axis=1)
        den = wins.sum() - wins
        weighted = ((matrix > 0) @ wins)/den
        raw = int(np.argmax(wins))
        strong = int(np.argmax(weighted))
        if raw != strong and np.count_nonzero(wins == wins[raw]) == 1 and np.count_nonzero(weighted == weighted[strong]) == 1:
            return {'ratio_99_to_1_checked': True, 'uniform_weights_recover_unweighted_checked': True,
                    'synthetic_unique_winner_changes': True,
                    'synthetic_raw_winner_index': raw, 'synthetic_weighted_winner_index': strong,
                    'synthetic_raw_wins': wins.tolist(), 'synthetic_weighted_rates': weighted.tolist(),
                    'synthetic_pair_outcomes': matrix.tolist()}
    raise AssertionError('No counterexample to unchanged winners found')


if __name__ == '__main__':
    report = {'method': 'CPU all-pairs outcome matrix; weights independently derived from its row win counts; exact rational comparison of weighted win rates',
              'additional_checks': synthetic_checks(),
              'categories': [recheck(kind) for kind in ('submachine', 'rifle')]}
    (ROOT / 'results' / 'weighted_ranking_recheck.json').write_text(json.dumps(report, indent=2) + '\n')
