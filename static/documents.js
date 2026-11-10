const documentForm = document.querySelector('#document-form');
const documentMessage = document.querySelector('#document-message');
const documentList = document.querySelector('#document-list');
let replacingDocument = null;
function updateDocumentFieldValidity(field) {
  if (!field.willValidate) return;
  if (field.validity.valid) field.removeAttribute('aria-invalid');
  else field.setAttribute('aria-invalid', 'true');
}
documentForm.addEventListener('invalid', event => {
  updateDocumentFieldValidity(event.target);
  documentMessage.textContent = 'Проверьте выделенные поля: обязательные поля отмечены звёздочкой.';
}, true);
for (const eventName of ['input', 'change']) documentForm.addEventListener(eventName, event => {
  if (event.target.matches('[name=title], [name=language]')) event.target.setCustomValidity('');
  if (event.target.hasAttribute('aria-invalid')) updateDocumentFieldValidity(event.target);
});
async function documentApi(url, options) {
  const response = await fetch(url, options);
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Проверьте поля документа.');
  return result;
}
function resetDocumentForm() {
  replacingDocument = null;
  documentForm.reset();
  for (const field of documentForm.querySelectorAll('[aria-invalid]')) field.removeAttribute('aria-invalid');
  for (const name of ['title', 'language']) documentForm.elements[name].setCustomValidity('');
  document.querySelector('#document-form-title').textContent = 'Добавить документ';
  document.querySelector('#document-submit').textContent = 'Загрузить';
  document.querySelector('#cancel-replace').hidden = true;
}
function documentButton(label, handler) {
  const button = document.createElement('button');
  button.type = 'button'; button.textContent = label; button.addEventListener('click', handler);
  return button;
}
async function showDocument(id) {
  try {
    const item = await documentApi('/api/documents/' + encodeURIComponent(id));
    document.querySelector('#detail-title').textContent = item.title;
    const metadata = [
      ['ID', item.id], ['Источник', item.source_type === 'official' ? 'Официальный' : 'Сторонний'],
      ['Язык', item.language], ['Версия', item.version || 'не указана'], ['Дата публикации', item.published_at || 'не указана'],
      ['URL', item.source_url || 'не указан'], ['Git-коммит', item.git_commit || 'не указан'], ['Файл', item.filename],
      ['SHA-256', item.sha256], ['Загружен', item.uploaded_at], ['Статус', 'Текст извлечён'], ['Чанков', item.chunk_count]
    ];
    const meta = document.querySelector('#detail-meta'); meta.replaceChildren();
    for (const [label, value] of metadata) { const row = document.createElement('div'); row.textContent = `${label}: ${value}`; meta.append(row); }
    document.querySelector('#detail-text').textContent = item.extracted_text;
    document.querySelector('#document-detail').hidden = false;
    document.querySelector('#document-detail').scrollIntoView({block:'start'});
  } catch (error) { documentMessage.textContent = error.message; }
}
let currentChunkDocument = null;
let currentChunkOffset = 0;
async function showChunks(id, offset, expectedId) {
  try {
    const data = await documentApi(`/api/documents/${encodeURIComponent(id)}/chunks?offset=${offset}&limit=20`);
    if (expectedId && data.chunks[0]?.chunk_id !== expectedId) {
      throw new Error('Чанк из эталонного набора больше не совпадает с текущей версией документа.');
    }
    if (expectedId) location.hash = 'knowledge';
    currentChunkDocument=id; currentChunkOffset=offset;
    const panel=document.querySelector('#chunk-panel'); panel.hidden=false;
    const summary=document.querySelector('#chunk-summary');
    summary.textContent=data.count ? `Всего: ${data.count}; токены — минимум ${data.statistics.min}, среднее ${data.statistics.mean}, максимум ${data.statistics.max}. Показаны ${offset+1}–${offset+data.chunks.length}.` : 'Чанки ещё не подготовлены.';
    const warnings=document.querySelector('#chunk-warnings'); warnings.replaceChildren();
    for (const message of data.warnings) { const p=document.createElement('p'); p.textContent='Внимание: '+message; warnings.append(p); }
    const list=document.querySelector('#chunk-list'); list.replaceChildren();
    for (const [index, chunk] of data.chunks.entries()) {
      const item=document.createElement('details'); const heading=document.createElement('summary');
      heading.textContent=`${offset+index+1}. ${chunk.source_file} · ${chunk.section || 'Без раздела'} · ${chunk.tokens} токенов`;
      const info=document.createElement('p'); info.textContent=`ID: ${chunk.chunk_id} · SHA-256: ${chunk.text_hash} · Источник: ${chunk.source_url || 'не указан'}`;
      const text=document.createElement('pre'); text.className='document-text'; text.textContent=chunk.text;
      item.open = chunk.chunk_id === expectedId;
      item.append(heading,info,text); list.append(item);
    }
    document.querySelector('#chunk-prev').disabled=offset===0;
    document.querySelector('#chunk-next').disabled=offset+data.chunks.length>=data.count;
    if (expectedId) list.querySelector('summary')?.focus();
    panel.scrollIntoView({block:'start'});
  } catch(error) {
    if (expectedId) throw error;
    documentMessage.textContent=error.message;
  }
}
document.querySelector('#chunk-prev').addEventListener('click',()=>showChunks(currentChunkDocument,Math.max(0,currentChunkOffset-20)));
document.querySelector('#chunk-next').addEventListener('click',()=>showChunks(currentChunkDocument,currentChunkOffset+20));

