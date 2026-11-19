import { allowed } from './model.js';
const $ = id => document.getElementById(id);
const canvas = (w,h) => { const c=document.createElement('canvas');c.width=w;c.height=h;return c; };
const framePixel = (r,g,b) => (r>110 && r>g*1.22 && r>b*1.05) || (r>130 && g>90 && r>b*1.35 && g>b*1.08) || (Math.min(r,g,b)>110 && Math.max(r,g,b)-Math.min(r,g,b)<35);
function frameMask(image) {
  const {data,width,height}=image,mask=new Uint8Array(width*height);
  for(let i=0;i<mask.length;i++)mask[i]=framePixel(data[i*4],data[i*4+1],data[i*4+2])?1:0;
  return mask;
}
function lineSegments(mask,w,h,vertical=false) {
  const result=[],outer=vertical?w:h,inner=vertical?h:w;
  for(let a=0;a<outer;a++) {
    let start=-1,last=-1;
    for(let b=0;b<=inner;b++) {
      const present=b<inner&&mask[vertical?b*w+a:a*w+b];
      if(present){if(start<0)start=b;last=b;}
      if(start>=0&&(!present&&b-last>2||b===inner)) {
        const length=last-start+1;
        if(length>=16&&length<inner*.9)result.push(vertical?{x:a,y:start,length,vertical:true}:{x:start,y:a,length,vertical:false});
        start=-1;
      }
    }
  }
  // Collapse border thickness, retaining long uninterrupted segments.
  const unique=new Map();
  for(const s of result){const key=[Math.round(s.x/3),Math.round(s.y/3),Math.round(s.length/4)].join('/');if(!unique.has(key)||unique.get(key).length<s.length)unique.set(key,s);}
  return [...unique.values()].sort((a,b)=>b.length-a.length).slice(0,400);
}

/** Suggestions only: physical 12x8 lattices inferred from colored item borders.
 * No item outside the user-confirmed crop is ever passed to recognition. */
export function findGridCandidates(source) {
  const scale=Math.min(1,1400/source.width,1100/source.height),c=canvas(Math.round(source.width*scale),Math.round(source.height*scale));
  c.getContext('2d').drawImage(source,0,0,c.width,c.height);
  const {width:w,height:h}=c,mask=frameMask(c.getContext('2d').getImageData(0,0,w,h));
  const segments=[...lineSegments(mask,w,h),...lineSegments(mask,w,h,true)];
  if(!segments.length)return [];
  const histogram=new Map();
  for(const s of segments)for(let cells=2;cells<=(s.vertical?4:5);cells++)for(const padding of [0,2,4]) {
    const size=(s.length+padding)/cells;
    if(size<12||size*12>w+4||size*8>h+4)continue;
    const key=Math.round(size*2)/2;histogram.set(key,(histogram.get(key)||0)+s.length);
  }
  const sizes=[...histogram].sort((a,b)=>b[1]-a[1]).slice(0,24).map(x=>x[0]),proposals=[];
  for(const size of sizes) {
    const votes=new Map();
    for(const s of segments) {
      const span=Math.round((s.length+3)/size);
      if(span<2||span>(s.vertical?4:5)||Math.abs(s.length+3-span*size)>Math.max(4,size*.12))continue;
      for(let i=0;i<=12-(s.vertical?0:span);i++)for(let j=0;j<=8-(s.vertical?span:0);j++) {
        const x=s.x-2-i*size,y=s.y-2-j*size;
        if(x< -4||y< -4||x+12*size>w+4||y+8*size>h+4)continue;
        const key=`${Math.round(x/4)},${Math.round(y/4)}`,p=votes.get(key)||{x:0,y:0,n:0,score:0};
        p.x+=x;p.y+=y;p.n++;p.score+=s.length;votes.set(key,p);
      }
    }
    for(const p of [...votes.values()].sort((a,b)=>b.score-a.score).slice(0,8)) {
      const x=p.x/p.n,y=p.y/p.n;
      proposals.push({x:Math.max(0,x)/scale,y:Math.max(0,y)/scale,w:12*size/scale,h:8*size/scale,score:p.score,alignment:p.n});
    }
  }
  // Prefer a tightly filled inventory with varied item rectangles over a
  // repetitive warehouse, while still asking the user to choose the region.
  const shortlist=proposals.sort((a,b)=>b.score-a.score).slice(0,60);
  const probe=canvas(360,240),probeContext=probe.getContext('2d',{willReadFrequently:true});
  for(const p of shortlist){
    probeContext.clearRect(0,0,360,240);probeContext.drawImage(source,p.x,p.y,p.w,p.h,0,0,360,240);
    const probeMask=frameMask(probeContext.getImageData(0,0,360,240)),covered=new Set(),shapes=new Set();let rectangles=0;
    for(const [rw,rh] of [[5,3],[3,4],[4,3],[4,4],[4,2],[3,3],[3,2],[2,3],[2,2]])for(let yy=0;yy<=8-rh;yy++)for(let xx=0;xx<=12-rw;xx++){
      const cells=[];for(let y=yy;y<yy+rh;y++)for(let x=xx;x<xx+rw;x++)cells.push(y*12+x);
      if(cells.some(cell=>covered.has(cell)))continue;
      if(rectangleFrame(probeMask,360,240,xx*30,yy*30,rw*30,rh*30,true)<.75)continue;
      cells.forEach(cell=>covered.add(cell));shapes.add(`${rw}/${rh}`);rectangles++;
    }
    p.score=(covered.size/96)**3*(.35+.65*Math.min(1,shapes.size/5))*(rectangles>=5?1:.5)+p.score/1e6;
  }
  const selected=[];
  for(const p of shortlist.sort((a,b)=>b.score-a.score)) {
    if(p.alignment<4)continue;
    if(selected.some(s=>Math.abs(s.x-p.x)<p.w*.12&&Math.abs(s.y-p.y)<p.h*.12&&Math.abs(s.w-p.w)<p.w*.18))continue;
    selected.push(p);if(selected.length===6)break;
  }
  return selected;
}

