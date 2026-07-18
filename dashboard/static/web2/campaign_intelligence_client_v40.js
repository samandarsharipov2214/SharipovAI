(() => {
  'use strict';
  const endpoint = ['', 'api', 'campaigns', 'phase8', 'live'].join('/');
  let sequence = -1;
  async function refresh() {
    const response = await fetch(`${endpoint}?since_sequence=${sequence}`, {cache: 'no-store'});
    const payload = await response.json();
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    sequence = Number(payload.sequence || 0);
    window.dispatchEvent(new CustomEvent('phase8data', {detail: payload}));
  }
  setInterval(() => {
    if (document.visibilityState === 'visible') refresh().catch(() => {});
  }, 1000);
  window.SharipovAIPhase8Client = {refresh};
})();
