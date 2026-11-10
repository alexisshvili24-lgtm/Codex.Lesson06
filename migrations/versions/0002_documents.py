from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('documents',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('source_type', sa.String(20), nullable=False),
        sa.Column('language', sa.String(50), nullable=False),
        sa.Column('version', sa.String(200), nullable=False),
        sa.Column('published_at', sa.String(10), nullable=False),
        sa.Column('source_url', sa.Text, nullable=False),
        sa.Column('git_commit', sa.String(100), nullable=False),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('uploaded_at', sa.String(40), nullable=False),
        sa.Column('status', sa.String(30), nullable=False),
        sa.Column('chunk_count', sa.Integer, nullable=False),
        sa.Column('extracted_text', sa.Text, nullable=False),
        sa.Column('original', sa.LargeBinary, nullable=False))

def downgrade():
    op.drop_table('documents')