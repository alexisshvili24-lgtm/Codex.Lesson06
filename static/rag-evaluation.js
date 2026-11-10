const evaluationGroups = [
  ['direct', 'Ответ прямо в базе'],
  ['combined', 'Ответ из нескольких фрагментов'],
  ['absent', 'Ответа в базе нет']
];

function evaluationElement(tag, text) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  return element;
}

function renderEvaluationCase(test) {
  const card = evaluationElement('article');
  card.className = 'document-row evaluation-case';
  const title = evaluationElement('h3', test.id);
  const question = evaluationElement('p', test.question);
  const actions = evaluationElement('div');
  actions.className = 'actions';
  const status = evaluationElement('span');
  status.setAttribute('role', 'status');
  const copy = evaluationElement('button', 'Копировать вопрос');
  copy.type = 'button';
  copy.setAttribute('aria-label', 'Копировать вопрос ' + test.id);
  copy.addEventListener('click', async () => {
    status.textContent = '';
    try {
      await navigator.clipboard.writeText(test.question);
      status.textContent = 'Вопрос скопирован.';
    } catch {
      const range = document.createRange();
      range.selectNodeContents(question);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      status.textContent = 'Вопрос выделен. Скопируйте его через Ctrl+C.';
    }
  });
  actions.append(copy, status);

  const details = evaluationElement('details');
  details.append(evaluationElement('summary', 'Эталон и критерии'), evaluationElement('p', test.answer));
  const criteria = evaluationElement('ul');
  for (const criterion of test.criteria) criteria.append(evaluationElement('li', criterion));
  details.append(evaluationElement('h4', 'Что проверить в ответе'), criteria);
  if (test.sources.length) {
    const sources = evaluationElement('ul');
    const sourceStatus = evaluationElement('p');
    sourceStatus.setAttribute('role', 'status');
    for (const source of test.sources) {
      const file = source.file.split('/').pop();
      const label = [source.document, file, source.section, 'чанк №' + (source.position + 1)]
        .filter(Boolean).join(' · ');
      const link = evaluationElement('a', label);
      link.href = '#knowledge';
      link.addEventListener('click', async event => {
        event.preventDefault();
        sourceStatus.textContent = '';
        try {
          await showChunks(source.document_id, source.position, source.chunk_id);
        } catch (error) {
          sourceStatus.textContent = 'Не удалось открыть источник. ' + error.message;
        }
      });
      const item = evaluationElement('li');
      item.append(link);
      sources.append(item);
    }
    details.append(evaluationElement('h4', 'Подтверждающие чанки'), sources, sourceStatus);
  }
  card.append(title, question, actions, details);
  return card;
}

async function loadEvaluation() {
  const status = document.querySelector('#evaluation-status');
  try {
    const response = await fetch('/static/rag-evaluation.json', {cache: 'no-cache'});
    if (!response.ok) throw new Error('HTTP ' + response.status);
    const data = await response.json();
    const target = document.querySelector('#evaluation-cases');
    for (const [category, label] of evaluationGroups) {
      const tests = data.cases.filter(test => test.category === category);
      const group = evaluationElement('section');
      group.className = 'panel section-panel evaluation-group';
      group.append(evaluationElement('h2', label + ' · ' + tests.length));
      for (const test of tests) group.append(renderEvaluationCase(test));
      target.append(group);
    }
    const corpus = data.corpus.documents.map(doc => doc.title + ' (' + doc.chunks + ' чанков)').join(' и ');
    status.textContent = data.cases.length + ' вопросов по снимку индекса ' + corpus + '.';
  } catch (error) {
    status.textContent = 'Не удалось загрузить вопросы. Обновите страницу.';
    console.error('Ошибка загрузки эталонных вопросов RAG', error);
  }
}

loadEvaluation();
