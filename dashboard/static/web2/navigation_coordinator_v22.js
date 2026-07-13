(() => {
  'use strict';

  const EXCLUSIVE_PAGES = new Map([
    ['system-status', 'system_status_v11.js'],
    ['operations', 'operations_center_v20.js'],
    ['incidents', 'incident_center_v21.js'],
  ]);

  function activePage() {
    return document.querySelector('#nav button.active[data-page]')?.dataset.page || 'overview';
  }

  function scriptFromStack(stack) {
    const value = String(stack || '');
    for (const filename of EXCLUSIVE_PAGES.values()) {
      if (value.includes(filename)) return filename;
    }
    return '';
  }

  function writeAllowed(stack) {
    const active = activePage();
    const activeOwner = EXCLUSIVE_PAGES.get(active);
    const callerOwner = scriptFromStack(stack);

    // An exclusive page owns #content while it is selected. Background refreshes
    // from the base dashboard must update state only, not replace the visible page.
    if (activeOwner) {
      return callerOwner === activeOwner || String(stack || '').includes('navigation_coordinator_v22.js');
    }

    // Ignore a delayed async response from an exclusive page after the user has
    // already navigated elsewhere.
    if (callerOwner) return false;
    return true;
  }

  function installContentOwnership() {
    const content = document.getElementById('content');
    if (!content || content.dataset.navigationOwnership === 'v22') return;

    const descriptor = Object.getOwnPropertyDescriptor(Element.prototype, 'innerHTML');
    if (!descriptor?.get || !descriptor?.set) return;

    Object.defineProperty(content, 'innerHTML', {
      configurable: true,
      enumerable: descriptor.enumerable,
      get() {
        return descriptor.get.call(this);
      },
      set(value) {
        const stack = new Error().stack || '';
        if (writeAllowed(stack)) descriptor.set.call(this, value);
      },
    });
    content.dataset.navigationOwnership = 'v22';
  }

  function preserveExtensionLabels() {
    const nav = document.getElementById('nav');
    if (!nav || nav.dataset.extensionLabelGuard === 'v22') return;

    const labels = {
      'system-status': 'Состояние системы',
      operations: 'Эксплуатация',
      incidents: 'Центр ошибок',
    };
    const restore = () => {
      for (const [page, label] of Object.entries(labels)) {
        const button = nav.querySelector(`button[data-page="${page}"]`);
        if (button && button.textContent !== label) button.textContent = label;
      }
    };
    new MutationObserver(restore).observe(nav, { childList: true, subtree: true, characterData: true });
    nav.dataset.extensionLabelGuard = 'v22';
    restore();
  }

  function install() {
    installContentOwnership();
    preserveExtensionLabels();
  }

  window.SharipovAIPageCoordinator = Object.freeze({
    activePage,
    writeAllowed,
    version: 22,
  });

  install();
  window.addEventListener('DOMContentLoaded', install, { once: true });
})();
