"""Extract class constants from the client and reconstruct per-point comparisons."""
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
import hashlib
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
D = Decimal


def simple_map(body):
    result = {name: D(value) for name, value in re.findall(r'(tactician|rogue|bully):([.\d]+)', body)}
    assert set(result) == {'tactician', 'rogue', 'bully'}
    return result


def extract():
    default_path = ROOT/'data/client/getDefaultWeapon-D9rrY_Ti.js'
    weapon_path = ROOT/'data/client/generateWeaponStats-CtMnMigh.js'
    fight_path = ROOT/'data/client/computeFight-PcsHNWeo.js'
    default, weapon, fight = [p.read_text() for p in (default_path, weapon_path, fight_path)]
    hp = simple_map(re.search(r'var c=\{([^{}]+)\};function l', default).group(1))
    dodge = simple_map(re.search(r'var g=\{([^{}]+)\},_=50', fight).group(1))
    defense_part = default.split('function u(e)', 1)[1].split('function d(e)', 1)[0]
    reduction = {name: D(value) for name, value in re.findall(r'case`(\w+)`:return\s*([.\d]+)', defense_part)}
    assert set(reduction) == set(hp)
    parameters = {name: (D(per), D(base)) for name, per, base in
                  re.findall(r'(tactician|rogue|bully):\{perLevel:([.\d]+),base:([.\d]+)\}', weapon)}
    spread_maps = {key: simple_map(body) for key, body in
                   re.findall(r'([ria])=\{(tactician:[^{}]+)\}', weapon)}
    tiers = {name: {'multiplier': D(multiplier), 'accuracy': D(accuracy), 'spread': spread_maps[spread]}
             for name, multiplier, accuracy, spread in
             re.findall(r'(\w+):\{multiplier:([.\d]+),accuracy:([.\d]+),spread:([ria])\}', weapon)}
    attack_factor = D(re.search(r'var a=([.\d]+);function o', default).group(1))
    assert len(parameters) == 3 and len(tiers) == 8 and attack_factor == D('.055')
    assert 'Math.ceil(s(e)*(e.level+1)*c[e.spec])' in default
    assert 'Math.ceil(e.endurance*(1+(e.enduranceBuffPerc??0)))' in default
    assert 'h=(u*e+d)*f*s.float(.99,1.01),g=m[i]*s.float(.9,1.1),_=Math.floor(h/(2+g))' in weapon
    assert 'minDamage:_,maxDamage:Math.round(h)-_' in weapon
    generic = weapon.split('function n(e,t)',1)[1].split('var r=',1)[0]
    for fragment in [
        'case`pistol`:case`submachine`:return n?{critDamageBuffPerc:.15}:{}',
        'case`shotgun`:return{damageVsBullyPerc:-.15,damageVsTacticianPerc:.15,...n?{critDamageBuffPerc:.25}:{}',
        'case`rifle`:return{damageVsTacticianPerc:-.15,damageVsRoguePerc:.15,...n?{critChanceBuffPerc:.03}:{}',
        'case`sniper`:return{damageVsRoguePerc:-.15,damageVsBullyPerc:.15,...n?{critChanceBuffPerc:.05}:{}',
    ]:
        assert fragment in generic
    return hp, dodge, reduction, parameters, tiers, attack_factor


def nominal_weapon(name, level, parameters, tier):
    per, base = parameters[name]
    total = (per*level+base)*tier['multiplier']
    low = int((total/(2+tier['spread'][name])).to_integral_value(rounding=ROUND_FLOOR))
    high = int(total.to_integral_value(rounding=ROUND_HALF_UP))-low
    return total, low, high, D(low+high)/2


