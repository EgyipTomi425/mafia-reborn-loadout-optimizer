"""Find every expected-trade loss of the highest-win-rate setups, locally."""
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
VARIANTS = {(v['id'], v['tier']): v for v in json.loads(
    (ROOT / 'data' / 'variants.json').read_text())}


def fighter(setup, scenario):
    s = {}
    for item in setup['items']:
        ident = item['id']
        tier = 'gold1' if ident.startswith(('full_metal_', 'soft_nosed_', 'tracer_')) else 'epic1'
        for key, value in VARIANTS[ident, tier]['effects'].items():
            s[key] = s.get(key, 0) + value
    raw = 8.5 * scenario['level'] * 1.15
    low = int(np.floor(raw / 2.12))
    rolls = np.arange(low, int(np.floor(raw + .5)) - low + 1)
    pre = np.floor(.055 * scenario['attack'] * (1 + s.get('damageBuffPerc', 0))
                   * rolls[:, None] * np.array([1, 2 + s.get('critDamageBuffPerc', 0)])
                   * (1 + s.get('damageVsRoguePerc', 0)) + .5)
    pc = (.5 + s.get('critChanceBuffPerc', 0)) * .6
    landed = []
    for resist in (0, .14):
        damage = np.floor(np.maximum(2, pre * (1 - .25 - resist)) + .5)
        def primitive(x):
            y = x + .5
            n = np.floor(y)
            return n * y - n * (n + 1) / 2
        bonus = (primitive(.2 * damage) - primitive(.1 * damage)) / (.1 * damage)
        total = damage + s.get('doubleShotChanceBuffPerc', 0) * bonus * (damage < scenario['hp'])
        landed.append(float(np.mean(total @ np.array([1 - pc, pc]))))
    return {'accuracy': 1.17 + s.get('accuracyBuffPerc', 0),
            'dodge': .101 + s.get('dodgeBuffPerc', 0),
            'camouflage': s.get('hitChanceReductionPerc', 0),
            'vest': int(s.get('damageResistancePerc', 0) > 0), 'landed': landed}


def shot(a, b):
    probability = np.clip(a['accuracy'] - b['camouflage'], 0, 1) * (1 - b['dodge'])
    return float(probability * a['landed'][b['vest']]), float(probability)


def main():
    report = {}
    for kind in ('submachine', 'rifle'):
        scenario = json.loads((ROOT / 'results' / f'{kind}_results.json').read_text())
        winner = scenario['most_wins']
        baseline = fighter(winner, scenario)
        base_ids = {x['id'] for x in winner['items']}
        counters = []
        wins = ties = losses = 0
        for line in (ROOT / 'results' / f'{kind}_valid_setups.jsonl').open():
            opponent = json.loads(line)
            if opponent['candidate_id'] == winner['candidate_id']:
                continue
            other = fighter(opponent, scenario)
            outgoing, land_out = shot(baseline, other)
            incoming, land_in = shot(other, baseline)
            out_percent, in_percent = 100 * outgoing / scenario['hp'], 100 * incoming / scenario['hp']
            net = out_percent - in_percent
            if net < -1e-10:
                losses += 1
                ids = {x['id'] for x in opponent['items']}
                counters.append({
                    'opponent': opponent,
                    'winner_damage_enemy_hp_percent': out_percent,
                    'opponent_damage_winner_hp_percent': in_percent,
                    'winner_net_hp_pp': net,
                    'winner_land_chance_percent': 100 * land_out,
                    'opponent_land_chance_percent': 100 * land_in,
                    'removed_from_winner': sorted(base_ids - ids),
                    'added_to_winner': sorted(ids - base_ids),
                })
            elif net > 1e-10:
                wins += 1
            else:
                ties += 1
        assert (wins, ties, losses) == (winner['wins'], winner['ties'], winner['losses'])
        counters.sort(key=lambda c: (c['winner_net_hp_pp'], c['opponent']['candidate_id']))
        report[kind] = {'winner_id': winner['candidate_id'], 'winner_items': sorted(base_ids),
                        'wins': wins, 'ties': ties, 'losses': losses, 'counters': counters}
    output = ROOT / 'results' / 'highest_win_rate_counters.json'
    output.write_text(json.dumps(report, indent=2) + '\n')
    for kind, entry in report.items():
        print(kind, 'winner', entry['winner_id'])
        for row in entry['counters']:
            print(json.dumps({k: v for k, v in row.items() if k != 'opponent'}),
                  'opponent_id', row['opponent']['candidate_id'])


if __name__ == '__main__':
    main()