function descriptor(context,x,y,w,h) {
  const c=canvas(28,28),ctx=c.getContext('2d',{willReadFrequently:true});
  // Exclude all colored frames and the bottom caption; no rarity signal is used.
  ctx.drawImage(context.canvas,x+w*.07,y+h*.065,w*.86,h*.79,0,0,28,28);
  const data=ctx.getImageData(0,0,28,28).data,values=new Float32Array(28*28*3);
  const samples=[0,27,27*28,28*28-1,1,26,28,55];
  const background=[0,1,2].map(k=>samples.map(i=>data[i*4+k]).sort((a,b)=>a-b)[Math.floor(samples.length/2)]);
  let norm=0;
  for(let i=0;i<28*28;i++)for(let k=0;k<3;k++){const value=data[i*4+k]-background[k];values[i*3+k]=value;norm+=value*value;}
  return {values,norm:Math.sqrt(norm)};
}
function similarity(a,b) {if(a.norm<150||b.norm<150)return 0;let dot=0;for(let i=0;i<a.values.length;i++)dot+=a.values[i]*b.values[i];return Math.max(0,dot/(a.norm*b.norm));}
function fit(ctx,img,x,y,w,h,scale=1) {const r=Math.min(w/img.width,h/img.height)*scale;ctx.drawImage(img,x+(w-img.width*r)/2,y+(h-img.height*r)/2,img.width*r,img.height*r);}
export async function loadArt(item) {
  async function load(src){const img=new Image();img.src=src;await img.decode();return img;}
  return {base:await load(item.image),overlay:item.overlay?await load(item.overlay):null};
}
export function drawArt(ctx,art,x,y,w,h,mode='game',scale=1) {
  if(mode==='caption') {
    const box={x:x+w*.05,y:y+h*.04,w:w*.9,h:h*.76};fit(ctx,art.base,box.x,box.y,box.w,box.h,.94*scale);
    if(art.overlay)fit(ctx,art.overlay,box.x,box.y,box.w,box.h,.51*scale);
  } else {
    fit(ctx,art.base,x,y,w,h,.91*scale);
    if(art.overlay)fit(ctx,art.overlay,x,y,w,h,.50*scale);
  }
}
function rectangleFrame(mask,width,height,x,y,w,h,allSides=false) {
  const line=(x1,y1,x2,y2)=>{
    const length=Math.max(Math.abs(x2-x1),Math.abs(y2-y1)),n=Math.max(10,Math.floor(length/2));let hits=0;
    for(let i=0;i<=n;i++){const px=Math.round(x1+(x2-x1)*i/n),py=Math.round(y1+(y2-y1)*i/n);if(px>=0&&px<width&&py>=0&&py<height)hits+=mask[py*width+px];}
    return hits/(n+1);
  };
  // Search a narrow inner band to allow frame thickness, cell gaps and compression.
  const band=Math.max(2,Math.round(Math.min(w,h)*.035)),scores=[0,0,0,0];
  for(let d=0;d<=band+2;d++){
    scores[0]=Math.max(scores[0],line(x+band,y+d,x+w-band,y+d));
    scores[1]=Math.max(scores[1],line(x+band,y+h-1-d,x+w-band,y+h-1-d));
    scores[2]=Math.max(scores[2],line(x+d,y+band,x+d,y+h-band));
    scores[3]=Math.max(scores[3],line(x+w-1-d,y+band,x+w-1-d,y+h-band));
  }
  const selected=scores.sort((a,b)=>b-a).slice(0,allSides?4:3);
  return allSides ? Math.min(...selected) : selected.reduce((a,b)=>a+b,0)/selected.length;
}

