/** Independently decode every published Parquet row with the actual JS reader. */
import assert from 'node:assert/strict';
import { readFile, readdir, stat } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { parquetReadObjects } from '../docs/vendor/hyparquet/src/index.js';
import { allowed, validate, signature, expectedShot, EPSILON, Database } from '../docs/model.js';
const root=fileURLToPath(new URL('../',import.meta.url)),data=path.join(root,'docs/data');
const manifest=JSON.parse(await readFile(path.join(data,'manifest.json'),'utf8')),items=new Map(manifest.items.map(i=>[i.id,i]));
async function read(file){const b=await readFile(path.join(data,file));return parquetReadObjects({file:b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength)});}
const aliases=JSON.parse(await readFile(path.join(data,'recognition-aliases.json'),'utf8'));
for(const a of aliases){const target=items.get(a.target);assert(target);assert.equal(a.width,target.width);assert.equal(a.height,target.height);assert(!a.id.startsWith('full_metal'));}
assert.equal(aliases.find(a=>a.id==='soft_nosed_bullet_shotgun').target,'soft_nosed_bullet_large');
assert.equal(aliases.find(a=>a.id==='tracer_ammunition_shotgun').target,'tracer_ammunition_large');
let count=0,entriesCount=0,maxFile=0;
for(const [kind,config] of Object.entries(manifest.categories)){
 const rows=await read(config.loadouts);for(const row of rows)for(const [k,v]of Object.entries(row))if(typeof v==='bigint')row[k]=Number(v);
 assert.equal(rows.length,config.count);assert.equal(new Set(rows.map(r=>signature(r.item_ids))).size,rows.length);
 const weights=rows.map(r=>r.wins),weightSum=weights.reduce((a,b)=>a+b,0);const ids=new Set();
 for(let i=0;i<rows.length;i++){
  const s=rows[i];assert.equal(s.row_index,i);assert(!ids.has(s.candidate_id));ids.add(s.candidate_id);
  const layout=s.item_ids.map((id,k)=>({id,x:Number(s.xs[k]),y:Number(s.ys[k])}));assert(validate(layout,items,kind).valid);
  assert.equal(signature(layout),signature([...layout].reverse()));
  const file=config.matrix_directory+String(Math.floor(i/100)).padStart(3,'0')+'/'+s.candidate_id+'.parquet';
  const [r]=await read(file);assert.equal(r.row_index,i);assert.equal(r.candidate_id,s.candidate_id);assert.equal(r.net_hp_pp.length,rows.length);
  const vector=r.net_hp_pp;let wins=0,losses=0,mean=0,weighted=0,weightedWins=0;
  for(let j=0;j<vector.length;j++){const x=vector[j];assert(Number.isFinite(x));if(j===i){assert(Math.abs(x)<EPSILON);continue;}wins+=x>EPSILON;losses+=x< -EPSILON;mean+=x;weighted+=x*weights[j];if(x>EPSILON)weightedWins+=weights[j];}
  assert.equal(wins,s.wins);assert.equal(losses,s.losses);assert.equal(rows.length-1-wins-losses,s.ties);
  assert(Math.abs(mean/(rows.length-1)-s.mean_net_hp_pp)<1e-10);
  const den=weightSum-weights[i];assert(Math.abs((den?weighted/den:mean/(rows.length-1))-s.weighted_mean_net_hp_pp)<1e-10);
  assert(Math.abs((den?weightedWins/den:wins/(rows.length-1))-s.weighted_win_rate)<1e-12);
  // Cross-check JS shot decomposition with the persisted matrix, including sign.
  for(const j of [0,Math.floor(rows.length/2),rows.length-1]){
   const out=expectedShot(s,rows[j],config.hp).hpPercent,inc=expectedShot(rows[j],s,config.hp).hpPercent;
   assert(Math.abs(out-inc-vector[j])<1e-10);
  }
  count++;entriesCount+=vector.length;maxFile=Math.max(maxFile,(await stat(path.join(data,file))).size);
 }
 const globalWins=rows.reduce((a,b)=>b.wins>a.wins||b.wins===a.wins&&b.mean_net_hp_pp>a.mean_net_hp_pp?b:a);
 const globalMean=rows.reduce((a,b)=>b.mean_net_hp_pp>a.mean_net_hp_pp?b:a);
 assert.equal(globalWins.candidate_id,config.winners.most_wins);assert.equal(globalMean.candidate_id,config.winners.best_mean_trade);
 console.log(`${kind}: every JS-decoded matrix row, score, placement, and ordinary winner verified`);
}
assert(!allowed(items.get('soft_nosed_bullet_small'),'rifle'));assert(!allowed(items.get('soft_nosed_bullet_large'),'submachine'));
assert(!validate([{id:'mp8',x:0,y:0}],items,'submachine').valid);
assert(!validate([{id:'mp8',x:0,y:0},{id:'mp8',x:0,y:0}],items,'submachine').valid);
assert(!validate([{id:'mp8',x:11,y:7}],items,'submachine').valid);
// A normal enemy lookup must request exactly its catalogue and its own slice.
const requests=[];globalThis.fetch=async url=>{requests.push(url);try{return new Response(await readFile(path.join(data,String(url).replace(/^data\//,''))));}catch{return new Response('',{status:404});}};
const db=new Database(manifest,'data/');const category=await db.category('rifle');const target=category.byId.get(manifest.categories.rifle.winners.most_wins);
const row=await db.matrixRow('rifle',target.row_index);assert.equal(row.length,manifest.categories.rifle.count);assert.equal(requests.length,2);
await db.matrixRow('rifle',target.row_index);assert.equal(requests.length,2,'Repeat lookup must be cached');
console.log(JSON.stringify({parquet_files_checked:count,matrix_entries_checked:entriesCount,max_matchup_file_bytes:maxFile,requests_per_enemy_lookup:1},null,2));
