"""Draw the exact CUDA layouts with locally available game icons (no network)."""
import json
from pathlib import Path
import textwrap

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
CATALOG = {x['id']: x for x in json.loads((DATA / 'catalog.json').read_text())}
VARIANTS = {(v['id'], v['tier']): v for v in json.loads((DATA / 'variants.json').read_text())}
ART = ROOT / 'assets' / 'png'
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
BOLD = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
NAMES = {
    'accuracy_submachine': 'SMG Accuracy', 'specialization_submachine': 'SMG Specialization',
    'specialization_rifle': 'Rifle Specialization', 'soft_nosed_bullet_small': 'Soft-Nosed Gold1 (small)',
    'soft_nosed_bullet_large': 'Soft-Nosed Gold1 (large)', 'holo_sight': 'Holographic Visor',
    'tracer_ammunition_small': 'Tracer Gold1 (small)', 'tracer_ammunition_large': 'Tracer Gold1 (large)',
    'thermal_telescopic_sight': 'Thermal Sight', 'tactical_telescopic_sight': 'Tactical Sight',
}


def effect_text(ident):
    tier = 'gold1' if CATALOG[ident].get('kind') == 'ammo' else 'epic1'
    v = VARIANTS[ident, tier]
    s = v['effects']
    fields = [
        ('accuracyBuffPerc', 'accuracy', 'pp'), ('damageBuffPerc', 'damage', '%'),
        ('critDamageBuffPerc', 'crit damage', '%'), ('critChanceBuffPerc', 'crit chance', 'pp'),
        ('damageVsRoguePerc', 'damage vs Rogue', '%'), ('dodgeBuffPerc', 'dodge', 'pp'),
        ('damageResistancePerc', 'damage reduction', 'pp'),
    ]
    values = ['117% base accuracy'] if v['type'] == 'weapon' else []
    for key, label, unit in fields:
        if s.get(key):
            values.append(f"{s[key] * 100:+g}{unit} {label}")
    if s.get('hitChanceReductionPerc'):
        values.append(f"Enemy hit chance −{100 * s['hitChanceReductionPerc']:g}pp")
    if s.get('doubleShotChanceBuffPerc'):
        values.append(f"{100 * s['doubleShotChanceBuffPerc']:g}% proc: +10–20% landed damage")
    if s.get('firstBlowBuffPerc'):
        values.append(f"{100 * s['firstBlowBuffPerc']:+g}pp initiative (inactive in this trade)")
    if s.get('healBuffPerc'):
        values.append(f"{100 * s['healBuffPerc']:+g}% healing (no healing item here)")
    return ' · '.join(values)


def font(size, bold=False):
    return ImageFont.truetype(BOLD if bold else FONT, size)


def text(draw, xy, value, size=22, color='#e7eef7', bold=False, anchor=None):
    draw.text(xy, value, font=font(size, bold), fill=color, anchor=anchor)


def asset(path):
    if not path:
        return None
    filename = path.split('/item/', 1)[1].replace('/', '_').replace('.svg', '.png')
    local = ART / filename
    if not local.exists():
        return None
    icon = Image.open(local).convert('RGBA')
    box = icon.getchannel('A').getbbox()
    return icon.crop(box) if box else icon


def paste(image, icon, box, scale=1):
    if icon is None:
        return
    x, y, w, h = box
    ratio = min(w * scale / icon.width, h * scale / icon.height)
    icon = icon.resize((max(1, int(icon.width * ratio)), max(1, int(icon.height * ratio))), Image.Resampling.LANCZOS)
    image.paste(icon, (int(x + (w - icon.width) / 2), int(y + (h - icon.height) / 2)), icon)


