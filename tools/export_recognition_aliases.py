"""Export temporary, dimension-preserving recognition aliases for the AK model."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def export():
    catalog=json.loads((ROOT/'data/catalog.json').read_text())
    rows=[]
    targets={'specialization_shotgun':'specialization_rifle','specialization_sniper':'specialization_rifle',
             'soft_nosed_bullet_shotgun':'soft_nosed_bullet_large','tracer_ammunition_shotgun':'tracer_ammunition_large'}
    for item in catalog:
        target=targets.get(item['id'])
        if item.get('type')=='weapon' and item.get('kind') in ('shotgun','sniper') and item.get('size')==[5,3]:target='ak_24_7'
        if not target:continue
        def icon(path):return 'icons/'+path.split('/item/')[1].replace('/','_') if path else None
        rows.append(dict(id=item['id'],target=target,name=item['name'],width=item['size'][0],height=item['size'][1],
                         image=icon(item.get('imgGold') if item.get('kind')=='ammo' else item['img']),overlay=icon(item.get('imgIcon'))))
    (ROOT/'docs/data/recognition-aliases.json').write_text(json.dumps(rows,indent=2)+'\n')
    return rows
if __name__=='__main__':print(f'Exported {len(export())} AK approximation aliases')
