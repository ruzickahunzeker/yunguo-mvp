"""Fulfillment adapter boundary. Only local mock/manual providers ship in MVP.
An authorized external provider must use a durable outbox, provider idempotency,
signed callbacks and a reconciliation process before being enabled.
"""
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class FulfillmentResult:
    status: str
    note: str

class FulfillmentAdapter(Protocol):
    def fulfill(self, order_id: str) -> FulfillmentResult: ...

class MockAdapter:
    def fulfill(self, order_id: str) -> FulfillmentResult:
        return FulfillmentResult('COMPLETED', '演示履约，无真实第三方订阅开通')

class ManualAdapter:
    def fulfill(self, order_id: str) -> FulfillmentResult:
        return FulfillmentResult('QUEUED', '等待管理员核验确认')

class AuthorizedProviderAdapter:
    """Deliberate fail-closed placeholder until a contracted provider is integrated."""
    def fulfill(self, order_id: str) -> FulfillmentResult:
        return FulfillmentResult('QUEUED', '授权履约服务尚未配置，等待供应商适配器')

def adapter_for(mode: str) -> FulfillmentAdapter:
    if mode == 'mock':
        return MockAdapter()
    if mode == 'manual':
        return ManualAdapter()
    if mode == 'authorized':
        return AuthorizedProviderAdapter()
    raise ValueError('Unsupported fulfillment provider')
