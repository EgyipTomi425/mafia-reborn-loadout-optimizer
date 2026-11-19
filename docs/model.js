import { parquetReadObjects } from './vendor/hyparquet/src/index.js';

export const EPSILON = 1e-10;
export const signature = items => items.map(x => typeof x === 'string' ? x : x.id).sort().join('|');
export const percent = x => `${(100 * x).toFixed(4)}%`;
export const margin = x => `${x >= 0 ? '+' : ''}${x.toFixed(6)} pp`;

export function allowed(item, category) {
  if (item.type === 'weapon') return item.id === (category === 'rifle' ? 'ak_24_7' : 'mp8');
  if (item.kind === 'ammo') return item.id.endsWith(category === 'rifle' ? '_large' : '_small');
  if (item.id.startsWith('accuracy_') || item.id.startsWith('specialization_')) {
    return item.id.endsWith(category) || item.id === 'accuracy_all';
  }
  return true;
}

export function validate(layout, items, category, minimum = true) {
  const occupied = new Set(), seen = new Set(), errors = [];
  let area = 0, weapons = 0, ammo = 0;
  for (const p of layout) {
    const item = items.get(p.id);
    if (!item) { errors.push(`Unknown item: ${p.id}`); continue; }
    if (seen.has(p.id)) errors.push(`Duplicate ${item.name}.`);
    seen.add(p.id);
    if (!allowed(item, category)) errors.push(`${item.name} is incompatible with this weapon category.`);
    weapons += item.type === 'weapon'; ammo += item.kind === 'ammo';
    if (!Number.isInteger(p.x) || !Number.isInteger(p.y) || p.x < 0 || p.y < 0 || p.x + item.width > 12 || p.y + item.height > 8) {
      errors.push(`${item.name} is outside the inventory.`); continue;
    }
    for (let y = p.y; y < p.y + item.height; y++) for (let x = p.x; x < p.x + item.width; x++) {
      const cell = y * 12 + x;
      if (occupied.has(cell)) errors.push('Items overlap.');
      occupied.add(cell);
    }
    area += item.width * item.height;
  }
  if (weapons !== 1) errors.push('Use exactly one supported weapon.');
  if (ammo > 1) errors.push('Use at most one compatible ammo item.');
  if (minimum && area < 92) errors.push(`Fill at least 92 cells (${92 - area} more needed).`);
  if (area > 96) errors.push('Inventory exceeds 96 cells.');
  return { area, errors: [...new Set(errors)], valid: !errors.length };
}

export function expectedShot(a, b, hp) {
  const hit = Math.max(0, Math.min(1, a.accuracy - b.camouflage));
  const land = hit * (1 - b.dodge);
  return { hit, land, hpPercent: 100 * land * (b.vest ? a.landed_vest : a.landed_no_vest) / hp };
}

export class Database {
  constructor(manifest, base = './data/') {
    this.manifest = manifest; this.base = base; this.categories = new Map(); this.files = new Map(); this.rows = new Map();
  }
  async read(file, options = {}) {
    if (!this.files.has(file)) {
      const promise = fetch(this.base + file).then(async r => {
        if (!r.ok) throw new Error(`Cannot load ${file} (HTTP ${r.status}).`);
        return r.arrayBuffer();
      }).catch(e => { this.files.delete(file); throw e; });
      this.files.set(file, promise);
      if (this.files.size > 12) this.files.delete(this.files.keys().next().value);
    }
    return parquetReadObjects({ file: await this.files.get(file), ...options });
  }
  async category(kind) {
    if (!this.categories.has(kind)) this.categories.set(kind, (async () => {
      const entries = await this.read(this.manifest.categories[kind].loadouts);
      for (const row of entries) {
        for (const [k, v] of Object.entries(row)) if (typeof v === 'bigint') row[k] = Number(v);
        row.layout = row.item_ids.map((id, i) => ({ id, x: Number(row.xs[i]), y: Number(row.ys[i]) }));
      }
      return { entries, byId: new Map(entries.map(x => [x.candidate_id, x])), byItems: new Map(entries.map(x => [signature(x.item_ids), x])) };
    })().catch(e => { this.categories.delete(kind); throw e; }));
    return this.categories.get(kind);
  }
  async matrixRow(kind, index) {
    const key = `${kind}/${index}`;
    if (!this.rows.has(key)) this.rows.set(key, (async () => {
      const category = await this.category(kind);
      const setup = category.entries[index];
      if (!setup) throw new Error('Matrix index outside this category.');
      const file = this.manifest.categories[kind].matrix_directory + String(Math.floor(index / 100)).padStart(3, '0') + '/' + setup.candidate_id + '.parquet';
      const [row] = await this.read(file);
      if (Number(row.row_index) !== index) throw new Error('Matrix row identifier mismatch.');
      if (row.net_hp_pp.length !== this.manifest.categories[kind].count) throw new Error('Matrix row length mismatch.');
      return row.net_hp_pp;
    })().catch(e => { this.rows.delete(key); throw e; }));
    const promise = this.rows.get(key);
    if (this.rows.size > 32) this.rows.delete(this.rows.keys().next().value);
    return promise;
  }
}
