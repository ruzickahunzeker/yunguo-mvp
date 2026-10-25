import pytest
from app.core.config import Settings
from app.services.fulfillment import adapter_for


def base(**overrides):
    values=dict(_env_file=None,app_env='development',database_url='sqlite:///dev.db',redis_url='',jwt_secret='a'*40,code_pepper='b'*40)
    values.update(overrides)
    return values


def test_authorized_adapter_fails_closed_without_provider_call():
    result=adapter_for('authorized').fulfill('YG-test')
    assert result.status=='QUEUED' and '尚未配置' in result.note


@pytest.mark.parametrize('url', ['', 'http://provider.example.com/api', 'https://provider.example.com/api'])
def test_production_authorized_requires_all_contract_secrets(url,monkeypatch):
    monkeypatch.delenv('DEMO_RECHARGE_ENABLED', raising=False)
    values=base(app_env='production',database_url='postgresql+psycopg://x/x',redis_url='redis://x',fulfillment_mode='authorized',fulfillment_provider_url=url,fulfillment_provider_token='t'*32,fulfillment_webhook_secret='s'*32)
    if url.startswith('https://'):
        assert Settings(**values).fulfillment_mode=='authorized'
    else:
        with pytest.raises(ValueError):Settings(**values)


def test_production_authorized_rejects_short_contract_secrets():
    values=base(app_env='production',database_url='postgresql+psycopg://x/x',redis_url='redis://x',fulfillment_mode='authorized',fulfillment_provider_url='https://provider.example.com/api',fulfillment_provider_token='short',fulfillment_webhook_secret='short')
    with pytest.raises(ValueError):Settings(**values)


def test_production_mock_and_direct_simulation_remain_blocked():
    values=base(app_env='production',database_url='postgresql+psycopg://x/x',redis_url='redis://x',fulfillment_mode='mock',mock_direct_topup_enabled=True)
    with pytest.raises(ValueError):Settings(**values)


def test_production_mock_fulfillment_is_blocked_even_without_direct_simulation():
    values=base(app_env='production',database_url='postgresql+psycopg://x/x',redis_url='redis://x',demo_recharge_enabled=False,fulfillment_mode='mock',mock_direct_topup_enabled=False)
    with pytest.raises(ValueError, match='mock fulfillment'):
        Settings(**values)
