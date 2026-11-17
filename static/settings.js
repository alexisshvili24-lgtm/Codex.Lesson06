const form = document.querySelector('#settings-form');
const message = document.querySelector('#settings-message');
function rubles(value) {
  const match = /^(\d+)(?:\.(\d+))?$/.exec(String(value));
  if (!match) return 'неизвестно';
  const rounded = BigInt(match[1]) + ((match[2] || '')[0] >= '5' ? 1n : 0n);
  return `${rounded.toLocaleString('ru-RU')} ₽`;
}
function updateNavigation() {
  const links = Array.from(document.querySelectorAll('.sidebar nav a'));
  const active = links.some(link => link.hash === location.hash) ? location.hash : '#chat';
  for (const link of links) {
    if (link.getAttribute('href') === active) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  }
}
window.addEventListener('hashchange', updateNavigation);
updateNavigation();
const fields = ['base_url', 'embedding_model', 'generation_model', 'system_prompt', 'vector_enabled', 'vector_threshold', 'bm25_enabled', 'bm25_threshold'];
async function api(url, options) {
  const response = await fetch(url, options);
  if (response.status === 401) { location.replace('/'); throw new Error('Сессия завершена. Войдите снова.'); }
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Проверьте значения полей.');
  return data;
}
async function load() {
  const data = await api('/api/settings');
  for (const name of fields) {
    const el = form.elements[name];
    if (el.type === 'checkbox') el.checked = data[name] === true || data[name] === 'true';
    else el.value = data[name];
  }
  form.elements.base_url.readOnly = !data.can_edit_global;
  form.elements.generation_model.readOnly = !data.can_edit_global;
  form.elements.embedding_model.readOnly = true;
  document.querySelector('#key-status').textContent = data.key_configured ? 'Ключ сохранён. Чтобы заменить его, введите новый.' : 'Ключ пока не задан.';
  await loadEvents();
}
async function loadChunkPlugins() {
  const data = await api('/api/chunk-plugins');
  const select = document.querySelector('#chunk-plugin');
  select.replaceChildren();
  for (const plugin of data.plugins) {
    const option = document.createElement('option');
    option.value = plugin.id;
    option.textContent = plugin.name + (plugin.available ? '' : ' — не установлен');
    option.disabled = !plugin.available;
    select.append(option);
  }
  if (![...select.options].some(option => option.value === data.selected)) {
    const missing = document.createElement('option');
    missing.value = data.selected; missing.textContent = data.selected + ' — не установлен';
    missing.disabled = true; select.append(missing);
  }
  select.value = data.selected;
  select.disabled = !data.can_edit;
  document.querySelector('#chunk-plugin-form button[type="submit"]').disabled = !data.can_edit;
}
document.querySelector('#chunk-plugin-form').addEventListener('submit', async event => {
  event.preventDefault();
  const message = document.querySelector('#chunk-plugin-message');
  try {
    await api('/api/chunk-plugins', {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({plugin:document.querySelector('#chunk-plugin').value})});
    document.querySelector('#chunk-panel').hidden = true;
    document.querySelector('#document-detail').hidden = true;
    message.textContent = 'Плагин сохранён. При необходимости подготовьте чанки заново.';
    await loadChunkPlugins();
  } catch (error) { message.textContent = error.message; }
});
loadChunkPlugins().catch(error => { document.querySelector('#chunk-plugin-message').textContent = 'Не удалось загрузить плагины: ' + error.message; });
async function loadEvents() {
  const data = await api('/api/events');
  const c = data.costs;
  document.querySelector('#costs').textContent = `Всего: ${rubles(c.total)} · embeddings: ${rubles(c.embedding)} · генерация: ${rubles(c.generation)} · вызовов: ${c.calls} · без стоимости: ${c.unknown}`;
  const versionList = document.querySelector('#cost-version-list');
  versionList.replaceChildren();
  const versions = data.costs_by_key_version || [];
  if (!versions.length) {
    const empty = document.createElement('p');
    empty.textContent = 'Платных вызовов пока нет.';
    versionList.append(empty);
  }
  for (const version of versions) {
    const item = document.createElement('details');
    const summary = document.createElement('summary');
    const label = version.key_version_id
      ? `Версия ключа ${version.key_version_id.slice(0, 8)}`
      : 'Исторические вызовы (версия ключа неизвестна)';
    summary.textContent = `${label} · ${rubles(version.total)} · вызовов: ${version.calls}`;
    const costs = document.createElement('p');
    costs.textContent = `Embeddings: ${rubles(version.embedding)} · генерация: ${rubles(version.generation)} · без стоимости: ${version.unknown}`;
    item.append(summary, costs);
    if (version.key_version_id) {
      const id = document.createElement('p');
      const code = document.createElement('code');
      code.textContent = version.key_version_id;
      id.append('ID версии: ', code);
      item.append(id);
    }
    const dates = document.createElement('p');
    dates.textContent = `Период: ${version.first_seen} — ${version.last_seen}`;
    item.append(dates);
    versionList.append(item);
  }
  const list = document.querySelector('#event-list');
  list.replaceChildren();
  for (const event of data.events) {
    const item = document.createElement('details');
    const summary = document.createElement('summary');
    summary.textContent = `${event.created_at} · ${event.operation} · ${event.status} · ${event.cost_rub === null ? 'стоимость неизвестна' : rubles(event.cost_rub)}`;
    const pre = document.createElement('pre');
    pre.textContent = JSON.stringify(JSON.parse(event.payload), null, 2);
    item.append(summary, pre); list.append(item);
  }
}
form.addEventListener('submit', async event => {
  event.preventDefault();
  const data = {};
  for (const name of fields) { const el = form.elements[name]; data[name] = el.type === 'checkbox' ? el.checked : el.type === 'number' ? Number(el.value) : el.value; }
  data.api_key = form.elements.api_key.value || null;
  try { await api('/api/settings', {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)}); form.elements.api_key.value = ''; message.textContent = 'Настройки сохранены.'; await load(); }
  catch (error) { message.textContent = error.message; }
});
for (const button of document.querySelectorAll('[data-test]')) button.addEventListener('click', async () => {
  button.disabled = true; message.textContent = 'Проверка выполняется…';
  try { const result = await api('/api/test/' + button.dataset.test, {method:'POST'}); message.textContent = result.message; await loadEvents(); }
  catch (error) { message.textContent = error.message; }
  finally { button.disabled = false; }
});
load().catch(error => { message.textContent = 'Не удалось загрузить настройки: ' + error.message; });
