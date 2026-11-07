"""Verify selected non-Epic ammo against catalog, variants, shops and buy-price code."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
catalog = {i['id']: i for i in json.loads((DATA / 'catalog.json').read_text())}
variants = {(i['id'], i['tier']): i for i in json.loads((DATA / 'variants.json').read_text())}
shop_path = DATA / 'client' / 'shops-Jw99SdUE.js'
source = shop_path.read_text()
pool = source[source.index('var j='):source.index('],M=', source.index('var j=')) + 1]
shop = source[source.index('function P('):source.index('function F(')]
assert 'let n=t.draw(j)' in shop and 'id:n,quantity:250,level:e,tier:`gold1`' in shop
assert 'if(t===`gold1`)return{cash:0,gold:Math.ceil(r*D)}' in source
entries = []
for kind, caliber in [('submachine', 'small'), ('rifle', 'large')]:
    for family, effects in [('soft_nosed_bullet', {'damageBuffPerc': .11, 'critDamageBuffPerc': .21}),
                            ('tracer_ammunition', {'damageBuffPerc': .11, 'accuracyBuffPerc': .11})]:
        ident = f'{family}_{caliber}'
        c, v = catalog[ident], variants[ident, 'gold1']
        assert f'`{ident}`' in pool
        assert kind in c['weaponKind'] and kind in v['compatibleWeapons']
        assert all(v['effects'][key] == value for key, value in effects.items())
        entries.append({'weapon_category': kind, 'id': ident, 'tier': 'gold1',
                        'compatible_weapons': v['compatibleWeapons'], 'effects': v['effects']})
report = {'basis': 'local 2026-11-07 client snapshot', 'selected_ammunition': entries,
          'shop_pool_excerpt': pool, 'shop_generation_excerpt': shop,
          'shop_source_sha256': hashlib.sha256(shop_path.read_bytes()).hexdigest(),
          'scope': 'No Epic ammo. No FMJ. None or one caliber-compatible Gold1 Tracer/Soft-Nosed.'}
(ROOT / 'evidence').mkdir(exist_ok=True)
(ROOT / 'evidence' / 'ammunition_verification.json').write_text(json.dumps(report, indent=2) + '\n')
print('Verified: small=SMG, large=rifle; Gold1 Tracer +11% damage/+11pp accuracy; Soft-Nosed +11% damage/+21% crit damage.')
