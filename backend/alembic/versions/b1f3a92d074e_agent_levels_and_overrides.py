"""Configurable agent tiers, level prices and individual product policies.
Backfills the existing agents.level values without modifying orders or balances.
"""
from datetime import datetime, timezone
from alembic import op
import sqlalchemy as sa

revision = 'b1f3a92d074e'
down_revision = '6cdb7ffa6ccd'
branch_labels = None
depends_on = None

def timestamps():
    return [sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False)]

def upgrade():
    op.create_table('agent_levels',
        sa.Column('id', sa.Integer(), sa.Identity(start=2), primary_key=True),
        sa.Column('name', sa.String(40), nullable=False, unique=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('sort', sa.Integer(), nullable=False), *timestamps())
    connection = op.get_bind()
    labels = connection.execute(sa.text('SELECT DISTINCT level FROM agents ORDER BY level')).scalars().all()
    names = ['一级代理'] + [label for label in labels if label != '一级代理']
    level_table = sa.table('agent_levels', sa.column('id', sa.Integer), sa.column('name', sa.String),
        sa.column('active', sa.Boolean), sa.column('sort', sa.Integer),
        sa.column('created_at', sa.DateTime(timezone=True)), sa.column('updated_at', sa.DateTime(timezone=True)))
    moment = datetime.now(timezone.utc)
    op.bulk_insert(level_table, [{'id': i, 'name': name, 'active': True, 'sort': i-1, 'created_at': moment, 'updated_at': moment} for i, name in enumerate(names, 1)])
    if connection.dialect.name == 'postgresql':
        connection.execute(sa.text("SELECT setval(pg_get_serial_sequence('agent_levels','id'), (SELECT MAX(id) FROM agent_levels), true)"))
    op.add_column('agents', sa.Column('level_id', sa.Integer(), nullable=True))
    connection.execute(sa.text('UPDATE agents SET level_id = (SELECT id FROM agent_levels WHERE name = agents.level)'))
    with op.batch_alter_table('agents') as batch:
        batch.alter_column('level_id', existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key('fk_agents_level_id', 'agent_levels', ['level_id'], ['id'])
        batch.create_index('ix_agents_level_id', ['level_id'])
        batch.drop_column('level')
    op.create_table('agent_level_prices',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('level_id', sa.Integer(), sa.ForeignKey('agent_levels.id'), nullable=False),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('price', sa.BigInteger(), nullable=False), *timestamps(),
        sa.UniqueConstraint('level_id','product_id',name='uq_level_product_price'),
        sa.CheckConstraint('price >= 0',name='ck_level_product_price'))
    op.create_table('agent_product_rules',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('agent_id', sa.Integer(), sa.ForeignKey('agents.user_id'), nullable=False),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('price', sa.BigInteger(), nullable=True),
        sa.Column('allowed', sa.Boolean(), nullable=False), *timestamps(),
        sa.UniqueConstraint('agent_id','product_id',name='uq_agent_product_rule'),
        sa.CheckConstraint('price IS NULL OR price >= 0',name='ck_agent_override_price'))

def downgrade():
    op.drop_table('agent_product_rules')
    op.drop_table('agent_level_prices')
    op.add_column('agents', sa.Column('level', sa.String(40), nullable=True))
    op.get_bind().execute(sa.text('UPDATE agents SET level = (SELECT name FROM agent_levels WHERE id = agents.level_id)'))
    with op.batch_alter_table('agents') as batch:
        batch.alter_column('level', existing_type=sa.String(40), nullable=False)
        batch.drop_index('ix_agents_level_id')
        batch.drop_constraint('fk_agents_level_id', type_='foreignkey')
        batch.drop_column('level_id')
    op.drop_table('agent_levels')
