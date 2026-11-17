/* Apply the saved theme before the stylesheet paints; storage can be unavailable. */
try {
  const saved = localStorage.getItem('training-rebuild-theme');
  document.documentElement.dataset.theme = saved === 'dark' ? 'dark' : 'light';
} catch { /* The light default works without persistent storage. */ }
