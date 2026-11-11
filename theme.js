(() => {
  let saved = null;
  try { saved = localStorage.getItem('household-ledger-theme'); } catch {}
  const theme = saved === 'dark' || saved === 'light'
    ? saved
    : (window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  document.documentElement.dataset.theme = theme;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = theme === 'dark' ? '#09090b' : '#f7f8fa';
})();
