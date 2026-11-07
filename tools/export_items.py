"""Generate C++ input from the supplied local snapshot; no network/dependencies."""
import json
import pathlib
import sys

root, output = map(pathlib.Path, sys.argv[1:])
catalog = json.loads((root / 'catalog.json').read_text())
variants = {(v['id'], v['tier']): v for v in json.loads((root / 'variants.json').read_text())}
fields = ['accuracyBuffPerc', 'dodgeBuffPerc', 'hitChanceReductionPerc',
          'critDamageBuffPerc', 'damageBuffPerc', 'damageResistancePerc',
          'doubleShotChanceBuffPerc', 'critChanceBuffPerc', 'damageVsRoguePerc']
inert = {'firstBlowBuffPerc', 'healBuffPerc', 'explosionResistancePerc',
         'damageVsTacticianPerc', 'fightThrowChance'}
lines = ['// Generated from local catalog.json and variants.json.', '#pragma once',
         '#include "model.hpp"', 'inline std::vector<Item> input_items(int kind) {',
         'std::vector<Item> out;', 'if (kind == 0) {']
for k, kind in enumerate(('submachine', 'rifle')):
    if k:
        lines.append('} else {')
    weapon = 'mp8' if k == 0 else 'ak_24_7'
    suffix = 'small' if k == 0 else 'large'
    ids = [(weapon, 'epic1', 0)]
    ids += [(f'{family}_{suffix}', 'gold1', 1) for family in
            ('soft_nosed_bullet', 'tracer_ammunition')]
    options = [x['id'] for x in catalog if x['type'] in ('skill', 'accessory')
               and x['id'] != 'riot_shield'
               and kind in x.get('weaponKind', [kind])]
    assert len(options) == 15
    ids += [(i, 'epic1', 2) for i in options]
    for ident, tier, role in ids:
        v = variants[ident, tier]
        compatible = v.get('compatibleWeapons', [])
        if compatible and kind not in compatible:
            raise ValueError(('Incompatible item', ident, kind, compatible))
        if role == 1:
            assert tier == 'gold1' and v['kind'] == 'ammo'
            assert ident.endswith('_' + suffix)
        unknown = set(v['effects']) - set(fields) - inert
        if unknown:
            raise ValueError((ident, unknown))
        stats = ','.join(repr(v['effects'].get(f, 0.0)) for f in fields)
        lines.append('out.push_back(Item{%s,%d,%d,%d,{%s}});' %
                     (json.dumps(ident), v['width'], v['height'], role, stats))
lines += ['}', 'return out;', '}']
output.write_text('\n'.join(lines) + '\n')