def card(image, x, y, summary, key, title, core_result):
    draw = ImageDraw.Draw(image)
    row = summary[key]
    opponents = summary['opponents_per_setup']
    assert row['wins'] + row['ties'] + row['losses'] == opponents
    win_rate = 100 * row['wins'] / opponents
    draw_rate = 100 * row['ties'] / opponents
    loss_rate = 100 * row['losses'] / opponents
    weighted = key.startswith('best_weighted')
    draw.rounded_rectangle((x, y, x + 1140, y + 1495), 24, fill='#172436', outline='#354d65', width=2)
    text(draw, (x + 35, y + 28), title, 34, bold=True)
    if weighted:
        text(draw, (x + 35, y + 83), f"WEIGHTED WIN RATE: {100 * row['weighted_win_rate']:.4f}%", 29, '#90e3c0', True)
        text(draw, (x + 35, y + 122), f"WEIGHTED AVG TRADE: {row['weighted_mean_net_hp_pp']:+.6f} pp", 28, '#90e3c0', True)
        text(draw, (x + 35, y + 161), f"Unweighted: {win_rate:.4f}% wins · Average trade {row['mean_net_hp_pp']:+.6f} pp", 23)
    else:
        text(draw, (x + 35, y + 83), f"WIN RATE: {win_rate:.4f}%   |   DRAW {draw_rate:.4f}%   |   LOSS {loss_rate:.4f}%", 27, '#90e3c0', True)
        text(draw, (x + 35, y + 122), f"AVG TRADE: {row['mean_net_hp_pp']:+.6f} pp net HP advantage", 28, '#90e3c0', True)
        text(draw, (x + 35, y + 161), f"{row['wins']:,} wins / {row['ties']:,} draws / {row['losses']:,} losses · {opponents:,} opponents", 23)
    text(draw, (x + 35, y + 196), f"{row['area']}/96 cells · Setup #{row['candidate_id']} · All opponents within the same weapon category", 20, '#adc0d5')
    gx, gy, cell = x + 78, y + 258, 80
    used = set()
    for item in row['items']:
        w, h = CATALOG[item['id']]['size']
        for yy in range(item['y'], item['y'] + h):
            for xx in range(item['x'], item['x'] + w):
                assert 0 <= xx < 12 and 0 <= yy < 8 and (xx, yy) not in used
                used.add((xx, yy))
    assert len(used) == row['area']
    for xx in range(12):
        text(draw, (gx + xx * cell + cell / 2, gy - 22), str(xx + 1), 19, '#adc0d5', anchor='mm')
    for yy in range(8):
        text(draw, (gx - 24, gy + yy * cell + cell / 2), chr(65 + yy), 19, '#adc0d5', anchor='mm')
        for xx in range(12):
            draw.rectangle((gx + xx * cell, gy + yy * cell, gx + (xx + 1) * cell, gy + (yy + 1) * cell),
                           fill='#0b1522', outline='#3b5065')
    for index, item in enumerate(row['items'], 1):
        ident = item['id']
        obj = CATALOG[ident]
        w, h = obj['size']
        xx, yy = gx + item['x'] * cell, gy + item['y'] * cell
        color = '#edb465' if obj['type'] == 'consumable' else '#e099a5'
        if obj['type'] == 'weapon':
            color = '#f27059'
        draw.rounded_rectangle((xx + 3, yy + 3, xx + w * cell - 3, yy + h * cell - 3),
                               12, fill='#23344a', outline=color, width=3)
        box = (xx + 15, yy + 20, w * cell - 30, h * cell - 65)
        icon = asset(obj.get('imgGold') if obj['type'] == 'consumable' else obj['img'])
        paste(image, icon, box, .94)
        if icon is None and obj.get('kind') == 'ammo':
            # Never substitute a small-caliber icon for a large-caliber item.
            text(draw, (xx + w * cell / 2, yy + h * cell / 2 - 8), 'LARGE CALIBER', 22, '#edb465', True, 'mm')
        if obj['type'] == 'skill':
            paste(image, asset(obj.get('imgIcon')), box, .51)
        short = NAMES.get(ident, obj['name']).replace('Specialization', 'Spec.').replace('Gold1 ', '')
        if len(short) > 22:
            short = short[:21] + '…'
        label_size = 17
        while draw.textlength(short, font=font(label_size, True)) > w * cell - 15 and label_size > 11:
            label_size -= 1
        text(draw, (xx + w * cell / 2, yy + h * cell - 23), short, label_size, bold=True, anchor='mm')
        draw.ellipse((xx + 9, yy + 9, xx + 38, yy + 38), fill='#101822')
        text(draw, (xx + 24, yy + 23), str(index), 17, bold=True, anchor='mm')
    for index, item in enumerate(row['items']):
        col, line = index % 2, index // 2
        ident = item['id']
        name = NAMES.get(ident, CATALOG[ident]['name'])
        lx, ly = x + 40 + col * 550, y + 930 + line * 68
        text(draw, (lx, ly), f'{index + 1:02}. {name}', 21, bold=True)
        for n, part in enumerate(textwrap.wrap(effect_text(ident), width=55)):
            text(draw, (lx, ly + 27 + n * 19), part, 16, '#adc0d5')
    draw.line((x + 35, y + 1340, x + 1100, y + 1340), fill='#354d65', width=2)
    best = core_result['strongest_against_champion']
    net = -best['core_setup_net_hp_pp']
    outcome = 'WIN' if net > 1e-10 else ('LOSS' if net < -1e-10 else 'DRAW')
    text(draw, (x + 40, y + 1352), 'BEST FULL CAMOUFLAGE + SUIT + VIGILANCE OPPONENT', 21, '#edb465', True)
    text(draw, (x + 40, y + 1385), f"Vs #{best['setup']['candidate_id']}: {outcome} · Our net trade: {net:+.6f} pp", 25, '#90e3c0' if net >= 0 else '#ffaaa0', True)
    text(draw, (x + 40, y + 1423), f"We deal {best['champion_damage_hp_percent']:.4f}% HP / take {best['core_setup_damage_hp_percent']:.4f}% HP · {core_result['full_valid_core_setups_tested']} full setups tested", 20)
    text(draw, (x + 40, y + 1451), 'Weighted metrics use each opponent’s unweighted win rate. Self is excluded.', 18, '#adc0d5')
    text(draw, (x + 40, y + 1476), 'pp = percentage points. Weapon categories are tested separately; no full-duel odds.', 16, '#adc0d5')


