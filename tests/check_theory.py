"""Check the algebra and numerical examples stated in the README."""
import json
import math
import sys
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from class_math import reconstruct


def main():
    mechanics = reconstruct()
    classes = json.loads((ROOT / 'data' / 'class_reference.json').read_text())
    calculated = []
    for row in classes['classes']:
        product = row['attack'] * row['endurance']
        value = math.sqrt(product)
        assert abs(100 * product - row['combat_percent']) < .051
        assert abs(value - row['value']) < .00051
        calculated.append({'class': row['class'], 'combat_percent_from_rounded_inputs': 100 * product,
                           'value_from_rounded_inputs': value})
    # Equal-cost allocation: brute force confirms the concave product maximum.
    budget = 2000
    best = max(range(1, budget), key=lambda attack: attack * (budget - attack))
    assert best == budget // 2
    for budget_case in range(2, 251):
        products = [a*(budget_case-a) for a in range(1,budget_case)]
        assert max(products) == (budget_case//2)*(budget_case-budget_case//2)
        for a in range(1,budget_case):
            e = budget_case-a
            # Exact integer form of AE = P^2/4 - (A-E)^2/4.
            assert 4*a*e == budget_case**2-(a-e)**2
    assert 4*60*40/(100**2) == .96
    # Unequal prices: equal budget spending, rather than equal raw stat points.
    budget, price_a, price_e = 1200, 2, 3
    candidates = [(a, (budget - price_a*a)//price_e) for a in range(1, budget//price_a)]
    a, e = max(candidates, key=lambda row: row[0]*row[1])
    assert (a, e) == (budget/(2*price_a), budget/(2*price_e))
    # Single-exchange margin: its optimum is different from the product optimum.
    budget, alpha, beta = 20000, .001, 40000
    end_star = math.sqrt(beta/alpha)
    score = lambda endurance: alpha*(budget-endurance)-beta/endurance
    integer_best = max(range(1, budget), key=score)
    assert integer_best in (math.floor(end_star), math.ceil(end_star))
    assert score(integer_best) > score(budget/2)
    level = 200
    luck = int((Decimal('.5')*Decimal('40.38')*level).to_integral_value(rounding=ROUND_CEILING))
    toughness = int((Decimal('.4')*Decimal('44.27')*level).to_integral_value(rounding=ROUND_CEILING))
    assert (luck, toughness) == (4038, 3542)
    strict_float_luck = math.ceil(.5*(40.38*level))
    assert strict_float_luck == 4039
    assert min(.5, 4038/(40.38*level)) < .5
    assert abs(min(.5, 4038/(40.38*level))-.5) < 1e-15
    assert min(.5, strict_float_luck/(40.38*level)) == .5
    source = (ROOT/'data/client/getDefaultWeapon-D9rrY_Ti.js').read_text()
    assert '40.38*e.level' in source and '44.27*e.level' in source
    assert 'tactician:2,rogue:3.85,bully:4.4' in source
    assert abs((1.17-.55)*(1-.201)-.49538) < 1e-12
    assert abs(1-.25-.14-.61) < 1e-12
    result = {'class_reference_arithmetic': calculated,
              'class_reference_reconstructed_with_vigilance_at_level_50': mechanics['reference_reconstruction_matches_displayed_values'],
              'source_derived_class_mechanics_checked': True,
              'allocation_square_identity_checked_for_budgets_2_to_250': True,
              'balanced_allocation_product_checked': True,
              'unequal_price_allocation_checked': True,
              'single_exchange_margin_has_different_optimum_checked': True,
              'level_200_no_buff_luck_cap': luck,
              'level_200_strict_binary_float_luck_saturation': strict_float_luck,
              'level_200_no_buff_toughness_cap': toughness}
    (ROOT/'results').mkdir(exist_ok=True)
    (ROOT/'results/theory_checks.json').write_text(json.dumps(result, indent=2)+'\n')
    print('Theory checks passed: reference arithmetic, constrained optima, caps, and combat examples.')


if __name__ == '__main__':
    main()
