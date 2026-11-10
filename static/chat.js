const chatForm = document.querySelector('#chat-form');
const chatQuestion = document.querySelector('#chat-question');
const chatStatus = document.querySelector('#chat-status');
const chatMessages = document.querySelector('#chat-messages');
const chatSubmit = document.querySelector('#chat-submit');
const chatNew = document.querySelector('#chat-new');
const chatArchive = document.querySelector('#chat-archive');
const chatMore = document.querySelector('#chat-more');
const chatTitle = document.querySelector('#chat-conversation-title');
const chatEmpty = document.querySelector('#chat-empty');
const chatConversations = document.querySelector('#chat-conversations');
const chatReferences = document.querySelector('#chat-references');
const chatReferenceItems = document.querySelector('#chat-reference-items');

let selectedConversation = null;
let archiveOffset = 0;
let chatBusy = false;

function chatElement(tag, text) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  return element;
}

function chatQuestionBubble(question) {
  const bubble = chatElement('p', question);
  bubble.className = 'chat-bubble chat-bubble-user';
  return bubble;
}

function renderChatTurn(data) {
  const article = chatElement('article');
  article.className = 'chat-message';
  const reply = chatElement('div');
  reply.className = 'chat-bubble chat-bubble-assistant';
  article.append(chatQuestionBubble(data.question), reply);
  const response = chatElement('p');
  response.className = 'chat-answer';
  const sources = new Map(data.sources.map(source => [source.id, source]));
  for (const part of data.answer.answer.split(/(\[S\d+\])/g)) {
    const match = /^\[(S\d+)\]$/.exec(part);
    if (!match || !sources.has(match[1])) { response.append(document.createTextNode(part)); continue; }
    const link = chatElement('button', part);
    link.type = 'button';
    link.className = 'source-link';
    link.setAttribute('aria-label', 'Открыть источник ' + match[1]);
    link.addEventListener('click', () => openChatSource(sources.get(match[1])));
    response.append(link);
  }
  reply.append(response);
  const statuses = {full:'Полный ответ', partial:'Частичный ответ', no_answer:'Ответ не найден'};
  const status = chatElement('p', statuses[data.answer.status] || data.answer.status);
  status.className = 'chat-answer-status';
  reply.append(status);
  if (data.answer.missing_information.length) reply.append(chatElement('p', 'Недостающая информация: ' + data.answer.missing_information.join('; ')));
  const reference = chatElement('section');
  reference.className = 'chat-reference-turn';
  reference.append(chatElement('h3', data.question));
  const sourceList = chatElement('ul');
  for (const source of data.sources) {
    const item = chatElement('li');
    const role = source.retrieval_role === 'context' ? 'Дополнительный контекст' : '';
    const button = chatElement('button', [source.id, source.document_title, source.source_file, role].filter(Boolean).join(' · '));
    button.type = 'button';
    button.className = 'source-link';
    button.addEventListener('click', () => openChatSource(source));
    item.append(button);
    sourceList.append(item);
  }
  if (sourceList.children.length) reference.append(sourceList);
  else reference.append(chatElement('p', 'Источники не найдены.'));
  const diagnostics = chatElement('div');
  diagnostics.append(chatElement('h4', 'Диагностика поиска'));
  if (data.search_query && data.search_query !== data.question) {
    diagnostics.append(chatElement('p', 'Основной запрос — ' + data.search_query));
  }
  appendSearchDiagnostics(diagnostics, data.diagnostics);
  if (data.diagnostics.context) {
    diagnostics.append(chatElement('h4', 'Дополнительный поиск по контексту'));
    diagnostics.append(chatElement('p', data.diagnostics.context.query));
    appendSearchDiagnostics(diagnostics, data.diagnostics.context);
  }
  reference.append(diagnostics);
  return {article, reference};
}

function appendSearchDiagnostics(target, results) {
  for (const [key, title] of [['vector','Vector'],['bm25','BM25'],['rrf','RRF']]) {
    target.append(chatElement('h5', title));
    const list = chatElement('ol');
    const items = key === 'rrf' ? (results.rrf_candidates || results.rrf) : results[key];
    for (const item of items) {
      const positions = key === 'rrf' ? ' · Vector: ' + (item.vector_position ?? '—') + ' · BM25: ' + (item.bm25_position ?? '—') : ' · ' + (item.accepted ? 'принят' : 'отклонён') + ' · порог: ' + (item.threshold ?? 'выключен');
      const reasons = {threshold_disabled:'порог выключен', meets_threshold:'оценка не ниже порога', below_threshold:'оценка ниже порога'};
      const reason = reasons[item.reason] ? ' · ' + reasons[item.reason] : '';
      const row = chatElement('li', item.chunk_id + ' · score: ' + item.score + positions + reason + (key === 'rrf' ? (item.included === false ? ' · не вошёл в контекст' : ' · включён в контекст') : ''));
      if (item.payload) {
        const view = chatElement('button', 'Открыть фрагмент');
        view.type = 'button'; view.className = 'source-link';
        view.addEventListener('click', () => openChatSource({id:item.chunk_id, ...item.payload}));
        row.append(' ', view);
      }
      list.append(row);
    }
    target.append(list);
  }
}

function openChatSource(source) {
  const dialog = chatElement('dialog');
  dialog.className = 'source-dialog';
  const heading = chatElement('h2', source.id + ' · ' + source.document_title);
  const meta = chatElement('p', [source.source_type, source.language, source.document_version, source.source_file, source.chapter, source.section, source.subsection, source.source_url].filter(Boolean).join(' · '));
  const content = chatElement('pre', source.text);
  content.className = 'document-text';
  const close = chatElement('button', 'Закрыть');
  close.type = 'button';
  close.addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => dialog.remove(), {once:true});
  dialog.append(heading, meta, content, close);
  document.body.append(dialog);
  dialog.showModal();
  close.focus();
}


