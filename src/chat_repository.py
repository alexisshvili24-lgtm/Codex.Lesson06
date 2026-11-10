"""Хранение бесед и их снимков."""
import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select, update
from src.database import ChatConversation, ChatTurn, Event, Session


class ConversationMissing(LookupError):
    pass


class ConversationChanged(Exception):
    pass


def _metadata(row):
    return {'id': row.id, 'title': row.title, 'updated_at': row.updated_at}


def create():
    with Session.begin() as session:
        row = ChatConversation(id=str(uuid4()), title='Новая беседа',
                               updated_at=datetime.now(timezone.utc).isoformat(), summary='', turn_count=0)
        session.add(row)
        return _metadata(row)


def list_conversations():
    with Session() as session:
        rows = session.scalars(select(ChatConversation)
                               .order_by(ChatConversation.updated_at.desc(), ChatConversation.id)).all()
        return [_metadata(row) for row in rows]


def _conversation(session, conversation_id):
    row = session.get(ChatConversation, conversation_id)
    if row is None:
        raise ConversationMissing('Беседа не найдена.')
    return row


def _messages(conversation_id):
    return (select(Event.payload).join(ChatTurn, ChatTurn.event_id == Event.id)
            .where(ChatTurn.conversation_id == conversation_id))


def history(conversation_id):
    with Session() as session:
        row = _conversation(session, conversation_id)
        rows = session.scalars(_messages(conversation_id).order_by(ChatTurn.position)).all()
        return {**_metadata(row), 'messages': [json.loads(payload) for payload in rows]}


def context(conversation_id):
    with Session() as session:
        row = _conversation(session, conversation_id)
        payload = session.scalar(_messages(conversation_id).where(ChatTurn.position == row.turn_count))
        previous = None
        if payload:
            data = json.loads(payload)
            previous = {'question': data['question'], 'answer': data['answer']['answer']}
        return row.turn_count, row.summary, previous


def append(conversation_id, turn_count, summary, model, output):
    now = datetime.now(timezone.utc).isoformat()
    values = {'turn_count': turn_count + 1, 'summary': summary, 'updated_at': now}
    if turn_count == 0:
        values['title'] = ' '.join(output['question'].split())[:100]
    with Session.begin() as session:
        result = session.execute(update(ChatConversation)
                                 .where(ChatConversation.id == conversation_id,
                                        ChatConversation.turn_count == turn_count).values(**values))
        if result.rowcount != 1:
            raise ConversationChanged('Беседа уже обновилась. Откройте её снова и повторите вопрос.')
        event = Event(request_id=output['request_id'], created_at=now, operation='rag',
                      status='ok', model=model, payload=json.dumps(output, ensure_ascii=False))
        session.add(event)
        session.flush()
        session.add(ChatTurn(conversation_id=conversation_id, position=turn_count + 1, event_id=event.id))
