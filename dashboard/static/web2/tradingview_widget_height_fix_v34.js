(() => {
  'use strict';

  const DEFAULT_HEIGHT = 720;
  let scheduled = false;
  let observer = null;

  function marketActive() {
    const coordinator = window.SharipovAIPageCoordinator;
    return coordinator?.activePage
      ? coordinator.activePage() === 'market'
      : document.querySelector('#nav button.active[data-page="market"]') !== null;
  }

  function numericHeight(value) {
    const parsed = Number.parseFloat(String(value || '').replace('px', ''));
    return Number.isFinite(parsed) && parsed >= 400 ? parsed : 0;
  }

  function applyHeightFix() {
    scheduled = false;
    if (!marketActive()) return;
    const host = document.getElementById('tv32Widget');
    if (!host) return;
    const container = host.querySelector('.tv32-widget-container');
    const widget = host.querySelector('.tradingview-widget-container__widget');
    const height = Math.max(
      numericHeight(host.style.minHeight),
      numericHeight(host.style.height),
      numericHeight(container?.style.height),
      DEFAULT_HEIGHT,
    );
    const widgetHeight = Math.max(372, height - 28);

    host.style.setProperty('--tv32-widget-height', `${height}px`);
    host.style.height = `${height}px`;
    host.style.minHeight = `${height}px`;

    if (container) {
      container.style.width = '100%';
      container.style.height = `${height}px`;
      container.style.minHeight = `${height}px`;
    }
    if (widget) {
      widget.style.width = '100%';
      widget.style.height = `${widgetHeight}px`;
      widget.style.minHeight = `${widgetHeight}px`;
    }

    host.querySelectorAll('iframe').forEach((frame) => {
      const directContainerChild = frame.parentElement === container;
      const frameHeight = directContainerChild ? widgetHeight : '100%';
      frame.style.display = 'block';
      frame.style.width = '100%';
      frame.style.height = typeof frameHeight === 'number' ? `${frameHeight}px` : frameHeight;
      frame.style.minHeight = typeof frameHeight === 'number' ? `${frameHeight}px` : frameHeight;
      frame.setAttribute('width', '100%');
      frame.setAttribute('height', String(widgetHeight));
    });
  }

  function scheduleFix() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(applyHeightFix);
  }

  function start() {
    if (!observer) {
      observer = new MutationObserver(scheduleFix);
      observer.observe(document.body, { childList: true, subtree: true });
    }
    scheduleFix();
    setTimeout(scheduleFix, 250);
    setTimeout(scheduleFix, 1000);
    setTimeout(scheduleFix, 2500);
  }

  document.addEventListener('click', (event) => {
    if (event.target.closest('#nav button[data-page="market"], [data-tv32-tab], [data-tv32-interval], #tv32Refresh')) {
      setTimeout(scheduleFix, 0);
      setTimeout(scheduleFix, 600);
    }
  });
  window.addEventListener('resize', scheduleFix);
  window.addEventListener('DOMContentLoaded', start);
})();
