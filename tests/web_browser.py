"""Real Chromium integration checks. All fixtures and outputs stay in .web-test/.

Requires playwright==1.56.0 and its Chromium browser. No game account or upload
service is used. The exported fixture uses real local game artwork, synthetic
screen layout, mixed rarity frames, and an intentionally separate warehouse.
"""
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import json
import os
from pathlib import Path
import threading

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / '.web-test'

FIXTURE = r'''async ({setup,category,mode='game',jpeg=false,cell=50})=>{
  const {findGridCandidates,recognizeGrid,loadArt,drawArt}=await import('./screenshot.js');
  const {allowed}=await import('./model.js');
  const manifest=await(await fetch('data/manifest.json')).json();
  const aliases=await(await fetch('data/recognition-aliases.json')).json();
  const items=new Map([...manifest.items,...aliases].map(x=>[x.id,x]));
  const c=document.createElement('canvas');c.width=1600;c.height=1100;
  const ctx=c.getContext('2d');ctx.fillStyle='#111820';ctx.fillRect(0,0,c.width,c.height);
  const crop={x:120,y:180,w:12*cell,h:8*cell};ctx.fillStyle='#0d151a';ctx.fillRect(crop.x,crop.y,crop.w,crop.h);
  ctx.fillStyle='#fff';ctx.font='24px sans-serif';ctx.fillText('OPPONENT EQUIPPED INVENTORY',120,155);ctx.fillText('WAREHOUSE',900,155);
  for(let i=0;i<setup.items.length;i++){
    const p=setup.items[i],item=items.get(setup.art_ids?.[p.id]||p.id),x=crop.x+p.x*cell,y=crop.y+p.y*cell,w=item.width*cell,h=item.height*cell;
    ctx.fillStyle='#23323d';ctx.fillRect(x+2,y+2,w-4,h-4);
    ctx.strokeStyle=['#ff5260','#e8b561','#bbbbbb'][i%3];ctx.lineWidth=3;ctx.strokeRect(x+3,y+3,w-6,h-6);
    drawArt(ctx,await loadArt(item),x,y,w,h,mode,1);
    if(mode==='caption'){ctx.fillStyle='#e8eeee';ctx.font='12px sans-serif';ctx.fillText(item.name,x+7,y+h-7);}
  }
  const warehouseItem=items.get('accuracy_all');
  for(let y=0;y<8;y+=4)for(let x=0;x<12;x+=4){
    const px=900+x*50,py=180+y*50;ctx.fillStyle='#23323d';ctx.fillRect(px+2,py+2,196,196);ctx.strokeStyle='#edb465';ctx.strokeRect(px+3,py+3,194,194);drawArt(ctx,await loadArt(warehouseItem),px,py,200,200);
  }
  const blob=await new Promise(r=>c.toBlob(r,jpeg?'image/jpeg':'image/png',.78));
  const image=await createImageBitmap(blob),candidates=findGridCandidates(image);
  const match=await recognizeGrid(image,crop,[...items.values()].filter(i=>!i.target&&allowed(i,category)),45,aliases);
  return{crop,candidates,found:match.matches.map(p=>({id:p.options[0].id,x:p.x,y:p.y})),filled:match.filled,
         expected:setup.items.map(x=>({id:x.id,x:x.x,y:x.y})),image:await new Promise(resolve=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.readAsDataURL(blob);})};
}'''

class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