async function chatRequest(path, options) {
  const response = await fetch('/api/chat' + path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Запрос не выполнен.');
  return data;
}

function setChatBusy(value) {
  chatBusy = value;
  for (const control of [chatNew, chatArchive, chatMore, chatSubmit, ...chatConversations.children]) {
    control.disabled = value;
  }
}

function showTurns(messages, older = false) {
  const turns = messages.map(renderChatTurn);
  const method = older ? 'prepend' : 'append';
  const previousHeight = chatMessages.scrollHeight;
  chatMessages[method](...turns.map(turn => turn.article));
  chatReferenceItems[method](...turns.map(turn => turn.reference));
  chatEmpty.hidden = chatMessages.children.length > 0;
  chatReferences.hidden = chatReferenceItems.children.length === 0;
  chatMessages.scrollTop = older ? chatMessages.scrollHeight - previousHeight : chatMessages.scrollHeight;
}

function setChatTitle(title) {
  chatTitle.textContent = title;
  chatTitle.title = title;
}

function resetChat(title, archived) {
  setChatTitle(title);
  chatEmpty.textContent = archived ? 'В архиве пока нет вопросов.' : 'Задайте вопрос о Git, чтобы начать беседу.';
  chatEmpty.hidden = false;
  chatForm.hidden = archived;
  chatQuestion.value = '';
  chatMessages.replaceChildren();
  chatReferenceItems.replaceChildren();
  chatReferences.open = false;
  chatReferences.hidden = true;
  chatMore.hidden = true;
  chatStatus.textContent = '';
}

function markConversation() {
  for (const button of [...chatConversations.children, chatArchive]) {
    const active = button.dataset.conversation === selectedConversation;
    if (active) button.setAttribute('aria-current', 'true');
    else button.removeAttribute('aria-current');
  }
}

async function refreshConversations() {
  const data = await chatRequest('/conversations');
  chatConversations.replaceChildren();
  for (const conversation of data.conversations) {
    const button = chatElement('button');
    const name = chatElement('span', conversation.title);
    name.className = 'conversation-name';
    button.append(name);
    button.title = conversation.title;
    button.type = 'button';
    button.className = 'conversation-option';
    button.dataset.conversation = conversation.id;
    button.disabled = chatBusy;
    button.addEventListener('click', () => openConversation(conversation.id));
    chatConversations.append(button);
  }
  markConversation();
  return data.conversations;
}

async function openConversation(id) {
  if (chatBusy) return;
  setChatBusy(true);
  try {
    const archived = id === 'archive';
    const data = await chatRequest(archived ? '/history' : '/conversations/' + id);
    selectedConversation = id;
    resetChat(archived ? 'Архив вопросов' : data.title, archived);
    archiveOffset = archived ? data.messages.length : 0;
    chatMore.hidden = !data.has_more;
    showTurns(data.messages);
    markConversation();
  } catch (error) {
    chatStatus.textContent = error.message;
  } finally {
    setChatBusy(false);
  }
}

chatNew.addEventListener('click', () => {
  selectedConversation = null;
  resetChat('Новая беседа', false);
  markConversation();
  chatQuestion.focus();
});

chatArchive.dataset.conversation = 'archive';
chatArchive.addEventListener('click', () => openConversation('archive'));

chatMore.addEventListener('click', async () => {
  if (chatBusy || selectedConversation !== 'archive') return;
  setChatBusy(true);
  try {
    const data = await chatRequest('/history?offset=' + archiveOffset);
    archiveOffset += data.messages.length;
    chatMore.hidden = !data.has_more;
    showTurns(data.messages, true);
  } catch (error) {
    chatStatus.textContent = error.message;
  } finally {
    setChatBusy(false);
  }
});

chatForm.addEventListener('submit', async event => {
  event.preventDefault();
  if (chatBusy || selectedConversation === 'archive') return;
  const question = chatQuestion.value.trim();
  if (!question) { chatStatus.textContent = 'Введите вопрос.'; return; }
  setChatBusy(true);
  chatQuestion.readOnly = true;
  const pending = chatElement('article');
  pending.className = 'chat-message';
  pending.append(chatQuestionBubble(question));
  chatMessages.append(pending);
  chatEmpty.hidden = true;
  chatMessages.scrollTop = chatMessages.scrollHeight;
  chatStatus.textContent = 'Ищу источники и готовлю ответ…';
  try {
    if (!selectedConversation) {
      const conversation = await chatRequest('/conversations', {method:'POST'});
      selectedConversation = conversation.id;
    }
    const data = await chatRequest('', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({question, conversation_id:selectedConversation})
    });
    pending.remove();
    showTurns([data]);
    chatQuestion.value = '';
    chatStatus.textContent = 'Ответ получен.';
    if (chatMessages.children.length === 1) {
      setChatTitle([...question.replace(/\s+/gu, ' ')].slice(0, 100).join(''));
    }
    try {
      await refreshConversations();
    } catch {
      chatStatus.textContent = 'Ответ сохранён. Не удалось обновить список бесед.';
    }
  } catch (error) {
    chatStatus.textContent = error.message;
  } finally {
    pending.remove();
    chatEmpty.hidden = chatMessages.children.length > 0;
    chatQuestion.readOnly = false;
    setChatBusy(false);
    if (chatQuestion.getClientRects().length) chatQuestion.focus({preventScroll:true});
  }
});

async function loadChat() {
  setChatBusy(true);
  let conversations;
  try {
    conversations = await refreshConversations();
  } catch (error) {
    chatStatus.textContent = error.message;
  } finally {
    setChatBusy(false);
  }
  if (conversations?.length) await openConversation(conversations[0].id);
}

loadChat();
