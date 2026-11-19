import { Database, allowed, validate, signature, expectedShot, percent, margin, EPSILON } from './model.js';
import { ScreenshotImporter } from './screenshot.js';

const $ = id => document.getElementById(id);
const state = { category: 'submachine', layout: [], selected: null, data: null, enemy: null, page: 0, rows: [], sequence: 0 };
let db, manifest, items, importer, toastTimer;
function toast(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').hidden = true, 5000); }
function failure(error) { console.error(error); toast(error.message || String(error)); }
function safe(fn) { return (...args) => Promise.resolve().then(() => fn(...args)).catch(failure); }
function art(item) {
  const box = document.createElement('span'); box.className = 'palette-art';
  const img = document.createElement('img'); img.className = 'art-image'; img.src = item.image; img.alt = ''; img.draggable = false; box.append(img);
  if (item.overlay) { const overlay = img.cloneNode(); overlay.src = item.overlay; overlay.className = 'art-overlay'; box.append(overlay); }
  return box;
}
function renderPalette() {
  const query = $('item-search').value.trim().toLowerCase(); $('palette').replaceChildren();
  for (const item of items.values()) {
    if (!allowed(item, state.category) || !item.name.toLowerCase().includes(query)) continue;
    const button = document.createElement('button'); button.className = 'palette-item'; button.dataset.id = item.id;
    button.title = `${item.name}: ${item.effects}`; button.draggable = true; button.setAttribute('aria-pressed', state.selected === item.id);
    button.classList.toggle('selected', state.selected === item.id); button.disabled = state.layout.some(p => p.id === item.id);
    const label = document.createElement('span'), name = document.createElement('strong'), size = document.createElement('small');
    name.textContent = item.name; size.textContent = `${item.width} × ${item.height} · ${item.tier === 'gold1' ? 'Gold1' : 'Epic1'}`; label.append(name, size); button.append(art(item), label);
    button.onclick = () => { state.selected = state.selected === item.id ? null : item.id; renderPalette(); if (state.selected) toast(`Place ${item.name}: tap a cell, or focus the grid and use arrow keys + Enter.`); };
    button.ondragstart = e => { state.selected = item.id; e.dataTransfer.setData('text/plain', JSON.stringify({ id: item.id, dx: 0, dy: 0 })); e.dataTransfer.effectAllowed = 'copy'; };
    $('palette').append(button);
  }
}
function renderBoard(element, layout, editable = false) {
  element.replaceChildren();
  for (const p of layout) {
    const item = items.get(p.id), tile = document.createElement('div'); tile.className = 'inventory-item'; tile.dataset.id = p.id;
    if (item.type === 'weapon') tile.classList.add('weapon'); if (item.kind === 'ammo') tile.classList.add('ammo');
    tile.style.gridArea = `${p.y + 1} / ${p.x + 1} / span ${item.height} / span ${item.width}`;
    tile.title = `${item.name} · ${item.effects}`; tile.setAttribute('aria-label', `${item.name}, column ${p.x + 1}, row ${p.y + 1}. ${item.effects}`);
    const icons = art(item); tile.append(...icons.childNodes);
    const label = document.createElement('span'); label.className = 'item-label'; label.textContent = item.name.replace('Gold1 ', '').replace('Specialization', 'Spec.'); tile.append(label);
    if (editable) {
      tile.draggable = true; tile.tabIndex = 0;
      tile.ondragstart = e => {
        const r = tile.getBoundingClientRect(), b = element.getBoundingClientRect();
        e.dataTransfer.setData('text/plain', JSON.stringify({ id: p.id, dx: Math.max(0, Math.floor((e.clientX-r.left)/(b.width/12))), dy: Math.max(0, Math.floor((e.clientY-r.top)/(b.height/8))) }));
        e.dataTransfer.effectAllowed = 'move';
      };
      const remove = document.createElement('button'); remove.className = 'remove-item'; remove.textContent = '×'; remove.title = `Remove ${item.name}`;
      remove.setAttribute('aria-label', `Remove ${item.name}`); remove.onclick = e => { e.stopPropagation(); state.layout = state.layout.filter(x => x.id !== p.id); changed(); }; tile.append(remove);
      tile.onkeydown = e => { if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); state.layout = state.layout.filter(x => x.id !== p.id); changed(); } };
      tile.onclick = e => { if (!state.selected) { e.stopPropagation(); toast(`${item.name}: ${item.effects}`); } };
    }
    element.append(tile);
  }
}
function changed() {
  state.sequence++; state.enemy = null; $('results').hidden = true;
  renderBoard($('inventory'), state.layout, true); renderPalette();
  const result = validate(state.layout, items, state.category), found = state.data?.byItems.get(signature(state.layout));
  $('area').textContent = `${result.area} / 96 CELLS`;
  $('validation').textContent = result.errors[0] || (found ? `Verified item set · Setup #${found.candidate_id}` : 'This item set is not in the current experiment.');
  $('validation').classList.toggle('valid', result.valid && !!found); $('evaluate').disabled = !result.valid || !found;
}
function place(id, x, y) {
  if (!items.has(id)) return;
  const candidate = state.layout.filter(p => p.id !== id).concat({ id, x, y });
  const errors = validate(candidate, items, state.category, false).errors.filter(x => !x.startsWith('Use exactly one'));
  if (errors.length) { toast(errors[0]); return; }
  state.layout = candidate; state.selected = null; changed();
}
async function categoryChanged() {
  const category = $('category').value; state.category = category; state.layout = []; state.data = null; state.selected = null; changed();
  $('load-status').textContent = 'Reading verified Parquet loadouts…'; $('load-winner').disabled = $('load-average').disabled = true;
  const data = await db.category(category);
  if (state.category !== category) return;
  state.data = data; $('load-winner').disabled = $('load-average').disabled = false;
  $('load-status').textContent = `${data.entries.length.toLocaleString()} verified ${category === 'rifle' ? 'AK' : 'SMG'} loadouts · Every same-category pairing · Exact item-set lookup`;
  changed();
}
function loadWinner(key) {
  if (!state.data) return;
  const row = state.data.byId.get(manifest.categories[state.category].winners[key]);
  state.layout = structuredClone(row.layout); state.selected = null; changed();
}
function summaryCard(label, value, note) {
  const div = document.createElement('div'); div.className = 'summary-card';
  const small = document.createElement('small'), strong = document.createElement('strong'), p = document.createElement('p');
  small.textContent = label; strong.textContent = value; p.textContent = note; div.append(small,strong,p); return div;
}
async function evaluate() {
  const validation = validate(state.layout, items, state.category);
  if (!validation.valid) throw new Error(validation.errors[0]);
  const enemy = state.data.byItems.get(signature(state.layout));
  if (!enemy) throw new Error('This item set is outside the measured experiment.');
  const sequence = state.sequence; $('evaluate').disabled = true; $('evaluate').textContent = 'Reading matchups…';
  try {
    const row = await db.matrixRow(state.category, enemy.row_index);
    if (sequence !== state.sequence) return;
    state.enemy = enemy; state.rows = state.data.entries.filter(s => s !== enemy).map(s => ({ setup: s, net: -row[s.row_index] }));
    $('results').hidden = false; $('setup-detail').hidden = true; $('matrix-container').replaceChildren(); $('matrix-status').textContent = '';
    $('enemy-summary').textContent = `Enemy #${enemy.candidate_id} · ${enemy.area}/96 cells · ${state.rows.length.toLocaleString()} opponents`;
    const beats = state.rows.filter(r => r.net > EPSILON).length, best = Math.max(...state.rows.map(r => r.net));
    $('result-summary').replaceChildren(summaryCard('SETUPS THAT BEAT THIS ENEMY', beats.toLocaleString(), `${state.rows.filter(r => Math.abs(r.net) <= EPSILON).length} expected-trade draws`), summaryCard('STRONGEST COUNTER MARGIN', margin(best), 'Net HP advantage per exchange'), summaryCard('ENEMY GLOBAL WIN RATE', percent(enemy.win_rate), `Weighted: ${percent(enemy.weighted_win_rate)}`), summaryCard('ENEMY AVERAGE TRADE', margin(enemy.mean_net_hp_pp), `Weighted: ${margin(enemy.weighted_mean_net_hp_pp)}`));
    state.page = 0; renderTable();
    $('results').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } finally { $('evaluate').textContent = 'Find counters'; $('evaluate').disabled = !validate(state.layout, items, state.category).valid || !state.data?.byItems.has(signature(state.layout)); }
}
function filteredRows() {
  let rows = state.rows;
  if ($('core-only').checked) rows = rows.filter(r => ['camouflage','camouflage_suit','vigilance'].every(x => r.setup.item_ids.includes(x)));
  const key = $('sort').value;
  return [...rows].sort((a,b) => (key === 'matchup' ? b.net-a.net : b.setup[key]-a.setup[key]) || b.net-a.net || a.setup.candidate_id-b.setup.candidate_id);
}
function renderTable() {
  const rows = filteredRows(), start = state.page*20; $('counter-rows').replaceChildren();
  for (const r of rows.slice(start,start+20)) {
    const tr = document.createElement('tr'), id = document.createElement('td'), button = document.createElement('button'); button.textContent = `#${r.setup.candidate_id}`; button.onclick = safe(() => detail(r)); id.append(button); tr.append(id);
    const values = [r.net>EPSILON ? 'WIN' : r.net < -EPSILON ? 'LOSS' : 'DRAW', margin(r.net), percent(r.setup.win_rate), margin(r.setup.mean_net_hp_pp), percent(r.setup.weighted_win_rate), margin(r.setup.weighted_mean_net_hp_pp)];
    values.forEach((value,i) => { const td = document.createElement('td'); td.textContent = value; if (i<2) td.className = r.net>EPSILON ? 'positive' : r.net < -EPSILON ? 'negative' : 'neutral'; tr.append(td); });
    $('counter-rows').append(tr);
  }
  $('page-info').textContent = rows.length ? `${start+1}–${Math.min(start+20,rows.length)} of ${rows.length.toLocaleString()}` : 'No matching setups';
  $('previous').disabled = state.page === 0; $('next').disabled = start+20 >= rows.length;
  $('matrix-container').replaceChildren(); $('matrix-status').textContent = '';
}
function detail(r) {
  const setup = r.setup, enemy = state.enemy; if (!enemy) return;
  const out = expectedShot(setup,enemy,manifest.categories[state.category].hp), inc = expectedShot(enemy,setup,manifest.categories[state.category].hp);
  const panel = $('setup-detail'); panel.replaceChildren(); panel.hidden = false;
  const h = document.createElement('h3'); h.textContent = `Setup #${setup.candidate_id} · ${margin(r.net)} vs enemy #${enemy.candidate_id}`;
  const metrics = document.createElement('div'); metrics.className = 'detail-metrics';
  for (const [label,value] of [['We deal',`${out.hpPercent.toFixed(6)}% enemy HP`],['We take',`${inc.hpPercent.toFixed(6)}% own HP`],['Our landed hit chance',percent(out.land)],['Enemy landed hit chance',percent(inc.land)]]) {
    const p = document.createElement('p'),strong = document.createElement('strong');p.textContent=label;strong.textContent=value;p.append(strong);metrics.append(p);
  }
  const grid = document.createElement('div'); grid.className='detail-grid'; const board = document.createElement('div'); board.className='inventory';renderBoard(board,setup.layout);
  const list = document.createElement('ul'); for(const id of setup.item_ids){const li=document.createElement('li'),effect=document.createElement('span');li.textContent=items.get(id).name;effect.textContent=items.get(id).effects;li.append(effect);list.append(li);}grid.append(board,list);
  const button = document.createElement('button');button.textContent='Use this setup as enemy';button.onclick=()=>{state.layout=structuredClone(setup.layout);changed();$('inventory').scrollIntoView({behavior:'smooth',block:'center'});};
  panel.append(h,metrics,grid,button);panel.scrollIntoView({behavior:'smooth',block:'start'});
}
async function matrix() {
  if(!state.enemy)return; const sequence=state.sequence,enemy=state.enemy;
  const entries=filteredRows().slice(0,10).map(r=>r.setup);entries.push(enemy);
  $('show-matrix').disabled=true; $('matrix-status').textContent='Loading only the selected matchup slices…';
  try {
    const vectors=await Promise.all(entries.map(s=>db.matrixRow(state.category,s.row_index)));if(sequence!==state.sequence)return;
    const table=document.createElement('table');table.className='heatmap';const head=document.createElement('thead'),hr=document.createElement('tr');
    const corner=document.createElement('th');corner.textContent='ROW vs COLUMN';hr.append(corner);
    for(const s of entries){const th=document.createElement('th');th.textContent=`#${s.candidate_id}${s===enemy?' (enemy)':''}`;if(s===enemy)th.className='enemy';hr.append(th);}head.append(hr);table.append(head);
    const body=document.createElement('tbody');entries.forEach((s,i)=>{const tr=document.createElement('tr'),th=document.createElement('th');th.textContent=`#${s.candidate_id}`;tr.append(th);for(const opponent of entries){const value=vectors[i][opponent.row_index],td=document.createElement('td'),b=document.createElement('button');b.textContent=value.toFixed(3);b.className=value>EPSILON?'positive':value< -EPSILON?'negative':'neutral';b.title=`#${s.candidate_id} vs #${opponent.candidate_id}: ${margin(value)}`;b.onclick=()=>{$('matrix-status').textContent=b.title;};td.append(b);tr.append(td);}body.append(tr);});table.append(body);$('matrix-container').replaceChildren(table);$('matrix-status').textContent='Values are HP percentage points. The diagonal is zero; each opposite pair has equal and opposite margins.';
  }finally{$('show-matrix').disabled=false;}
}
function saveLayout(){const blob=new Blob([JSON.stringify({schema_version:1,category:state.category,scenario:manifest.scenario,items:state.layout},null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`mafia-reborn-${state.category}-inventory.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
async function openLayout(file){if(!file)return;if(file.size>25000)throw new Error('Inventory file is too large.');const data=JSON.parse(await file.text());if(data.schema_version!==1||!['rifle','submachine'].includes(data.category)||!Array.isArray(data.items)||data.items.length>25)throw new Error('Not a supported saved inventory.');const result=validate(data.items,items,data.category,false);if(result.errors.length)throw new Error(result.errors[0]);if(state.category!==data.category){$('category').value=data.category;await categoryChanged();}state.layout=data.items.map(p=>({id:p.id,x:p.x,y:p.y}));changed();}
async function main(){
  const response=await fetch('data/manifest.json');if(!response.ok)throw new Error('Cannot read the experiment manifest.');manifest=await response.json();items=new Map(manifest.items.map(i=>[i.id,i]));db=new Database(manifest);
  $('inventory').style.gridTemplateColumns='repeat(12,minmax(0,1fr))';$('inventory').style.gridTemplateRows='repeat(8,minmax(0,1fr))';$('inventory').tabIndex=0;
  document.querySelectorAll('.axis-x').forEach(el=>{el.style.display='grid';el.style.gridTemplateColumns='repeat(12,1fr)';el.style.textAlign='center';el.style.fontSize='.75rem';el.style.color='var(--muted)';el.style.marginBottom='8px';for(let i=1;i<=12;i++){const span=document.createElement('span');span.textContent=i;el.append(span);}});
  const point=e=>{const r=$('inventory').getBoundingClientRect();return{x:Math.min(11,Math.floor((e.clientX-r.left)/r.width*12)),y:Math.min(7,Math.floor((e.clientY-r.top)/r.height*8))};};
  $('inventory').ondragover=e=>{e.preventDefault();e.dataTransfer.dropEffect=e.dataTransfer.effectAllowed==='copy'?'copy':'move';};
  $('inventory').ondrop=e=>{e.preventDefault();try{const data=JSON.parse(e.dataTransfer.getData('text/plain')),p=point(e);place(data.id,p.x-(data.dx||0),p.y-(data.dy||0));}catch{toast('Drag an item from the library or this inventory.');}};
  $('inventory').onclick=e=>{if(state.selected){const p=point(e);place(state.selected,p.x,p.y);}};
  let keyboard={x:0,y:0};$('inventory').onkeydown=e=>{if(e.target!==$('inventory'))return;const keys={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]};if(keys[e.key]){e.preventDefault();keyboard.x=Math.max(0,Math.min(11,keyboard.x+keys[e.key][0]));keyboard.y=Math.max(0,Math.min(7,keyboard.y+keys[e.key][1]));toast(`Grid column ${keyboard.x+1}, row ${keyboard.y+1}. Press Enter to place the selected item.`);}else if(e.key==='Enter'&&state.selected){e.preventDefault();place(state.selected,keyboard.x,keyboard.y);}};
  $('category').onchange=safe(categoryChanged);$('item-search').oninput=renderPalette;$('clear').onclick=()=>{state.layout=[];state.selected=null;changed();};
  $('load-winner').onclick=()=>loadWinner('most_wins');$('load-average').onclick=()=>loadWinner('best_mean_trade');$('evaluate').onclick=safe(evaluate);
  $('sort').onchange=$('core-only').onchange=()=>{state.page=0;renderTable();};$('previous').onclick=()=>{state.page--;renderTable();};$('next').onclick=()=>{state.page++;renderTable();};$('show-matrix').onclick=safe(matrix);
  $('export-layout').onclick=saveLayout;$('layout-file').onchange=safe(async e=>{await openLayout(e.target.files[0]);e.target.value='';});
  importer=new ScreenshotImporter({items,category:()=>state.category,onApply:layout=>{state.layout=layout;state.selected=null;changed();toast('Reviewed items imported. Check the inventory and fill any missing cells.');},onError:failure});
  $('data-links').textContent = 'A compact loadout catalogue loads once per category. Each enemy lookup fetches only its own small Parquet matchup slice; the complete matrix is never downloaded. GitHub Pages serves these precomputed slices directly, with no backend.';
  await categoryChanged();loadWinner('most_wins');
}
main().catch(error=>{$('load-status').textContent=`Could not load the experiment: ${error.message}. Reload to retry.`;failure(error);});
