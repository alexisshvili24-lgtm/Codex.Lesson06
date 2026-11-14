"""Создаёт журнал и его владельца в одной транзакции."""
import json
from datetime import datetime, timezone

from src.database import Event, EventOwner, User
from src.request_context import current_user_id, current_key_version, has_api_key_snapshot


def add_event(session, request_id, operation, status, model='', duration_ms=0, cost=None,
              payload=None, *, user_id=None, key_version_id=None):
    owner_id = user_id if user_id is not None else current_user_id()
    row = Event(request_id=request_id, created_at=datetime.now(timezone.utc).isoformat(),
                operation=operation, status=status, model=model, duration_ms=duration_ms,
                cost_rub=str(cost) if cost is not None else None,
                payload=json.dumps(payload or {}, ensure_ascii=False, default=str))
    session.add(row)
    session.flush()
    version = key_version_id
    if version is None and has_api_key_snapshot():
        version = current_key_version()
    elif version is None:
        owner = session.get(User, owner_id)
        version = owner.api_key_version if owner else None
    session.add(EventOwner(event_id=row.id, user_id=owner_id, key_version_id=version))
    return row