async function loadDocuments() {
  const items = await documentApi('/api/documents');
  documentList.replaceChildren();
  document.querySelector('#document-empty').hidden = items.length > 0;
  for (const item of items) {
    const row = document.createElement('article'); row.className = 'document-row';
    const title = document.createElement('h3'); title.textContent = item.title;
    const description = document.createElement('p'); description.textContent = `${item.filename} · ${item.language} · ${item.index_count ? `в индексе: ${item.index_count} чанков` : 'не проиндексирован'}`;
    const actions = document.createElement('div'); actions.className = 'actions';
    const view = documentButton('Просмотр', () => showDocument(item.id));
    const chunks = documentButton('Чанки', () => showChunks(item.id, 0));
    const prepare = documentButton('Подготовить и индексировать', async () => {
      prepare.disabled = true; documentMessage.textContent = 'Подготовка документа…';
      try {
        await documentApi('/api/documents/' + encodeURIComponent(item.id) + '/prepare-and-index', {method:'POST'});
        await pollIndex();
      } catch (error) { documentMessage.textContent = error.message; }
      finally { prepare.disabled = false; }
    });
    const replace = documentButton('Заменить', () => {
      replacingDocument = item.id;
      for (const name of ['title','source_type','language','version','published_at','source_url','git_commit']) documentForm.elements[name].value = item[name];
      documentForm.elements.file.value = '';
      document.querySelector('#document-form-title').textContent = `Замена: ${item.title}`;
      document.querySelector('#document-submit').textContent = 'Заменить документ';
      document.querySelector('#cancel-replace').hidden = false;
      documentForm.elements.file.focus();
    });
    const remove = documentButton('Удалить', async () => {
      if (!confirm(`Удалить документ «${item.title}» и его исходный файл?`)) return;
      try {
        const deleted = await documentApi('/api/documents/' + encodeURIComponent(item.id), {method:'DELETE'});
        document.querySelector('#document-detail').hidden = true;
        if (replacingDocument === item.id) resetDocumentForm();
        documentMessage.textContent = deleted.index_cleanup_pending ? 'Документ удалён; очистка индекса отложена. Проверьте журнал.' : 'Документ удалён.'; await loadDocuments();
      } catch (error) { documentMessage.textContent = error.message; }
    });
    actions.append(view, chunks, prepare, replace, remove); row.append(title, description, actions); documentList.append(row);
  }
}
documentForm.addEventListener('submit', async event => {
  event.preventDefault();
  for (const name of ['title', 'language']) {
    const field = documentForm.elements[name];
    field.setCustomValidity(field.value.trim() ? '' : 'Заполните поле.');
  }
  if (!documentForm.reportValidity()) return;
  if (replacingDocument && !confirm('Заменить исходный файл и данные этого документа?')) return;
  const button = document.querySelector('#document-submit'); button.disabled = true;
  documentMessage.textContent = 'Обработка документа…';
  try {
    const url = '/api/documents' + (replacingDocument ? '/' + encodeURIComponent(replacingDocument) : '');
    const saved = await documentApi(url, {method: replacingDocument ? 'PUT' : 'POST', body: new FormData(documentForm)});
    documentMessage.textContent = saved.index_cleanup_pending ? 'Документ заменён; очистка индекса отложена. Проверьте журнал.' : replacingDocument ? 'Документ заменён.' : 'Документ загружен.';
    document.querySelector('#document-detail').hidden = true; resetDocumentForm(); await loadDocuments();
  } catch (error) { documentMessage.textContent = error.message; }
  finally { button.disabled = false; }
});
document.querySelector('#cancel-replace').addEventListener('click', resetDocumentForm);
loadDocuments().catch(error => { documentMessage.textContent = 'Не удалось загрузить список: ' + error.message; });
async function pollIndex() {
  for (;;) {
    const state = await documentApi('/api/index/status');
    if (state.state === 'completed') {
      await loadDocuments();
      const warningText = state.result.warnings?.length ? ` Предупреждений: ${state.result.warnings.length}; откройте «Чанки».` : '';
      documentMessage.textContent = (state.result.status === 'unchanged' ? 'Индекс актуален.' : `Индексация завершена: ${state.result.chunks} чанков. Расходы: ${Math.round(Number(state.result.expenses.cost_rub))} ₽${state.result.expenses.unknown ? ' (часть стоимости неизвестна)' : ''}.`) + warningText;
      return;
    }
    if (state.state === 'error') {
      const costs = state.expenses;
      const detail = costs && costs.calls ? ` Расходы: ${Math.round(Number(costs.cost_rub))} ₽${costs.unknown ? ' (часть стоимости неизвестна)' : ''}.` : '';
      throw new Error('Ошибка подготовки или индексации: ' + state.error + detail);
    }
    if (state.state !== 'running') throw new Error('Состояние индексации потеряно; проверьте журнал.');
    documentMessage.textContent = state.phase === 'preparing' ? 'Подготовка чанков…' : `Индексация: ${state.completed} из ${state.total || '…'} чанков.`;
    await new Promise(resolve => setTimeout(resolve, 2000));
  }
}

// Восстанавливаем наблюдение за задачей после обновления страницы.
documentApi('/api/index/status').then(state => {
  if (state.state === 'running') return pollIndex();
  if (state.state === 'interrupted') documentMessage.textContent = state.error;
}).catch(error => { documentMessage.textContent = error.message; });