export async function recognizeGrid(source,crop,itemList,tolerance=45) {
  const target=canvas(720,480),ctx=target.getContext('2d',{willReadFrequently:true});ctx.drawImage(source,crop.x,crop.y,crop.w,crop.h,0,0,720,480);
  const mask=frameMask(ctx.getImageData(0,0,720,480)),templates=[];
  for(const item of itemList) {
    const art=await loadArt(item),variants=[];
    for(const mode of ['game','caption'])for(const scale of [.8,1,1.13]){
      const c=canvas(item.width*60,item.height*60),cx=c.getContext('2d');cx.fillStyle='#23323d';cx.fillRect(0,0,c.width,c.height);drawArt(cx,art,0,0,c.width,c.height,mode,scale);variants.push(descriptor(cx,0,0,c.width,c.height));
    }
    templates.push({item,variants});
  }
  const shapes=[...new Set(itemList.map(i=>`${i.width}/${i.height}`))].map(s=>s.split('/').map(Number)),possible=[];
  const minimum=.82-tolerance*.0031;
  for(let y=0;y<8;y++)for(let x=0;x<12;x++)for(const [w,h] of shapes) {
    if(x+w>12||y+h>8)continue;
    const border=rectangleFrame(mask,720,480,x*60,y*60,w*60,h*60);
    if(border<.55)continue;
    const patch=descriptor(ctx,x*60,y*60,w*60,h*60);
    const options=templates.filter(t=>t.item.width===w&&t.item.height===h).map(t=>({id:t.item.id,score:Math.max(...t.variants.map(v=>similarity(patch,v)))})).sort((a,b)=>b.score-a.score);
    if(!options.length||options[0].score<minimum)continue;
    possible.push({x,y,w,h,options,score:options[0].score,border,uncertain:options[0].score<.82||(options.length>1&&options[0].score-options[1].score<.06)});
  }
  // Multiple adjacent borders can outline a larger rectangle. Artwork confidence
  // and frame support decide first; overlapping matches are never both accepted.
  const occupied=new Set(),matches=[];
  for(const p of possible.sort((a,b)=>(b.score+.07*b.border)-(a.score+.07*a.border))) {
    const cells=[];for(let yy=p.y;yy<p.y+p.h;yy++)for(let xx=p.x;xx<p.x+p.w;xx++)cells.push(yy*12+xx);
    if(cells.some(c=>occupied.has(c)))continue;
    cells.forEach(c=>occupied.add(c));matches.push(p);
  }
  return {matches:matches.sort((a,b)=>a.y-b.y||a.x-b.x),preview:target,filled:occupied.size};
}

