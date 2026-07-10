(() => {
  const MODAL_SELECTOR = '.trade-modal';

  function closeModal(modal) {
    if (!modal) return;
    modal.classList.remove('open');
    document.body.classList.remove('mini-modal-open');
  }

  function enhanceModal(modal) {
    if (!modal || modal.dataset.mobileEnhanced === '1') return;
    modal.dataset.mobileEnhanced = '1';
    const card = modal.querySelector('.trade-modal-card');
    if (!card) return;

    const topClose = card.querySelector('.modal-close');
    if (topClose) {
      topClose.setAttribute('aria-label', 'Закрыть окно');
      topClose.setAttribute('title', 'Закрыть');
    }

    if (!card.querySelector('.modal-close-bottom')) {
      const bottomClose = document.createElement('button');
      bottomClose.type = 'button';
      bottomClose.className = 'modal-close-bottom';
      bottomClose.textContent = 'Закрыть';
      bottomClose.addEventListener('click', () => closeModal(modal));
      card.appendChild(bottomClose);
    }

    modal.addEventListener('click', (event) => {
      if (event.target === modal) closeModal(modal);
    });
  }

  function scan() {
    document.querySelectorAll(MODAL_SELECTOR).forEach((modal) => {
      enhanceModal(modal);
      if (modal.classList.contains('open')) document.body.classList.add('mini-modal-open');
    });
  }

  const observer = new MutationObserver(scan);
  window.addEventListener('DOMContentLoaded', () => {
    scan();
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] });
  });

  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    closeModal(document.querySelector(`${MODAL_SELECTOR}.open`));
  });
})();
