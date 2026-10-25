"""Generate local configuration without printing secrets; never overwrite existing files."""
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
template = (root / '.env.example').read_text()
for target in [root / '.env', root / 'backend' / '.env']:
    if target.exists():
        print(f'{target.relative_to(root)} already exists; preserved')
        continue
    content = template.replace('replace-with-independent-random-jwt-secret', secrets.token_hex(32)).replace(
        'replace-with-independent-random-card-pepper', secrets.token_hex(32)).replace(
        'replace-with-random-database-password', secrets.token_hex(24))
    with target.open('x') as file:
        file.write(content)
    target.chmod(0o600)
    print(f'Created {target.relative_to(root)} with independent secrets')
