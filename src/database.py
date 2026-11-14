from pathlib import Path
import os
from sqlalchemy import create_engine, event, String, Text, Integer, LargeBinary, ForeignKey, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = Path(os.environ.get('GIT_SUPPORT_ENV_PATH', str(ROOT / '.env')))
config = dotenv_values(ENV_PATH, encoding='utf-8-sig')
url = os.environ.get('DATABASE_URL') or config.get('DATABASE_URL') or f"sqlite:///{(ROOT / 'data' / 'app.sqlite3').as_posix()}"
if url.startswith('sqlite:///') and not url.endswith(':memory:'):
    Path(url.removeprefix('sqlite:///')).parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(url, connect_args={'timeout': 15} if url.startswith('sqlite:') else {})
if engine.dialect.name == 'sqlite':
    @event.listens_for(engine, 'connect')
    def configure_sqlite(connection, _record):
        cursor = connection.cursor()
        cursor.execute('PRAGMA foreign_keys=ON')
        cursor.execute('PRAGMA busy_timeout=15000')
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.close()
Session = sessionmaker(bind=engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class Setting(Base):
    __tablename__ = 'settings'
    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)

class Event(Base):
    __tablename__ = 'events'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36), index=True)
    created_at: Mapped[str] = mapped_column(String(40))
    operation: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(200), default='')
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    cost_rub: Mapped[str | None] = mapped_column(String(80), nullable=True)
    payload: Mapped[str] = mapped_column(Text)
class Document(Base):
    __tablename__ = 'documents'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    source_type: Mapped[str] = mapped_column(String(20))
    language: Mapped[str] = mapped_column(String(50))
    version: Mapped[str] = mapped_column(String(200), default='')
    published_at: Mapped[str] = mapped_column(String(10), default='')
    source_url: Mapped[str] = mapped_column(Text, default='')
    git_commit: Mapped[str] = mapped_column(String(100), default='')
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    uploaded_at: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30))
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    extracted_text: Mapped[str] = mapped_column(Text)
    original: Mapped[bytes] = mapped_column(LargeBinary)
class ChunkRun(Base):
    __tablename__ = 'chunk_runs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(36), index=True)
    revision: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(40))
    warnings: Mapped[str] = mapped_column(Text)
    chunk_count: Mapped[int] = mapped_column(Integer)

class PreparedChunk(Base):
    __tablename__ = 'prepared_chunks'
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey('chunk_runs.id'), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    chunk_id: Mapped[str] = mapped_column(String(64))
    payload: Mapped[str] = mapped_column(Text)

class IndexGeneration(Base):
    __tablename__ = 'index_generations'
    document_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36))
    revision: Mapped[str] = mapped_column(String(64))
    collection: Mapped[str] = mapped_column(String(80))
    model: Mapped[str] = mapped_column(String(200))
    chunk_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(String(40))


class IndexPending(Base):
    __tablename__ = 'index_pending'
    collection: Mapped[str] = mapped_column(String(80), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[str] = mapped_column(String(40))


class ChatConversation(Base):
    __tablename__ = 'chat_conversations'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(100))
    updated_at: Mapped[str] = mapped_column(String(40))
    summary: Mapped[str] = mapped_column(Text)
    turn_count: Mapped[int] = mapped_column(Integer)


class ChatTurn(Base):
    __tablename__ = 'chat_turns'
    conversation_id: Mapped[str] = mapped_column(ForeignKey('chat_conversations.id'), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey('events.id'), unique=True)


class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nickname: Mapped[str] = mapped_column(String(32))
    nickname_normalized: Mapped[str] = mapped_column(String(32), unique=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    api_key_version: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))


class UserSession(Base):
    __tablename__ = 'user_sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    created_at: Mapped[str] = mapped_column(String(40))
    expires_at: Mapped[str] = mapped_column(String(40), index=True)


class UserSetting(Base):
    __tablename__ = 'user_settings'
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class EventOwner(Base):
    __tablename__ = 'event_owners'
    event_id: Mapped[int] = mapped_column(ForeignKey('events.id', ondelete='CASCADE'), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    key_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class ConversationOwner(Base):
    __tablename__ = 'conversation_owners'
    conversation_id: Mapped[str] = mapped_column(ForeignKey('chat_conversations.id', ondelete='CASCADE'), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
