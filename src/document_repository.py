import json
from datetime import datetime, timezone
from sqlalchemy import select
from src.database import Session, Document, IndexGeneration, IndexPending
from src.event_store import add_event

FIELDS = ('id', 'title', 'source_type', 'language', 'version', 'published_at', 'source_url', 'git_commit', 'filename', 'sha256', 'uploaded_at', 'status', 'chunk_count')

def serialize(row, text=False):
    data = {field: getattr(row, field) for field in FIELDS}
    if text:
        data['extracted_text'] = row.extracted_text
    return data

def list_documents():
    with Session() as s:
        return [serialize(row) for row in s.scalars(select(Document).order_by(Document.uploaded_at.desc())).all()]

def get_document(document_id):
    with Session() as s:
        row = s.get(Document, document_id)
        return serialize(row, True) if row else None

def find_duplicate(sha256, excluded_id=None):
    with Session() as s:
        query = select(Document.id, Document.title).where(Document.sha256 == sha256)
        if excluded_id:
            query = query.where(Document.id != excluded_id)
        row = s.execute(query.order_by(Document.uploaded_at)).first()
        return {'id': row.id, 'title': row.title} if row else None
def write_document(values, request_id, replace=False):
    with Session.begin() as s:
        if replace:
            row = s.get(Document, values['id'])
            if row is None:
                return None
            from src.chunk_store import _revision, _selected
            previous_revision = _revision(row, _selected(s))
            for key, value in values.items():
                setattr(row, key, value)
            generation = s.get(IndexGeneration, row.id)
            if generation and _revision(row, _selected(s)) != previous_revision:
                if s.get(IndexPending, generation.collection) is None:
                    s.add(IndexPending(collection=generation.collection, document_id=row.id, created_at=datetime.now(timezone.utc).isoformat()))
                s.delete(generation)
        else:
            row = Document(**values)
            s.add(row)
        add_event(s, request_id, 'document_replace' if replace else 'document_upload', 'ok',
                  payload={'document_id': values['id'], 'filename': values['filename'], 'sha256': values['sha256']})
        return serialize(row)

def delete_document(document_id, request_id):
    with Session.begin() as s:
        row = s.get(Document, document_id)
        if row is None:
            return False
        event_payload = {'document_id': row.id, 'filename': row.filename, 'sha256': row.sha256}
        s.delete(row)
        add_event(s, request_id, 'document_delete', 'ok',
                  payload=event_payload)
        return True