export class ScreenshotImporter {
  constructor({items,category,onApply,onError}) {
    Object.assign(this,{items,category,onApply,onError});this.source=null;this.crop=null;this.candidates=[];this.matches=[];
    const safe=fn=>(...args)=>Promise.resolve().then(()=>fn(...args)).catch(onError);
    $('screenshot-open').onclick=()=>$('screenshot-dialog').showModal();$('screenshot-close').onclick=()=>$('screenshot-dialog').close();
    $('screenshot-file').onchange=safe(async e=>{await this.read(e.target.files[0]);e.target.value='';});
    $('paste-image').onclick=safe(async()=>{if(!navigator.clipboard?.read){$('screenshot-status').textContent='Use Ctrl/Cmd+V or Choose screenshot. This browser does not support the clipboard image button.';return;}try{for(const item of await navigator.clipboard.read())for(const type of item.types)if(type.startsWith('image/')){await this.read(await item.getType(type));return;}$('screenshot-status').textContent='No image on the clipboard. Copy a screenshot or choose a file.';}catch{$('screenshot-status').textContent='Clipboard access was unavailable. Use Ctrl/Cmd+V or Choose screenshot.';}});
    document.addEventListener('paste',safe(async e=>{if(!$('screenshot-dialog').open)return;for(const item of e.clipboardData?.items||[])if(item.type.startsWith('image/')){e.preventDefault();await this.read(item.getAsFile());return;}}));
    for(const field of ['x','y','w','h'])$('crop-'+field).onchange=()=>{this.crop=Object.fromEntries(['x','y','w','h'].map(k=>[k,Number($('crop-'+k).value)]));this.draw();};
    let start=null;const stage=$('screenshot-canvas');
    const point=e=>{const r=stage.getBoundingClientRect();return{x:(e.clientX-r.left)/r.width*this.source.width,y:(e.clientY-r.top)/r.height*this.source.height};};
    stage.onpointerdown=e=>{if(!this.source)return;start=point(e);stage.setPointerCapture(e.pointerId);};
    stage.onpointermove=e=>{if(!start)return;const p=point(e);this.setCrop({x:Math.min(p.x,start.x),y:Math.min(p.y,start.y),w:Math.abs(p.x-start.x),h:Math.abs(p.y-start.y)});};
    stage.onpointerup=e=>{if(!start)return;const p=point(e);if(Math.abs(p.x-start.x)<8&&Math.abs(p.y-start.y)<8){const candidate=this.candidates.find(c=>p.x>=c.x&&p.x<=c.x+c.w&&p.y>=c.y&&p.y<=c.y+c.h);if(candidate)this.setCrop(candidate);}start=null;};
    stage.onpointercancel=()=>{start=null;};
    $('recognize').onclick=safe(()=>this.recognize());$('confirm-tier').onchange=()=>{$('apply-recognition').disabled=!$('confirm-tier').checked||!this.matches.length;};
    $('apply-recognition').onclick=safe(()=>this.apply());
  }
  async read(blob) {
    if(!blob)return;if(!blob.type.startsWith('image/'))throw new Error('Choose an image file.');if(blob.size>25*1024*1024)throw new Error('Use an image smaller than 25 MB.');
    const bitmap=await createImageBitmap(blob);if(bitmap.width*bitmap.height>40e6){bitmap.close();throw new Error('Use a screenshot smaller than 40 megapixels.');}
    this.source?.close?.();this.source=bitmap;$('screenshot-status').textContent='Looking for equipped inventory regions…';$('recognition-review').hidden=true;$('crop-stage').hidden=false;
    await new Promise(r=>setTimeout(r,20));this.candidates=findGridCandidates(bitmap);
    this.crop=null;$('crop-candidates').replaceChildren();this.candidates.forEach((c,i)=>{const b=document.createElement('button');b.textContent=`Candidate ${i+1}`;b.onclick=()=>this.setCrop(c);$('crop-candidates').append(b);});
    if(this.candidates.length)this.setCrop(this.candidates[0]);else this.draw();
    $('screenshot-status').textContent=this.candidates.length?`Found ${this.candidates.length} possible regions. Select the enemy’s equipped inventory, not its warehouse, then confirm with Recognize selected grid.`:'No reliable grid found. Drag around the enemy’s equipped inventory, or set the crop coordinates.';
  }
  setCrop(crop){this.crop={x:Math.round(crop.x),y:Math.round(crop.y),w:Math.round(crop.w),h:Math.round(crop.h)};for(const k of ['x','y','w','h'])$('crop-'+k).value=this.crop[k];this.draw();}
  draw(){if(!this.source)return;const el=$('screenshot-canvas'),scale=Math.min(1,1200/this.source.width);el.width=Math.round(this.source.width*scale);el.height=Math.round(this.source.height*scale);const ctx=el.getContext('2d');ctx.drawImage(this.source,0,0,el.width,el.height);for(let i=0;i<this.candidates.length;i++){const c=this.candidates[i];ctx.strokeStyle='#f1b881';ctx.lineWidth=2;ctx.setLineDash([6,4]);ctx.strokeRect(c.x*scale,c.y*scale,c.w*scale,c.h*scale);ctx.fillStyle='#10171c';ctx.fillRect(c.x*scale,c.y*scale,95,22);ctx.fillStyle='#f1b881';ctx.font='14px sans-serif';ctx.fillText(`Candidate ${i+1}`,c.x*scale+5,c.y*scale+16);}if(this.crop){const c=this.crop;ctx.strokeStyle='#b3e38a';ctx.lineWidth=3;ctx.setLineDash([]);ctx.strokeRect(c.x*scale,c.y*scale,c.w*scale,c.h*scale);for(let x=1;x<12;x++){ctx.beginPath();ctx.moveTo((c.x+c.w*x/12)*scale,c.y*scale);ctx.lineTo((c.x+c.w*x/12)*scale,(c.y+c.h)*scale);ctx.strokeStyle='#b3e38a55';ctx.lineWidth=1;ctx.stroke();}for(let y=1;y<8;y++){ctx.beginPath();ctx.moveTo(c.x*scale,(c.y+c.h*y/8)*scale);ctx.lineTo((c.x+c.w)*scale,(c.y+c.h*y/8)*scale);ctx.stroke();}}}
  async recognize(){const c=this.crop;if(!c||c.w<60||c.h<40||c.x<0||c.y<0||c.x+c.w>this.source.width+1||c.y+c.h>this.source.height+1)throw new Error('Select a complete inventory region inside the screenshot.');if(Math.abs(c.w/c.h-1.5)>.13)throw new Error('The inventory must have a 12 × 8 grid (3:2 aspect ratio). Adjust the crop to the grid edges.');
    if(this.crop.x<0||this.crop.y<0||this.crop.w<120||this.crop.h<80||this.crop.x+this.crop.w>this.source.width+2||this.crop.y+this.crop.h>this.source.height+2)throw new Error('Keep the crop inside the screenshot and use at least 10 pixels per inventory cell.');
    $('recognize').disabled=true;$('screenshot-status').textContent='Comparing item artwork inside the confirmed crop…';$('recognition-review').hidden=true;await new Promise(r=>setTimeout(r,20));
    try{const list=[...this.items.values()].filter(i=>allowed(i,this.category()));const result=await recognizeGrid(this.source,c,list,Number($('tolerance').value));this.matches=result.matches;this.importCategory=this.category();$('recognition-items').replaceChildren();
      for(const p of result.matches){const row=document.createElement('div');row.className='recognition-row'+(p.uncertain?' uncertain':'');const thumb=canvas(p.w*30,p.h*30);thumb.getContext('2d').drawImage(result.preview,p.x*60,p.y*60,p.w*60,p.h*60,0,0,thumb.width,thumb.height);const box=document.createElement('div'),select=document.createElement('select');select.setAttribute('aria-label',`Item at column ${p.x+1}, row ${p.y+1}`);const omit=document.createElement('option');omit.value='';omit.textContent='Omit this match';select.append(omit);for(const item of list.filter(i=>i.width===p.w&&i.height===p.h)){const o=document.createElement('option');o.value=item.id;const score=p.options.find(x=>x.id===item.id)?.score;o.textContent=`${item.name}${score==null?'':` · similarity ${(100*score).toFixed(0)}/100`}`;select.append(o);}select.value=p.options[0].id;p.selection=select;const label=document.createElement('small');label.textContent=`Cell ${p.x+1}, ${p.y+1} · ${p.uncertain?'Review carefully':'Strong artwork match'} · similarity is not a calibrated probability`;box.append(select,label);row.append(thumb,box);$('recognition-items').append(row);}
      $('recognition-review').hidden=false;$('confirm-tier').checked=false;$('apply-recognition').disabled=true;$('screenshot-status').textContent=`Recognized ${result.matches.length} possible items across ${result.filled}/96 cells. Review identities and the gear-tier assumption before applying. Missing items can be added manually.`;
    }finally{$('recognize').disabled=false;}
  }
  apply(){if(!$('confirm-tier').checked)throw new Error('Confirm the current experiment’s gear values.');if(this.category()!==this.importCategory)throw new Error('Weapon category changed. Recognize the crop again.');const layout=[],seen=new Set();for(const p of this.matches){const id=p.selection.value;if(!id)continue;if(seen.has(id))throw new Error(`Duplicate ${this.items.get(id).name}: correct or omit one of the matches.`);seen.add(id);layout.push({id,x:p.x,y:p.y});}if(!layout.length)throw new Error('Select at least one recognized item.');this.onApply(layout);$('screenshot-dialog').close();}
}
