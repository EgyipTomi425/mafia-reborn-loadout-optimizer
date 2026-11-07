"""Reproduce the full-field ammo comparison and near-optimal alternative findings."""
import csv
import json
from pathlib import Path

from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / 'results'
OBJECTIVES = {
    'most_wins': ('wins', 'mean_net_hp_pp'),
    'best_mean_trade': ('mean_net_hp_pp', 'wins'),
    'best_weighted_win_rate': ('weighted_win_rate', 'weighted_mean_net_hp_pp'),
    'best_weighted_mean_trade': ('weighted_mean_net_hp_pp', 'weighted_win_rate'),
}


def ammo(ident):
    return ident.startswith(('soft_nosed_bullet_', 'tracer_ammunition_'))


def main():
    sensitivity, ammo_comparison = {}, {}
    for kind in ('submachine', 'rifle'):
        summary = json.loads((RESULTS / f'{kind}_results.json').read_text())
        rows = list(csv.DictReader((RESULTS / f'{kind}_rankings.csv').open()))
        identities = lambda r: set(r['item_ids'].split(';'))
        nonammo = lambda ids: frozenset(i for i in ids if not ammo(i))
        report = {'correlations': {}, 'best_different_gear': {}}
        for a, b in [('wins', 'mean_net_hp_pp'), ('wins', 'weighted_win_rate'),
                     ('mean_net_hp_pp', 'weighted_mean_net_hp_pp')]:
            report['correlations'][a + ' vs ' + b] = float(spearmanr(
                [float(r[a]) for r in rows], [float(r[b]) for r in rows]).statistic)
        for objective, (primary, secondary) in OBJECTIVES.items():
            winner = summary[objective]
            winner_ids = {i['id'] for i in winner['items']}
            candidates = [r for r in rows if nonammo(identities(r)) != nonammo(winner_ids)]
            rival = min(candidates, key=lambda r: (-float(r[primary]), -float(r[secondary]), int(r['candidate_id'])))
            report['best_different_gear'][objective] = {
                'winner_id': winner['candidate_id'], 'rival_id': int(rival['candidate_id']),
                'wins': int(rival['wins']),
                'win_rate_percent': 100 * int(rival['wins']) / summary['opponents_per_setup'],
                'mean_net_hp_pp': float(rival['mean_net_hp_pp']),
                'weighted_win_rate_percent': 100 * float(rival['weighted_win_rate']),
                'weighted_mean_net_hp_pp': float(rival['weighted_mean_net_hp_pp']),
                'removed_from_winner': sorted(winner_ids - identities(rival)),
                'added_to_winner': sorted(identities(rival) - winner_ids),
            }
        sensitivity[kind] = report
        bases = {nonammo({i['id'] for i in summary[k]['items']}) for k in OBJECTIVES}
        ammo_comparison[kind] = []
        for row in rows:
            if nonammo(identities(row)) not in bases:
                continue
            ammo_comparison[kind].append({
                'id': int(row['candidate_id']), 'ammo': sorted(i for i in identities(row) if ammo(i)),
                'opponents': summary['opponents_per_setup'],
                'wins': int(row['wins']), 'ties': int(row['ties']), 'losses': int(row['losses']),
                'win_rate_percent': 100 * int(row['wins']) / summary['opponents_per_setup'],
                'mean_net_hp_pp': float(row['mean_net_hp_pp']),
                'weighted_win_rate_percent': 100 * float(row['weighted_win_rate']),
                'weighted_mean_net_hp_pp': float(row['weighted_mean_net_hp_pp']),
            })
    (RESULTS / 'objective_sensitivity_analysis.json').write_text(json.dumps(sensitivity, indent=2) + '\n')
    (RESULTS / 'ammo_full_field_comparison.json').write_text(json.dumps({
        'method': 'Every caliber-compatible ammo variant is ranked against the entire valid field; direct head-to-head contributes one opponent outcome.',
        'categories': ammo_comparison}, indent=2) + '\n')
    print('Full-field ammo and near-optimal alternative findings reproduced.')


if __name__ == '__main__':
    main()
