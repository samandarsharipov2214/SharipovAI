(() => {
  const tg = window.Telegram && window.Telegram.WebApp;
  if (!tg) {
    document.documentElement.dataset.telegram = 'browser';
    return;
  }

  document.documentElement.dataset.telegram = 'miniapp';
  document.documentElement.dataset.telegramPlatform = tg.platform || 'unknown';

  function applyTheme() {
    const p = tg.themeParams || {};
    const root = document.documentElement;
    const vars = {
      '--tg-theme-bg-color': p.bg_color,
      '--tg-theme-text-color': p.text_color,
      '--tg-theme-hint-color': p.hint_color,
      '--tg-theme-link-color': p.link_color,
      '--tg-theme-button-color': p.button_color,
      '--tg-theme-button-text-color': p.button_text_color,
      '--tg-theme-secondary-bg-color': p.secondary_bg_color,
      '--tg-theme-header-bg-color': p.header_bg_color,
      '--tg-theme-bottom-bar-bg-color': p.bottom_bar_bg_color,
    };
    Object.entries(vars).forEach(([name, value]) => {
      if (value) root.style.setProperty(name, value);
    });
    root.dataset.colorScheme = tg.colorScheme || 'dark';
  }

  function applySafeArea() {
    const root = document.documentElement;
    const safe = tg.safeAreaInset || {};
    const content = tg.contentSafeAreaInset || {};
    root.style.setProperty('--tg-safe-top', `${Number(safe.top || 0)}px`);
    root.style.setProperty('--tg-safe-right', `${Number(safe.right || 0)}px`);
    root.style.setProperty('--tg-safe-bottom', `${Number(safe.bottom || 0)}px`);
    root.style.setProperty('--tg-safe-left', `${Number(safe.left || 0)}px`);
    root.style.setProperty('--tg-content-safe-top', `${Number(content.top || 0)}px`);
    root.style.setProperty('--tg-content-safe-bottom', `${Number(content.bottom || 0)}px`);
  }

  async function authenticate() {
    if (!tg.initData) {
      document.documentElement.dataset.telegramAuth = 'missing';
      return;
    }
    try {
      const response = await fetch('/api/telegram/miniapp-auth', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        cache: 'no-store',
        body: JSON.stringify({ init_data: tg.initData }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.authenticated) throw new Error(payload.detail || 'auth_failed');
      document.documentElement.dataset.telegramAuth = 'ok';
      window.SharipovAITelegramUser = payload.user || null;
      window.dispatchEvent(new CustomEvent('sharipovai:telegram-auth', { detail: payload }));
    } catch (error) {
      document.documentElement.dataset.telegramAuth = 'failed';
      console.error('Telegram Mini App authentication failed', error);
    }
  }

  function init() {
    applyTheme();
    applySafeArea();
    tg.ready();
    tg.expand();
    try { tg.setHeaderColor('secondary_bg_color'); } catch (_) {}
    try { tg.setBackgroundColor('bg_color'); } catch (_) {}
    try { tg.setBottomBarColor('bottom_bar_bg_color'); } catch (_) {}
    try { tg.enableClosingConfirmation(); } catch (_) {}
    tg.onEvent('themeChanged', applyTheme);
    tg.onEvent('safeAreaChanged', applySafeArea);
    tg.onEvent('contentSafeAreaChanged', applySafeArea);
    authenticate();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
