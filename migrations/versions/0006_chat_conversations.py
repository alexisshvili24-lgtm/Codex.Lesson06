"""Беседы чата и ссылки на исторические снимки ответов."""
from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'chat_conversations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('title', sa.String(100), nullable=False),
        sa.Column('updated_at', sa.String(40), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('turn_count', sa.Integer(), nullable=False),
    )
    op.create_table(
        'chat_turns',
        sa.Column('conversation_id', sa.String(36), sa.ForeignKey('chat_conversations.id'), primary_key=True),
        sa.Column('position', sa.Integer(), primary_key=True),
        sa.Column('event_id', sa.Integer(), sa.ForeignKey('events.id'), nullable=False, unique=True),
    )


def downgrade():
    op.drop_table('chat_turns')
    op.drop_table('chat_conversations')
