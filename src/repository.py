import json
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import select
from src.database import Session, Setting, Event, ChatTurn

class Repository:
    def settings(self):
        with Session() as s:
            return {row.name: row.value for row in s.scalars(select(Setting)).all()}

    def save_settings(self, values):
        with Session.begin() as s:
            for name, value in values.items():
                row = s.get(Setting, name)
                if row is None:
                    s.add(Setting(name=name, value=str(value)))
                else:
                    row.value = str(value)

    def log(self, request_id, operation, status, model='', duration_ms=0, cost=None, payload=None):
        with Session.begin() as s:
            s.add(Event(request_id=request_id, created_at=datetime.now(timezone.utc).isoformat(), operation=operation,
                        status=status, model=model, duration_ms=duration_ms, cost_rub=str(cost) if cost is not None else None,
                        payload=json.dumps(payload or {}, ensure_ascii=False, default=str)))

    def events(self):
        with Session() as s:
            rows = s.scalars(select(Event).order_by(Event.id.desc()).limit(200)).all()
            return [{key: getattr(row, key) for key in ('id','request_id','created_at','operation','status','model','duration_ms','cost_rub','payload')} for row in rows]

    def chat_history(self, limit=50, offset=0):
        with Session() as session:
            rows = session.scalars(select(Event).where(Event.operation == 'rag', Event.status == 'ok',
                                                       ~select(ChatTurn.event_id).where(ChatTurn.event_id == Event.id).exists())
                                   .order_by(Event.id.desc()).offset(offset).limit(limit)).all()
            return [json.loads(row.payload) for row in reversed(rows)]

    def costs(self):
        with Session() as s:
            rows = s.scalars(select(Event).where(Event.operation.in_(['embedding', 'generation']), Event.status != 'not_sent')).all()
            totals = {'embedding': Decimal(0), 'generation': Decimal(0)}
            unknown = 0
            for row in rows:
                if row.cost_rub is None:
                    unknown += 1
                else:
                    totals[row.operation] += Decimal(row.cost_rub)
            return {'embedding': str(totals['embedding']), 'generation': str(totals['generation']),
                    'total': str(sum(totals.values())), 'calls': len(rows), 'unknown': unknown}
    def embedding_group_cost(self, group_id):
        with Session() as session:
            rows = session.scalars(select(Event).where(Event.operation == 'embedding', Event.status != 'not_sent')).all()
            relevant = [row for row in rows if json.loads(row.payload).get('group_id') == group_id]
            total = sum((Decimal(row.cost_rub) for row in relevant if row.cost_rub is not None), Decimal(0))
            return {'cost_rub':str(total), 'unknown':sum(row.cost_rub is None for row in relevant), 'calls':len(relevant)}

    def last_index_job(self):
        with Session() as session:
            row = session.scalars(select(Event).where(Event.operation == 'index_job').order_by(Event.id.desc()).limit(1)).first()
            if row is None:
                return None
            return {'status':row.status, 'request_id':row.request_id, 'payload':json.loads(row.payload)}
