"""Add per-order fulfillment verification for selected products.

Revision ID: 8ac51c872aa1
Revises: 32fb2f23c757
"""
from alembic import op
import sqlalchemy as sa

revision = '8ac51c872aa1'
down_revision = '32fb2f23c757'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('products') as batch:
        batch.add_column(sa.Column('verification_required', sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table('orders') as batch:
        batch.add_column(sa.Column('verification_required', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table('fulfillment_checks',
        sa.Column('order_id', sa.String(length=40), sa.ForeignKey('orders.id'), primary_key=True),
        sa.Column('step', sa.String(length=30), primary_key=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('reference', sa.String(length=64), nullable=False),
        sa.Column('actor_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("step IN ('payment','entitlement','renewal_stopped','card_removed')", name='ck_fulfillment_check_step'),
        sa.CheckConstraint("status IN ('VERIFIED','FAILED')", name='ck_fulfillment_check_status'))

def downgrade():
    op.drop_table('fulfillment_checks')
    with op.batch_alter_table('orders') as batch:
        batch.drop_column('verification_required')
    with op.batch_alter_table('products') as batch:
        batch.drop_column('verification_required')
