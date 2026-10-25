"""Package deployable sources, excluding secrets, caches and runtime/test data."""
from pathlib import Path
import tarfile

root=Path(__file__).resolve().parents[1]
output=root.parent / 'yunguo-mvp-source.tar.gz'
excluded={'.venv','.tools','node_modules','dist','__pycache__','.pytest_cache','.git','test-results','playwright-report','backups'}
def include(info):
    parts=Path(info.name).parts
    name=parts[-1]
    if any(part in excluded for part in parts):return None
    if (name.startswith('.env') and name!='.env.example') or name in {'.test-postgres.env','audit.json'} or '.db' in name or name.endswith(('.log','.sqlite','.sqlite3')):return None
    return info
with tarfile.open(output,'w:gz') as archive:
    archive.add(root,arcname=root.name,filter=include)
with tarfile.open(output) as archive:
    names=archive.getnames()
    assert not any(Path(name).name=='.env' for name in names)
    assert 'yunguo-mvp/.env.example' in names
print(f'Packaged {len(names)} entries, {output.stat().st_size} bytes; secrets/runtime data excluded')
