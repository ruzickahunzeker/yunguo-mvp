from datetime import datetime
from typing import Literal, Annotated
from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator

Money = Annotated[int, Field(strict=True, ge=0, le=100_000_000)]
class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')
class AlertAcknowledge(Input):
    expected_occurrences: int = Field(strict=True, ge=1)
    note: str = Field(min_length=3, max_length=200)
    @field_validator('note', mode='before')
    @classmethod
    def trim_note(cls, value):
        return value.strip() if isinstance(value, str) else value
class Register(Input):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    name: str = Field(default='', max_length=80)
class Login(Input):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
class Profile(Input):
    name: str = Field(max_length=80)
class PasswordChange(Input):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)
class ForgotPassword(Input):
    email: EmailStr
class ResetPassword(Input):
    token: str = Field(pattern=r'^[a-f0-9]{64}$')
    new_password: str = Field(min_length=10, max_length=128)
class ProductInput(Input):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default='', max_length=5000)
    category: str = Field(default='数字服务', min_length=1, max_length=60)
    original_price: Money
    price: Money
    agent_price: Money
    stock: int = Field(ge=0, le=1_000_000)
    active: bool = True
    sort: int = 0
    verification_required: bool = False
class ProductUpdate(ProductInput):
    expected_updated_at: datetime
class Buy(Input):
    product_id: int = Field(gt=0)
    expected_amount: Money
class MockDirectTopup(Input):
    product_id: int = Field(strict=True, gt=0)
    expected_amount: Money
    mock_reference: str = Field(pattern=r'^mock-customer-[a-f0-9]{12,32}$')
class Redeem(Input):
    code: str = Field(min_length=16, max_length=100)
class Lookup(Input):
    order_id: str = Field(min_length=10, max_length=40)
    lookup_token: str = Field(min_length=20, max_length=100)
class CodeBatch(Input):
    product_id: int = Field(gt=0)
    quantity: int = Field(ge=1, le=500)
    valid_days: int = Field(default=30, ge=1, le=365)
    owner_id: int | None = Field(default=None, gt=0)
class AgentCodePurchase(Input):
    product_id: int = Field(strict=True, gt=0, le=2_147_483_647)
    quantity: int = Field(strict=True, ge=1, le=500)
    valid_days: int = Field(default=30, strict=True, ge=1, le=365)
    expected_unit_price: Money
class CodeVoid(Input):
    ids: list[int] = Field(min_length=1, max_length=500)
class Recharge(Input):
    amount: int = Field(strict=True, gt=0, le=1_000_000)
class WalletAdjust(Input):
    amount: int = Field(strict=True, ge=-100_000_000, le=100_000_000)
    note: str = Field(min_length=3, max_length=200)
    operation: Literal['adjust','freeze','unfreeze'] = 'adjust'
class UserUpdate(Input):
    active: bool
    role: Literal['user','agent','admin']
class OrderAction(Input):
    action: Literal['complete','fail','retry','refund','cancel']
    note: str = Field(min_length=3, max_length=200)
class FulfillmentCheckInput(Input):
    step: Literal['payment','entitlement','renewal_stopped','card_removed']
    status: Literal['VERIFIED','FAILED']
    reference: str = Field(min_length=8, max_length=64, pattern=r'^[A-Za-z][A-Za-z0-9_-]{7,63}$')
class SettingsUpdate(Input):
    sales_enabled: bool
    redemption_enabled: bool

class AgentLevelInput(Input):
    name: str = Field(min_length=1, max_length=40, pattern=r'.*\S.*')
    active: bool = True
    sort: int = Field(default=0, ge=-1000000, le=1000000)
class AgentAssignment(Input):
    level_id: int = Field(gt=0)
class AgentParentAssignment(Input):
    parent_id: int | None = Field(default=None, strict=True, gt=0, le=2_147_483_647)
    expected_parent_id: int | None = Field(strict=True, gt=0, le=2_147_483_647)
class AgentLevelPriceInput(Input):
    price: Money
class AgentProductRuleInput(Input):
    price: Money | None = None
    allowed: bool = True

class VerifyEmail(Input):
    token: str = Field(pattern=r'^[a-f0-9]{64}$')
