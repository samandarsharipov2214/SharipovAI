(() => {
  'use strict';

  const content = document.getElementById('content');
  if (!content || content.dataset.runtimeRenderGuard === 'v24') return;

  const ownDescriptor = Object.getOwnPropertyDescriptor(content, 'innerHTML');
  const prototypeDescriptor = Object.getOwnPropertyDescriptor(Element.prototype, 'innerHTML');
  const descriptor = ownDescriptor?.get && ownDescriptor?.set ? ownDescriptor : prototypeDescriptor;
  if (!descriptor?.get || !descriptor?.set) return;

  const legacyOverviewMarkers = [
    'Фактическое состояние системы без выдуманных показателей',
    'Verified system state without invented figures',
    'To‘qima raqamlarsiz tizim holati',
  ];

  function activePage() {
    const coordinator = window.SharipovAIPageCoordinator;
    if (coordinator?.activePage) return coordinator.activePage();
    return document.querySelector('#nav button.active[data-page]')?.dataset.page || 'overview';
  }

  function isLegacyOverwrite(value) {
    const html = String(value ?? '');
    const page = activePage();
    if (page === 'overview' && legacyOverviewMarkers.some((marker) => html.includes(marker))) return true;
    if (page === 'market' && html.includes('class="market-toolbar"') && html.includes('id="symbolSelect"')) return true;
    return false;
  }

  Object.defineProperty(content, 'innerHTML', {
    configurable: true,
    enumerable: descriptor.enumerable,
    get() {
      return descriptor.get.call(this);
    },
    set(value) {
      if (isLegacyOverwrite(value)) return;
      descriptor.set.call(this, value);
    },
  });

  content.dataset.runtimeRenderGuard = 'v24';
})();
