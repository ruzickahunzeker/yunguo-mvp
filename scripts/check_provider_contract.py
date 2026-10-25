"""Validate authorized-provider configuration without making a network request."""
import os
from urllib.parse import urlsplit

mode = os.environ.get('FULFILLMENT_MODE', 'manual')
url = os.environ.get('FULFILLMENT_PROVIDER_URL', '')
token = os.environ.get('FULFILLMENT_PROVIDER_TOKEN', '')
secret = os.environ.get('FULFILLMENT_WEBHOOK_SECRET', '')

if mode != 'authorized':
    print(f'Provider contract check: mode={mode}; no external provider requested')
    raise SystemExit(0)

parsed = urlsplit(url)
errors = []
if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
    errors.append('FULFILLMENT_PROVIDER_URL must be a clean HTTPS origin/path')
if len(token) < 32:
    errors.append('FULFILLMENT_PROVIDER_TOKEN must be a secret of at least 32 characters')
if len(secret) < 32:
    errors.append('FULFILLMENT_WEBHOOK_SECRET must be a secret of at least 32 characters')
if errors:
    for error in errors: print('ERROR:', error)
    raise SystemExit(1)
print('Provider contract check: configuration shape is valid; no network request made')
