"""Сценарии раздельных бесед и обновления их резюме."""
import json
import unittest
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from app import ChatQuestion, chat_answer, chat_history, create_chat_conversation, get_chat_conversation
from src import chat_repository
from src.database import ROOT, engine
from src.rag_answer import Answer


class ChatConversationsTest(unittest.TestCase):
    def test_turns_keep_context_in_one_conversation_and_archive_old_questions(self):
        assert '.tmp' in str(engine.url), 'Тестовая БД должна быть изолирована'
        config = Config()
        config.set_main_option('script_location', str(ROOT / 'migrations'))
        command.upgrade(config, 'head')
        contexts = []

        def router_response(base_url, key, path, body):
            self.assertTrue(body['response_format']['json_schema']['strict'])
            payload = json.loads(body['messages'][1]['content'])
            contexts.append(payload)
            if payload['last_turn'] is None:
                question = payload['question']
                prepared = {'summary': '', 'search_query': question, 'context_query': '',
                            'search_groups': [[question, 'Как сделать это в Git?']], 'evidence_types': ['command']}
                return {'choices': [{'message': {'content': json.dumps(prepared)}}]}, 'context-test'
            summary = 'Ветка уже опубликована. Уточняем отмену коммита. '
            length = 6800 if not payload['summary'] else 12500
            prepared = {'summary': (summary + 'Подробности беседы. ' * 700)[:length],
                        'search_query': 'Как отменить коммит в опубликованной ветке Git?',
                        'context_query': 'Как работать с опубликованными ветками Git?',
                        'search_groups': [['Как отменить коммит в опубликованной ветке Git?',
                                           'Git undo a commit on a published branch']], 'evidence_types': ['command']}
            return {'choices': [{'message': {'content': json.dumps(prepared)}}]}, 'context-test'

        with (
            patch('src.rag_service.search_documents', return_value={'rrf': [], 'vector': [], 'bm25': []}) as search,
            patch('src.rag_service.generate_answer', return_value=Answer(
                status='no_answer', answer='Предыдущий ответ', source_ids=[], missing_information=[])) as generate,
            patch('src.rag_answer.api_key', return_value='test-key'),
            patch('src.rag_answer.routerai.request_json', side_effect=router_response),
            patch('src.rag_answer.routerai.cost', return_value=(None, None)),
        ):
            def ask(question, conversation_id=None):
                return chat_answer(ChatQuestion(question=question, conversation_id=conversation_id))

            old = ask('Старый независимый вопрос')
            first = create_chat_conversation()['id']
            second = create_chat_conversation()['id']
            initial = ask('Как отменить коммит? Ветка уже опубликована.', first)
            self.assertEqual(len(contexts), 2)
            self.assertTrue(all(context['last_turn'] is None for context in contexts))
            follow_up = ask('А если его уже забрали коллеги?', first)
            self.assertEqual(contexts[2]['last_turn']['question'], initial['question'])
            self.assertEqual(contexts[2]['summary'], '')
            self.assertEqual(search.call_args.args[0], follow_up['search_query'])
            self.assertEqual(follow_up['question'], 'А если его уже забрали коллеги?')
            self.assertEqual(search.call_args.kwargs['context_query'], 'Как работать с опубликованными ветками Git?')
            self.assertEqual(generate.call_args.args[0], follow_up['question'])
            self.assertEqual(generate.call_args.kwargs['search_query'], follow_up['search_query'])

            ask('Как создать тег?', second)
            self.assertEqual(len(contexts), 4)
            self.assertEqual(search.call_args.args[0], 'Как создать тег?')

            ask('А если правки ещё нужны?', first)
            self.assertIn('Ветка уже опубликована', contexts[4]['summary'])
            self.assertEqual(len(contexts[4]['summary']), 6800)
            _, saved_summary, _ = chat_repository.context(first)
            self.assertTrue(saved_summary.startswith('Ветка уже опубликована'))
            self.assertLessEqual(len(saved_summary), 12000)
            self.assertTrue(saved_summary.endswith('беседы.') or saved_summary.endswith('Подробности'))
            self.assertEqual(contexts[4]['last_turn']['question'], follow_up['question'])

            history = get_chat_conversation(first)
            self.assertEqual(history['title'], initial['question'])
            self.assertEqual(len(history['messages']), 3)
            self.assertEqual(len(get_chat_conversation(second)['messages']), 1)
            self.assertIn(old['request_id'], {item['request_id'] for item in chat_history(offset=0)['messages']})
            self.assertNotIn(initial['request_id'], {item['request_id'] for item in chat_history(offset=0)['messages']})

            with self.assertRaises(chat_repository.ConversationChanged):
                chat_repository.append(first, 0, 'Устаревшее резюме', 'test', initial)
            self.assertEqual(len(get_chat_conversation(first)['messages']), 3)
