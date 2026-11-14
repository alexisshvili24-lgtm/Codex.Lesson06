"""Профили, сессии и владельцы личных данных."""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None

_PERSONAL_SETTINGS = (
    'system_prompt', 'vector_enabled', 'vector_threshold',
    'bm25_enabled', 'bm25_threshold',
)


def upgrade():
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('nickname', sa.String(32), nullable=False),
        sa.Column('nickname_normalized', sa.String(32), nullable=False),
        sa.Column('is_admin', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('api_key_version', sa.String(36), nullable=True),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.UniqueConstraint('nickname_normalized', name='uq_users_nickname_normalized'),
    )
    op.create_index('ix_users_nickname_normalized', 'users', ['nickname_normalized'])
    op.create_table(
        'user_sessions',
        sa.Column('token_hash', sa.String(64), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('expires_at', sa.String(40), nullable=False),
    )
    op.create_index('ix_user_sessions_user_id', 'user_sessions', ['user_id'])
    op.create_index('ix_user_sessions_expires_at', 'user_sessions', ['expires_at'])
    op.create_table(
        'user_settings',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('name', sa.String(100), primary_key=True),
        sa.Column('value', sa.Text(), nullable=False),
    )
    op.create_table(
        'event_owners',
        sa.Column('event_id', sa.Integer(), sa.ForeignKey('events.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('key_version_id', sa.String(36), nullable=True),
    )
    op.create_index('ix_event_owners_user_id', 'event_owners', ['user_id'])
    op.create_table(
        'conversation_owners',
        sa.Column('conversation_id', sa.String(36), sa.ForeignKey('chat_conversations.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
    )
    op.create_index('ix_conversation_owners_user_id', 'conversation_owners', ['user_id'])

    bind = op.get_bind()
    now = datetime.now(timezone.utc).isoformat()
    bind.execute(sa.text(
        "INSERT INTO users (id, nickname, nickname_normalized, is_admin, created_at) "
        "VALUES (1, 'admin', 'admin', :is_admin, :created_at)"
    ), {'is_admin': True, 'created_at': now})

    present = {row[0] for row in bind.execute(sa.text('SELECT name FROM settings')).all()}
    for name in _PERSONAL_SETTINGS:
        if name in present:
            bind.execute(sa.text(
                'INSERT INTO user_settings (user_id, name, value) '
                'SELECT 1, name, value FROM settings WHERE name = :name'
            ), {'name': name})

    bind.execute(sa.text(
        'INSERT INTO event_owners (event_id, user_id, key_version_id) '
        'SELECT id, 1, NULL FROM events'
    ))
    bind.execute(sa.text(
        'INSERT INTO conversation_owners (conversation_id, user_id) '
        'SELECT id, 1 FROM chat_conversations'
    ))


def downgrade():
    bind = op.get_bind()
    for name, value in bind.execute(sa.text(
        'SELECT name, value FROM user_settings WHERE user_id = 1'
    )).all():
        if name not in _PERSONAL_SETTINGS:
            continue
        exists = bind.execute(sa.text('SELECT 1 FROM settings WHERE name = :name'), {'name': name}).first()
        if exists:
            bind.execute(sa.text('UPDATE settings SET value = :value WHERE name = :name'),
                         {'name': name, 'value': value})
        else:
            bind.execute(sa.text('INSERT INTO settings (name, value) VALUES (:name, :value)'),
                         {'name': name, 'value': value})
    op.drop_index('ix_conversation_owners_user_id', table_name='conversation_owners')
    op.drop_table('conversation_owners')
    op.drop_index('ix_event_owners_user_id', table_name='event_owners')
    op.drop_table('event_owners')
    op.drop_table('user_settings')
    op.drop_index('ix_user_sessions_expires_at', table_name='user_sessions')
    op.drop_index('ix_user_sessions_user_id', table_name='user_sessions')
    op.drop_table('user_sessions')
    op.drop_index('ix_users_nickname_normalized', table_name='users')
    op.drop_table('users')
