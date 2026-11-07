"""Compare FULL valid defensive-core setups with each category's win-rate winner."""
import json
from pathlib import Path

from analyze_counters import fighter, shot

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {'camouflage', 'camouflage_suit', 'vigilance'}


def main():
    report = {'required_items': sorted(REQUIRED), 'categories': {}}
    for kind in ('submachine', 'rifle'):
        scenario = json.loads((ROOT / 'results' / f'{kind}_results.json').read_text())
        candidates = []
        for line in (ROOT / 'results' / f'{kind}_valid_setups.jsonl').open():
            setup = json.loads(line)
            ids = {x['id'] for x in setup['items']}
            if not REQUIRED <= ids:
                continue
            candidates.append((setup, fighter(setup, scenario)))
        selections = {}
        for objective in ('most_wins', 'best_mean_trade', 'best_weighted_win_rate', 'best_weighted_mean_trade'):
            winner = scenario[objective]
            champion = fighter(winner, scenario)
            rows = []
            for setup, other in candidates:
                if setup['candidate_id'] == winner['candidate_id']:
                    continue
                outgoing, land_out = shot(other, champion)
                incoming, land_in = shot(champion, other)
                outgoing_pct = 100 * outgoing / scenario['hp']
                incoming_pct = 100 * incoming / scenario['hp']
                rows.append({'setup': setup, 'core_setup_damage_hp_percent': outgoing_pct,
                             'champion_damage_hp_percent': incoming_pct,
                             'core_setup_net_hp_pp': outgoing_pct - incoming_pct,
                             'core_setup_land_percent': 100 * land_out,
                             'champion_land_percent': 100 * land_in})
            rows.sort(key=lambda r: (-r['core_setup_net_hp_pp'], r['setup']['candidate_id']))
            assert rows
            beats = [r for r in rows if r['core_setup_net_hp_pp'] > 1e-10]
            ties = [r for r in rows if abs(r['core_setup_net_hp_pp']) <= 1e-10]
            selections[objective] = {'champion': winner, 'full_valid_core_setups_tested': len(rows),
                      'core_setups_beating_champion': len(beats), 'draws': len(ties),
                      'core_setups_losing_to_champion': len(rows) - len(beats) - len(ties),
                      'strongest_against_champion': rows[0], 'all_beating_champion': beats,
                      'closest_to_draw': min(rows, key=lambda r: (abs(r['core_setup_net_hp_pp']), r['setup']['candidate_id'])),
                      'top_5_against_champion': rows[:5]}
            print(kind, objective, 'tested', len(rows), 'beaten by', len(beats),
                  'strongest counter', rows[0]['setup']['candidate_id'],
                  'counter net pp', rows[0]['core_setup_net_hp_pp'])
        report['categories'][kind] = {'selections': selections}
    (ROOT / 'results' / 'full_defensive_core_vs_champions.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