def reconstruct():
    hp, dodge, mitigation, parameters, tiers, attack_factor = extract()
    tier = tiers['epic1']
    assert tier['multiplier'] == D('1.15') and tier['accuracy'] == D('1.17')
    scenarios = []
    for level in (50, 200):
        for vigilance in (D('0'), D('.10')):
            values = {}
            for name in hp:
                total, low, high, mean = nominal_weapon(name, level, parameters, tier)
                survival = hp[name]/((1-mitigation[name])*(1-dodge[name]-vigilance))
                values[name] = {'weapon_mean': mean, 'survival': survival}
            rows = []
            for name in hp:
                a = values[name]['weapon_mean']/values['rogue']['weapon_mean']
                e = values[name]['survival']/values['rogue']['survival']
                rows.append({'class': name, 'attack': float(a), 'endurance': float(e),
                             'combat_percent': float(100*a*e), 'value': float((a*e).sqrt())})
            scenarios.append({'level': level, 'vigilance_bonus': float(vigilance), 'classes': rows})
    reference = next(s for s in scenarios if s['level'] == 50 and s['vigilance_bonus'] == .1)
    supplied = json.loads((ROOT/'data/class_reference.json').read_text())
    for row in supplied['classes']:
        actual = next(r for r in reference['classes'] if r['class'] == row['class'].lower())
        for key, tolerance in [('attack', .0005), ('endurance', .0005), ('combat_percent', .05), ('value', .0005)]:
            assert abs(actual[key]-row[key]) < tolerance, (row['class'], key, actual[key], row[key])
    no_vigilance = next(s for s in scenarios if s['level'] == 50 and s['vigilance_bonus'] == 0)
    level_200 = next(s for s in scenarios if s['level'] == 200 and s['vigilance_bonus'] == .1)
    assert abs(no_vigilance['classes'][0]['endurance']-.417) > .0005
    assert abs(no_vigilance['classes'][2]['endurance']-1.693) > .0005
    assert abs(level_200['classes'][0]['attack']-2.033) > .0005
    assert abs(level_200['classes'][2]['attack']-.607) > .0005
    per_point = []
    for name in hp:
        total, low, high, mean = nominal_weapon(name, 200, parameters, tier)
        gain = hp[name]*201
        h0 = math.ceil(10000*201*float(hp[name]))
        h1 = math.ceil(10001*201*float(hp[name]))
        finite_attack_gain = sum(math.floor(.055*10001*r+.5)-math.floor(.055*10000*r+.5)
                                 for r in range(low, high+1))/(high-low+1)
        slope = attack_factor*mean
        assert abs(finite_attack_gain-float(slope)) <= 1
        # Arithmetic-series identity: conditional mean is independent of spread.
        for spread_scale in (D('.9'), D('1'), D('1.1')):
            left = int((total/(2+tier['spread'][name]*spread_scale)).to_integral_value(rounding=ROUND_FLOOR))
            right = int(total.to_integral_value(rounding=ROUND_HALF_UP))-left
            assert D(left+right)/2 == mean
            assert D(sum(range(left, right+1)))/D(right-left+1) == mean
        per_point.append({'class': name, 'hp_multiplier': float(hp[name]),
                          'base_dodge_percent': float(100*dodge[name]),
                          'dodge_with_epic_vigilance_percent': float(100*(dodge[name]+D('.10'))),
                          'base_reduction_percent': float(100*mitigation[name]),
                          'reduction_with_epic_vest_percent': float(100*(mitigation[name]+D('.14'))),
                          'continuous_hp_per_endurance': float(gain),
                          'hp_at_10000_endurance': h0, 'exact_next_endurance_hp': h1-h0,
                          'effective_hp_per_endurance_without_vigilance': float(gain/((1-mitigation[name])*(1-dodge[name]))),
                          'effective_hp_per_endurance_with_vigilance': float(gain/((1-mitigation[name])*(1-dodge[name]-D('.10')))),
                          'weapon_per_level': float(parameters[name][0]), 'weapon_base': float(parameters[name][1]),
                          'epic_spread': float(tier['spread'][name]), 'nominal_epic_sum': float(total),
                          'nominal_weapon_min': low, 'nominal_weapon_max': high,
                          'mean_roll': float(mean), 'continuous_damage_per_attack': float(slope),
                          'rounded_mean_damage_gain_at_attack_10000': finite_attack_gain})
    assert [(r['nominal_weapon_min'], r['nominal_weapon_max']) for r in per_point] == [(1826,2100),(922,1033),(562,614)]
    assert [r['exact_next_endurance_hp'] for r in per_point] == [402,774,885]
    paths = ['getDefaultWeapon-D9rrY_Ti.js', 'generateWeaponStats-CtMnMigh.js', 'computeFight-PcsHNWeo.js']
    result = {'scope': 'Source-derived class constants; nominal Epic1 generation with both generation random factors set to 1; no target-specific weapon bonuses.',
              'reference_reconstruction_matches_displayed_values': True,
              'reference_context': {'level': 50, 'weapon_tier': 'epic1', 'vigilance_on_all_classes': True,
                                    'example_raw_attack': 1000, 'example_raw_endurance': 1000,
                                    'common_base_crit': .5, 'common_anti_crit': .4,
                                    'vigilance_bonus': .1, 'vest': False, 'camouflage': False,
                                    'weapon_example': 'same generic SMG category for all classes; shared hit/crit factors cancel'},
              'source_sha256': {name: hashlib.sha256((ROOT/'data/client'/name).read_bytes()).hexdigest() for name in paths},
              'wrong_context_checks': {'removing_vigilance_does_not_reproduce_end_coefficients': True,
                                       'using_level_200_does_not_reproduce_attack_coefficients': True},
              'generic_epic_weapon_bonuses_checked_against_client': True,
              'scenario_comparisons': scenarios, 'per_point_at_level_200': per_point,
              'luck_gain_pp_per_point_before_cap_at_level_200': float(100/(D('40.38')*200)),
              'anti_crit_gain_pp_per_point_before_cap_at_level_200': float(100/(D('44.27')*200))}
    (ROOT/'results/class_mechanics.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


if __name__ == '__main__':
    reconstruct()
    print('Source-derived class mechanics and level-50 Vigilance reconstruction verified.')
