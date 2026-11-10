"""Сведения об активных поколениях индекса."""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('index_generations',
        sa.Column('document_id', sa.String(36), primary_key=True),
        sa.Column('run_id', sa.String(36), nullable=False),
        sa.Column('revision', sa.String(64), nullable=False),
        sa.Column('collection', sa.String(80), nullable=False),
        sa.Column('model', sa.String(200), nullable=False),
        sa.Column('chunk_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False))

def downgrade():
    op.drop_table('index_generations')
