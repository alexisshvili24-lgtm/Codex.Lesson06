from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('chunk_runs', sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('document_id', sa.String(36), nullable=False), sa.Column('revision', sa.String(64), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False), sa.Column('warnings', sa.Text(), nullable=False),
        sa.Column('chunk_count', sa.Integer(), nullable=False))
    op.create_index('ix_chunk_runs_document_id', 'chunk_runs', ['document_id'])
    op.create_table('prepared_chunks', sa.Column('run_id', sa.String(36), sa.ForeignKey('chunk_runs.id'), primary_key=True),
        sa.Column('position', sa.Integer(), primary_key=True), sa.Column('chunk_id', sa.String(64), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False))

def downgrade():
    op.drop_table('prepared_chunks')
    op.drop_index('ix_chunk_runs_document_id', table_name='chunk_runs')
    op.drop_table('chunk_runs')