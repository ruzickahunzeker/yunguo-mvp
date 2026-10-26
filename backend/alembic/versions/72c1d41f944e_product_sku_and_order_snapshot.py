"""Stable product SKU and order entitlement snapshot.

Revision ID: 72c1d41f944e
Revises: 8ac51c872aa1
"""
from alembic import op
import sqlalchemy as sa

revision = '72c1d41f944e'
down_revision = '8ac51c872aa1'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('products') as batch:
        batch.add_column(sa.Column('sku', sa.String(length=40), nullable=True))
        batch.add_column(sa.Column('subscription_months', sa.Integer(), nullable=True))
        batch.create_unique_constraint('uq_product_sku', ['sku'])
        batch.create_check_constraint('ck_product_subscription_months', 'subscription_months IS NULL OR subscription_months BETWEEN 1 AND 36')
    with op.batch_alter_table('orders') as batch:
        batch.add_column(sa.Column('product_sku', sa.String(length=40), nullable=True))
        batch.add_column(sa.Column('product_description', sa.Text(), nullable=True))
        batch.add_column(sa.Column('subscription_months', sa.Integer(), nullable=True))

def downgrade():
    with op.batch_alter_table('orders') as batch:
        batch.drop_column('subscription_months')
        batch.drop_column('product_description')
        batch.drop_column('product_sku')
    with op.batch_alter_table('products') as batch:
        batch.drop_constraint('ck_product_subscription_months', type_='check')
        batch.drop_constraint('uq_product_sku', type_='unique')
        batch.drop_column('subscription_months')
        batch.drop_column('sku')
