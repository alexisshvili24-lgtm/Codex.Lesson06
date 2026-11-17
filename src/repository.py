import json
from decimal import Decimal
from sqlalchemy import select
from src.database import Session, Setting, Event, EventOwner, UserSetting, ChatTurn
from src.request_context import current_user_id
from src.event_store import add_event

_PERSONAL_SETTINGS = {'system_prompt', 'vector_enabled', 'vector_threshold', 'bm25_enabled', 'bm25_threshold'}

class Repository:
    def settings(self, user_id=None):
        owner_id = user_id if user_id is not None else current_user_id()
        with Session() as s:
            shared = {row.name: row.value for row in s.scalars(select(Setting)).all()
                      if row.name not in _PERSONAL_SETTINGS}
            personal = {row.name: row.value for row in s.scalars(
                select(UserSetting).where(UserSetting.user_id == owner_id)).all()}
            return shared | personal

    def save_settings(self, values, user_id=None):
        owner_id = user_id if user_id is not None else current_user_id()
        with Session.begin() as s:
            for name, value in values.items():
                if name in _PERSONAL_SETTINGS:
                    row = s.get(UserSetting, (owner_id, name))
                    if row is None:
                        s.add(UserSetting(user_id=owner_id, name=name, value=str(value)))
                    else:
                        row.value = str(value)
                    continue
                row = s.get(Setting, name)
                if row is None:
                    s.add(Setting(name=name, value=str(value)))
                else:
                    row.value = str(value)

    def log(self, request_id, operation, status, model='', duration_ms=0, cost=None, payload=None,
            user_id=None, key_version_id=None):
        owner_id = user_id if user_id is not None else current_user_id()
        with Session.begin() as s:
            add_event(s, request_id, operation, status, model, duration_ms, cost, payload,
                      user_id=owner_id, key_version_id=key_version_id)

    def events(self, user_id=None):
        owner_id = user_id if user_id is not None else current_user_id()
        with Session() as s:
            rows = s.scalars(select(Event).join(EventOwner).where(EventOwner.user_id == owner_id)
                             .order_by(Event.id.desc()).limit(200)).all()
            return [{key: getattr(row, key) for key in ('id','request_id','created_at','operation','status','model','duration_ms','cost_rub','payload')} for row in rows]

    def chat_history(self, limit=50, offset=0, user_id=None):
        owner_id = user_id if user_id is not None else current_user_id()
        with Session() as session:
            rows = session.scalars(select(Event).where(Event.operation == 'rag', Event.status == 'ok',
                                                       Event.id.in_(select(EventOwner.event_id).where(EventOwner.user_id == owner_id)),
                                                       ~select(ChatTurn.event_id).where(ChatTurn.event_id == Event.id).exists())
                                   .order_by(Event.id.desc()).offset(offset).limit(limit)).all()
            return [json.loads(row.payload) for row in reversed(rows)]

    def costs(self, user_id=None):
        owner_id = user_id if user_id is not None else current_user_id()
        with Session() as s:
            rows = s.scalars(select(Event).join(EventOwner).where(
                EventOwner.user_id == owner_id, Event.operation.in_(['embedding', 'generation']),
                Event.status != 'not_sent')).all()
            totals = {'embedding': Decimal(0), 'generation': Decimal(0)}
            unknown = 0
            for row in rows:
                if row.cost_rub is None:
                    unknown += 1
                else:
                    totals[row.operation] += Decimal(row.cost_rub)
            return {'embedding': str(totals['embedding']), 'generation': str(totals['generation']),
                    'total': str(sum(totals.values())), 'calls': len(rows), 'unknown': unknown}

    def costs_by_key_version(self, user_id=None):
        owner_id = user_id if user_id is not None else current_user_id()
        with Session() as session:
            rows = session.execute(select(Event, EventOwner.key_version_id).join(EventOwner).where(
                EventOwner.user_id == owner_id, Event.operation.in_(['embedding', 'generation']),
                Event.status != 'not_sent').order_by(Event.id)).all()
        groups = {}
        for event, key_version_id in rows:
            key_version_id = key_version_id or None
            group = groups.setdefault(key_version_id, {
                'key_version_id': key_version_id,
                'key_version_known': key_version_id is not None,
                'embedding': Decimal(0),
                'generation': Decimal(0),
                'calls': 0,
                'unknown': 0,
                'first_seen': event.created_at,
                'last_seen': event.created_at,
            })
            group['calls'] += 1
            group['first_seen'] = min(group['first_seen'], event.created_at)
            group['last_seen'] = max(group['last_seen'], event.created_at)
            if event.cost_rub is None:
                group['unknown'] += 1
            else:
                group[event.operation] += Decimal(event.cost_rub)
        result = []
        for group in groups.values():
            group['total'] = str(group['embedding'] + group['generation'])
            group['embedding'] = str(group['embedding'])
            group['generation'] = str(group['generation'])
            result.append(group)
        return sorted(result, key=lambda group: (group['last_seen'], group['key_version_id'] or ''), reverse=True)

    def embedding_group_cost(self, group_id, user_id=None):
        owner_id = user_id if user_id is not None else current_user_id()
        with Session() as session:
            rows = session.scalars(select(Event).join(EventOwner).where(
                EventOwner.user_id == owner_id, Event.operation == 'embedding', Event.status != 'not_sent')).all()
            relevant = [row for row in rows if json.loads(row.payload).get('group_id') == group_id]
            total = sum((Decimal(row.cost_rub) for row in relevant if row.cost_rub is not None), Decimal(0))
            return {'cost_rub':str(total), 'unknown':sum(row.cost_rub is None for row in relevant), 'calls':len(relevant)}

    def last_index_job(self, user_id=None):
        owner_id = user_id if user_id is not None else current_user_id()
        with Session() as session:
            row = session.scalars(select(Event).join(EventOwner).where(
                EventOwner.user_id == owner_id, Event.operation == 'index_job')
                .order_by(Event.id.desc()).limit(1)).first()
            if row is None:
                return None
            return {'status':row.status, 'request_id':row.request_id, 'payload':json.loads(row.payload)}
