"""Запись коллекций, ожидающих публикации или очистки."""
from alembic import op
import sqlalchemy as sa
revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('index_pending', sa.Column('collection', sa.String(80), primary_key=True), sa.Column('document_id', sa.String(36), nullable=False), sa.Column('created_at', sa.String(40), nullable=False))

def downgrade():
    op.drop_table('index_pending')
