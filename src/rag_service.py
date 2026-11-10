"""Оркестрация ответа и сохранение исторического снимка поиска."""
import uuid
from src.search_service import search_documents
from src.rag_answer import generate_answer
from src import chat_repository
from src.chat_context import update_context
from src.service import settings, repo


def answer_question(question, *, conversation_id=None):
    question = question.strip()
    if not question:
        raise ValueError('Введите вопрос.')
    request_id = str(uuid.uuid4())
    config = settings()
    output = {'request_id':request_id, 'question':question}
    if conversation_id is not None:
        output['conversation_id'] = conversation_id
    try:
        summary, previous = '', None
        if conversation_id is not None:
            turn_count, summary, previous = chat_repository.context(conversation_id)
        context = update_context(summary, previous, question, config, group_id=request_id)
        query = question
        if previous is not None:
            summary = context.summary or summary
            query = context.search_query
            output['search_query'] = query
        groups = context.search_groups
        if len(groups) == 1:
            groups = [[query, groups[0][1]]]
        output['search_groups'] = groups
        output['evidence_types'] = context.evidence_types
        diagnostics = search_documents(
            query, search_groups=groups, evidence_types=context.evidence_types,
            context_query=context.context_query if previous is not None else '',
            config=config, group_id=request_id,
        )
        sources = []
        for index, item in enumerate(diagnostics['rrf'], 1):
            source = {'id': f'S{index}', **item['payload']}
            if 'retrieval_role' in item:
                source['retrieval_role'] = item['retrieval_role']
            sources.append(source)
        output.update(sources=sources, diagnostics=diagnostics)
        answer_options = {'group_id': request_id}
        if query != question:
            answer_options['search_query'] = query
        result = generate_answer(question, sources, config, **answer_options)
        output['answer'] = result.model_dump()
        if conversation_id is None:
            repo.log(request_id, 'rag', 'ok', config['generation_model'], payload=output)
        else:
            chat_repository.append(conversation_id, turn_count, summary, config['generation_model'], output)
        return output
    except Exception as exc:
        repo.log(request_id, 'rag', 'error', config['generation_model'], payload={**output, 'error':str(exc)})
        raise
