const form = document.querySelector('#login-form');
const status = document.querySelector('#login-status');

form.addEventListener('submit', async event => {
  event.preventDefault();
  const button = form.querySelector('button[type="submit"]');
  button.disabled = true;
  status.textContent = 'Входим…';
  try {
    const response = await fetch('/api/auth/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({nickname: form.elements.nickname.value})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Не удалось войти.');
    location.replace('/');
  } catch (error) {
    status.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