def main():
    summaries = {kind: json.loads((ROOT / 'results' / f'{kind}_results.json').read_text())
                 for kind in ('submachine', 'rifle')}
    core = json.loads((ROOT / 'results' / 'full_defensive_core_vs_champions.json').read_text())['categories']
    grid = Image.new('RGB', (4760, 3360), '#0b1320')
    draw = ImageDraw.Draw(grid)
    text(draw, (40, 24), 'MAFIA REBORN · FOUR OBJECTIVES · SMG AND ASSAULT RIFLE', 44, bold=True)
    text(draw, (40, 86), 'Level 200 Rogue · 10,000 ATK / END · 50% base crit / 40% anti-crit · Epic1 gear / compatible Gold1 ammo · 92–96 cells · No Riot Shield', 26, '#adc0d5')
    text(draw, (40, 129), 'Opponent weight = its unweighted win rate. Weighted wins = sum of beaten-opponent weights / sum of all opponent weights; weighted trades use signed HP margins.', 25, '#adc0d5')
    text(draw, (40, 159), 'Every ammo variant is ranked against the entire field. A direct head-to-head is only one matchup.', 22, '#adc0d5')
    plans = [
        [('submachine', 'most_wins'), ('rifle', 'most_wins'),
         ('submachine', 'best_weighted_win_rate'), ('rifle', 'best_weighted_win_rate')],
        [('submachine', 'best_mean_trade'), ('rifle', 'best_mean_trade'),
         ('submachine', 'best_weighted_mean_trade'), ('rifle', 'best_weighted_mean_trade')],
    ]
    for r, cells in enumerate(plans):
        top = 190 + r * 1590
        text(draw, (40, top), 'UNWEIGHTED · HIGHEST WIN RATE' if r == 0 else 'UNWEIGHTED · BEST AVERAGE TRADE', 34, bold=True)
        text(draw, (2400, top), 'WEIGHTED · HIGHEST WIN RATE' if r == 0 else 'WEIGHTED · BEST AVERAGE TRADE', 34, bold=True)
        for col, (kind, key) in enumerate(cells):
            title = 'SMG · MP8' if kind == 'submachine' else 'ASSAULT RIFLE · AK 24/7'
            card(grid, 40 + 1180 * col, top + 60, summaries[kind], key, title, core[kind]['selections'][key])
    grid.save(ROOT / 'results' / 'loadout_comparison.png')
    write_report(summaries, core)


def write_report(summaries, core):
    lines = ['# Selected setups — two compatible Gold1 ammo families', '',
             'Scope: level 200 Rogue; 10,000 ATK / END; 50% base crit / 40% anti-crit.',
             'Epic1 gear; Gold1 Tracer or Soft-Nosed only; no ammo also allowed; no Riot Shield; 92–96 occupied cells.',
             'SMG and rifle opponents are separate. Every matchup uses both complete inventories.', '']
    for key, heading in [('most_wins', 'Highest trade win rate'), ('best_mean_trade', 'Best average trade'),
                         ('best_weighted_win_rate', 'Highest opponent-weighted win rate'),
                         ('best_weighted_mean_trade', 'Best opponent-weighted average trade')]:
        lines += [f'## {heading}', '']
        for kind in ('submachine', 'rifle'):
            summary = summaries[kind]
            row = summary[key]
            counter = core[kind]['selections'][key]
            best = counter['strongest_against_champion']
            lines += [f"### {kind}: setup #{row['candidate_id']}", '',
                      f"Win rate: {100 * row['wins'] / summary['opponents_per_setup']:.6f}%; "
                      f"{row['wins']} wins / {row['ties']} draws / {row['losses']} losses.",
                      f"Average net HP advantage per exchange: {row['mean_net_hp_pp']:+.6f} percentage points.", '',
                      f"Weighted win rate: {100 * row['weighted_win_rate']:.6f}%; "
                      f"weighted average net HP advantage: {row['weighted_mean_net_hp_pp']:+.6f} percentage points.", '',
                      '| Item | Effects |', '|---|---|']
            for item in row['items']:
                ident = item['id']
                lines.append(f"| {NAMES.get(ident, CATALOG[ident]['name'])} | {effect_text(ident)} |")
            lines += ['', '#### Strongest FULL Camouflage + Camouflage Suit + Vigilance opponent', '',
                      f"Tested {counter['full_valid_core_setups_tested']} valid complete setups; "
                      f"{counter['core_setups_beating_champion']} beat the selected setup.",
                      f"Strongest opponent: #{best['setup']['candidate_id']}, {best['setup']['area']}/96 cells.",
                      f"Selected setup deals {best['champion_damage_hp_percent']:.6f}% HP and takes "
                      f"{best['core_setup_damage_hp_percent']:.6f}% HP; selected setup net "
                      f"{-best['core_setup_net_hp_pp']:+.6f} percentage points.", '',
                      '| Opponent item | Effects |', '|---|---|']
            for item in best['setup']['items']:
                ident = item['id']
                lines.append(f"| {NAMES.get(ident, CATALOG[ident]['name'])} | {effect_text(ident)} |")
            lines.append('')
    (ROOT / 'results' / 'selected_setups_report.md').write_text('\n'.join(lines).rstrip() + '\n')


if __name__ == '__main__':
    main()
