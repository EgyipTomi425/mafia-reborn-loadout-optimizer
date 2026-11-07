"""Record reproducible evidence from the supplied game-client snapshot."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
catalog_path = DATA / 'client' / 'ItemImg-DP5zsOkH.js'
fight_path = DATA / 'client' / 'computeFight-PcsHNWeo.js'
catalog, fight = catalog_path.read_text(), fight_path.read_text()
definition = 'rapid_fire:{id:`rapid_fire`'
tiers = 'if(e==`rapid_fire`)switch(t)'
activation = 'let u=b(t).doubleShotChanceBuffPerc??0'


def excerpt(source, start, length):
    i = source.index(start)
    return source[i:i + length]


item_excerpt = excerpt(catalog, definition, 235)
tier_excerpt = excerpt(catalog, tiers, 310)
fight_excerpt = excerpt(fight, activation, 185)
assert 'size:[3,3]' in item_excerpt
assert 'case`epic1`:return{doubleShotChanceBuffPerc:.17}' in tier_excerpt
assert 'n.life>l' in fight_excerpt
assert '!c.isMiss&&!c.isDodged' in fight_excerpt
assert 'Math.round(l*r.float(.1,.2))' in fight_excerpt
variant = next(v for v in json.loads((DATA / 'variants.json').read_text())
               if v['id'] == 'rapid_fire' and v['tier'] == 'epic1')
assert variant['effects']['doubleShotChanceBuffPerc'] == .17
report = {
    'basis': 'supplied local client snapshot, 2026-11-07',
    'live_verification': 'Verification is against the bundled offline client snapshot; live server behavior is outside this run.',
    'item': variant,
    'mean_extra_damage_fraction_on_nonlethal_hit_before_rounding': .17 * .15,
    'sources': [
        {'path': str(catalog_path.relative_to(ROOT)),
         'sha256': hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
         'definition_excerpt': item_excerpt, 'tiers_excerpt': tier_excerpt},
        {'path': str(fight_path.relative_to(ROOT)),
         'sha256': hashlib.sha256(fight_path.read_bytes()).hexdigest(),
         'combat_excerpt': fight_excerpt},
    ],
}
(ROOT / 'evidence').mkdir(exist_ok=True)
(ROOT / 'evidence' / 'rapid_fire_verification.json').write_text(json.dumps(report, indent=2) + '\n')
print('Rapid Fire verified in local client: 3x3, Epic1 17%, +10-20% nonlethal landed damage.')
