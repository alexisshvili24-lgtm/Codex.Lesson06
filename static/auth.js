const logoutButton = document.querySelector('#logout-button');
logoutButton?.addEventListener('click', async () => {
  logoutButton.disabled = true;
  try {
    await fetch('/api/auth/logout', {method: 'POST'});
  } finally {
    // Полная навигация очищает личное состояние скриптов перед следующим входом.
    location.replace('/');
  }
});

fetch('/api/auth/me').then(response => response.json()).then(data => {
  if (data.user) document.querySelector('#current-user').textContent = data.user.nickname;
}).catch(() => {});