def main():
    import base64
    OUTPUT.mkdir(exist_ok=True)
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(QuietHandler,directory=str(ROOT/'docs')))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    base=f'http://127.0.0.1:{server.server_port}/'
    requests,errors=[],[]
    report={'browser':'Chromium','checks':[],'recognition_fixtures':[]}
    try:
      with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':1440,'height':1000})
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:requests.append(r.url))
        page.goto(base)
        page.wait_for_function("document.querySelector('#validation').textContent.includes('Verified')")
        assert '2,947' in page.locator('#load-status').inner_text()
        assert not [r for r in requests if '/matchups/' in r], 'No matchup slices before a query'
        page.locator('#evaluate').click();page.wait_for_selector('#counter-rows tr')
        assert len([r for r in requests if '/matchups/' in r])==1
        first_id=page.locator('#counter-rows tr button').first.inner_text()
        assert first_id=='#51838'
        assert 'WIN' in page.locator('#counter-rows tr').first.inner_text()
        assert page.locator('#counter-rows tr').count()==20
        page.locator('#next').click();assert '21–40' in page.locator('#page-info').inner_text()
        page.locator('#previous').click();assert '1–20' in page.locator('#page-info').inner_text()
        report['checks'].append('lookup requests exactly one slice; descending counter order and pagination')
        page.locator('#core-only').check();assert '#55868'==page.locator('#counter-rows tr button').first.inner_text()
        page.locator('#counter-rows tr button').first.click()
        assert page.locator('#setup-detail li').count()>3
        assert 'LOSS' in page.locator('#counter-rows tr').first.inner_text()
        report['checks'].append('per-enemy full defensive core search; exact outgoing/incoming detail')
        page.locator('#core-only').uncheck();page.locator('#show-matrix').click();page.wait_for_selector('.heatmap tbody tr')
        assert page.locator('.heatmap tbody tr').count()==11
        for i in range(11):assert page.locator('.heatmap tbody tr').nth(i).locator('button').nth(i).inner_text()=='0.000'
        page.locator('.heatmap tbody tr').first.locator('button').nth(1).click()
        assert 'vs #' in page.locator('#matrix-status').inner_text()
        report['checks'].append('matrix rows load on demand; zero diagonal; cell inspection')
        with page.expect_download() as dl: page.locator('#export-layout').click()
        saved=OUTPUT/'inventory.json';dl.value.save_as(saved)
        page.locator('#clear').click();assert page.locator('#evaluate').is_disabled()
        page.locator('#layout-file').set_input_files(saved);page.wait_for_function("document.querySelector('#validation').textContent.includes('Verified')")
        assert '#56878' in page.locator('#validation').inner_text()
        report['checks'].append('save/open inventory round trip')
        # Remove MP8, then drag it back to exactly the same location.
        page.get_by_role('button',name='Remove MP8',exact=True).click();assert page.locator('#evaluate').is_disabled()
        tile=page.locator('.palette-item[data-id="mp8"]');box=page.locator('#inventory').bounding_box()
        tile.drag_to(page.locator('#inventory'),target_position={'x':box['width']/24,'y':box['height']/16})
        assert '#56878' in page.locator('#validation').inner_text()
        report['checks'].append('drag/drop editing and partial inventory gating')
        page.locator('#category').select_option('rifle');page.wait_for_function("document.querySelector('#load-status').textContent.includes('2,066')")
        page.locator('#load-winner').click();assert '#85548' in page.locator('#validation').inner_text()
        page.locator('#evaluate').click();page.wait_for_selector('#counter-rows tr')
        assert page.locator('#counter-rows tr button').first.inner_text()=='#52764'
        page.locator('#sort').select_option('mean_net_hp_pp');assert page.locator('#counter-rows tr button').first.inner_text()=='#52780'
        page.locator('#sort').select_option('weighted_win_rate');assert page.locator('#counter-rows tr button').first.inner_text()=='#54380'
        report['checks'].append('AK category isolation and alternative global sorts')
        page.locator('#item-search').fill('scorpion');assert page.locator('.palette-item[data-id="ak_24_7"]').count()==1
        page.locator('#item-search').fill('specialization_shotgun');assert page.locator('.palette-item[data-id="specialization_rifle"]').count()==1
        page.locator('#item-search').fill('')
        report['checks'].append('Shotgun/Sniper alias names resolve to canonical AK library items')
        # Recognition fixtures: frames, layouts, scale, compression, warehouse.
        scenarios=[('rifle','most_wins','game',False,50,None),('rifle','best_mean_trade','caption',True,36,None),('submachine','most_wins','caption',True,42,None),('rifle','most_wins','game',True,50,'shotgun'),('rifle','best_mean_trade','caption',True,42,'sniper')]
        fixture_path=None
        for category,key,mode,jpeg,cell,alias_kind in scenarios:
          setup=json.loads((ROOT/'results'/f'{category}_results.json').read_text())[key]
          if alias_kind:
            setup['art_ids']={'ak_24_7':'scorpion' if alias_kind=='shotgun' else 'psk1','specialization_rifle':'specialization_'+alias_kind,'soft_nosed_bullet_large':'soft_nosed_bullet_shotgun','tracer_ammunition_large':'tracer_ammunition_shotgun'}
          result=page.evaluate(FIXTURE,{'setup':setup,'category':category,'mode':mode,'jpeg':jpeg,'cell':cell})
          assert {x['id'] for x in result['found']}=={x['id'] for x in result['expected']},result
          assert 'accuracy_all' not in {x['id'] for x in result['found']},'Warehouse item leaked into equipped inventory'
          crop=result['crop']
          assert any(abs(c['x']-crop['x'])<12 and abs(c['y']-crop['y'])<12 and abs(c['w']-crop['w'])<18 for c in result['candidates']), 'No correct automatic crop candidate'
          path=OUTPUT/f'{category}-{key}.{"jpg" if jpeg else "png"}';path.write_bytes(base64.b64decode(result['image'].split(',')[1]))
          if category=='rifle' and key=='most_wins':fixture_path=path;fixture_crop=crop
          report['recognition_fixtures'].append({'category':category,'selection':key,'layout':mode,'jpeg':jpeg,'cell_pixels':cell,'items_correct':len(result['found']),'warehouse_excluded':True,'temporary_alias':alias_kind})
        # Exercise the actual file upload / crop / review / apply UI.
        page.locator('#screenshot-open').click();page.locator('#screenshot-file').set_input_files(fixture_path)
        page.wait_for_function("document.querySelector('#screenshot-status').textContent.includes('regions')")
        for k,v in fixture_crop.items():page.locator('#crop-'+k).fill(str(v));page.locator('#crop-'+k).dispatch_event('change')
        page.locator('#recognize').click();page.wait_for_selector('#recognition-items select')
        assert page.locator('#recognition-items select').count()==9
        assert page.locator('#apply-recognition').is_disabled()
        page.locator('#confirm-tier').check();page.locator('#apply-recognition').click()
        assert '#85548' in page.locator('#validation').inner_text()
        assert page.locator('#screenshot-dialog').is_hidden()
        report['checks'].append('screenshot upload, explicit crop, identity review, tier confirmation, and import')
        # Clipboard paste event uses the same local image pipeline.
        page.locator('#screenshot-open').click()
        page.evaluate('''async()=>{const c=document.createElement('canvas');c.width=40;c.height=40;const blob=await new Promise(r=>c.toBlob(r));const dt=new DataTransfer();dt.items.add(new File([blob],'pasted.png',{type:'image/png'}));document.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true}));}''')
        page.wait_for_function("document.querySelector('#screenshot-status').textContent.includes('No reliable grid')")
        page.locator('#screenshot-close').click()
        report['checks'].append('clipboard paste and manual crop fallback for unrecognizable images')
        page.screenshot(path=str(OUTPUT/'desktop.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(OUTPUT/'mobile.png'),full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'), 'Mobile page overflow'
        report['checks'].append('390px mobile layout without horizontal page overflow')
        assert not errors,errors
        assert all(r.startswith(base) or r.startswith('blob:') or r.startswith('data:') for r in requests),'Unexpected outbound request'
        report['checks'].append('no page errors and no off-site runtime or screenshot requests')
        browser.close()
    finally:
      server.shutdown();server.server_close()
    (OUTPUT/'browser-checks.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
