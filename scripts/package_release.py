"""Build a clean single archive; exclude root weights, never source models."""
from pathlib import Path
import argparse
import json
import zipfile

root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('output',type=Path);args=p.parse_args()
out=args.output.resolve();out.parent.mkdir(parents=True,exist_ok=True)
excluded=[];included=[]
for file in sorted(root.rglob('*')):
    if not file.is_file():continue
    rel=file.relative_to(root)
    if (file.resolve()==out or file.is_symlink() or rel.parts[0] in {'models','artifacts','dist','build'}
        or any(x.startswith('.') and x!='.env.example' for x in rel.parts)
        or any(x in {'__pycache__','node_modules'} or x.endswith('.egg-info') or x.startswith('concat-') for x in rel.parts)
        or file.suffix in {'.pyc','.zip','.code-workspace'} or file.name=='.env'):
        excluded.append(str(rel));continue
    included.append((file,rel))
(root/'CLEANUP.json').write_text(json.dumps({'excluded_from_release':excluded,'note':'Source models included. Downloadable model weights, caches, environments and temporary outputs excluded.'},indent=2))
with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for file,rel in included:z.write(file,str(Path('agentic-content-factory')/rel))
with zipfile.ZipFile(out) as z:
    for required in ['setup_channel.sh','channel.sh','scripts/download_voice.sh','src/content_factory/models/content.py','src/content_factory/config/asset_license_registry.json','src/content_factory/channel/catalog.py','examples/channel/demo.json']:
        assert 'agentic-content-factory/'+required in z.namelist(),required
    assert z.testzip() is None
print(f'{out}: {out.stat().st_size:,} bytes; {len(included)} files')
