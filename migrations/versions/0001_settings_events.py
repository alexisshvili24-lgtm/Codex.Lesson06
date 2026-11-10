from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('settings', sa.Column('name', sa.String(100), primary_key=True), sa.Column('value', sa.Text(), nullable=False))
    op.create_table('events', sa.Column('id', sa.Integer(), primary_key=True), sa.Column('request_id', sa.String(36), nullable=False), sa.Column('created_at', sa.String(40), nullable=False), sa.Column('operation', sa.String(40), nullable=False), sa.Column('status', sa.String(40), nullable=False), sa.Column('model', sa.String(200), nullable=False), sa.Column('duration_ms', sa.Integer(), nullable=False), sa.Column('cost_rub', sa.String(80), nullable=True), sa.Column('payload', sa.Text(), nullable=False))
    op.create_index('ix_events_request_id', 'events', ['request_id'])

def downgrade():
    op.drop_index('ix_events_request_id', table_name='events')
    op.drop_table('events')
    op.drop_table('settings')