"""Публикация поколения после проверки актуальности документа."""
from datetime import datetime, timezone
from sqlalchemy import select
from src.database import Session, Document, ChunkRun, IndexGeneration, IndexPending, Setting
from src.chunk_store import _revision, _selected


class StaleIndex(ValueError):
    pass


def active(document_id):
    with Session() as session:
        row = session.get(IndexGeneration, document_id)
        document = session.get(Document, document_id)
        if row is None or document is None:
            return None
        model = session.get(Setting, 'embedding_model')
        model_value = model.value if model else 'baai/bge-m3'
        if row.revision != _revision(document, _selected(session)) or row.model != model_value:
            return None
        latest = session.scalars(select(ChunkRun).where(ChunkRun.document_id == document_id, ChunkRun.revision == row.revision).order_by(ChunkRun.created_at.desc(), ChunkRun.id.desc()).limit(1)).first()
        if latest is None:
            return None
        if latest.id != row.run_id:
            from src.database import PreparedChunk
            old_ids = list(session.scalars(select(PreparedChunk.chunk_id).where(PreparedChunk.run_id == row.run_id).order_by(PreparedChunk.position)).all())
            new_ids = list(session.scalars(select(PreparedChunk.chunk_id).where(PreparedChunk.run_id == latest.id).order_by(PreparedChunk.position)).all())
            if old_ids != new_ids:
                return None
        return {key: getattr(row, key) for key in ('document_id','run_id','revision','collection','model','chunk_count','created_at')}


def activate(document_id, run_id, revision, model, collection, count):
    with Session.begin() as session:
        document = session.get(Document, document_id)
        run = session.get(ChunkRun, run_id)
        current_model = session.get(Setting, 'embedding_model')
        configured_model = current_model.value if current_model else 'baai/bge-m3'
        if document is None or run is None or run.document_id != document_id or run.revision != revision or _revision(document, _selected(session)) != revision or configured_model != model or run.chunk_count != count:
            raise StaleIndex('Документ или настройки изменились во время индексации.')
        latest = session.scalars(select(ChunkRun).where(ChunkRun.document_id == document_id, ChunkRun.revision == revision).order_by(ChunkRun.created_at.desc(), ChunkRun.id.desc()).limit(1)).first()
        if latest is None or latest.id != run_id:
            raise StaleIndex('Чанки были подготовлены заново во время индексации.')
        row = session.get(IndexGeneration, document_id)
        previous = row.collection if row else None
        if row is None:
            row = IndexGeneration(document_id=document_id)
            session.add(row)
        row.run_id, row.revision, row.model, row.collection, row.chunk_count = run_id, revision, model, collection, count
        row.created_at = datetime.now(timezone.utc).isoformat()
        pending = session.get(IndexPending, collection)
        if pending:
            session.delete(pending)
        if previous and previous != collection and session.get(IndexPending, previous) is None:
            session.add(IndexPending(collection=previous, document_id=document_id, created_at=datetime.now(timezone.utc).isoformat()))
        return previous


def run_chunk_ids(run_id):
    from src.database import PreparedChunk
    with Session() as session:
        return list(session.scalars(select(PreparedChunk.chunk_id).where(PreparedChunk.run_id == run_id).order_by(PreparedChunk.position)).all())


def retired_collection(document_id):
    """Возвращает коллекцию только если её документ больше не существует."""
    with Session() as session:
        row = session.get(IndexGeneration, document_id)
        return row.collection if row and session.get(Document, document_id) is None else None


def forget_retired(document_id, collection):
    with Session.begin() as session:
        row = session.get(IndexGeneration, document_id)
        if row and row.collection == collection and session.get(Document, document_id) is None:
            session.delete(row)


def deleted_document_ids():
    with Session() as session:
        return list(session.scalars(select(IndexGeneration.document_id).outerjoin(Document, Document.id == IndexGeneration.document_id).where(Document.id.is_(None))).all())


def register_pending(document_id, collection):
    with Session.begin() as session:
        session.add(IndexPending(collection=collection, document_id=document_id, created_at=datetime.now(timezone.utc).isoformat()))


def pending_collections():
    with Session() as session:
        return list(session.scalars(select(IndexPending.collection)).all())


def forget_pending(collection):
    with Session.begin() as session:
        active = session.scalars(select(IndexGeneration).where(IndexGeneration.collection == collection)).first()
        if active is not None:
            return False
        row = session.get(IndexPending, collection)
        if row:
            session.delete(row)
        return True


def pending_is_unreferenced(collection):
    with Session() as session:
        return session.get(IndexPending, collection) is not None and session.scalars(select(IndexGeneration.document_id).where(IndexGeneration.collection == collection)).first() is None
