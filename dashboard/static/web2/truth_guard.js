(() => {
  'use strict';

  const SYNTHETIC_PHRASES = [
    'сверил цель дня, риск и конфликт решений',
    'сверил ботов, цель дня, риск и дисциплину paper-realism',
    'обновил сценарий BTC/ETH/SOL',
    'проверил источники и снизил доверие',
    'пересчитал риск как при реальном капитале',
    'принял ошибку ETH'
  ];

  function sanitizeBotCards(root = document) {
    root.querySelectorAll('.bot-grid .panel').forEach(card => {
      const text = card.textContent || '';
      const hasSyntheticAction = SYNTHETIC_PHRASES.some(phrase => text.includes(phrase));
      const rows = [...card.querySelectorAll('.status-list > div')];

      rows.forEach(row => {
        const label = row.querySelector('span')?.textContent?.trim();
        const value = row.querySelector('b');
        if (!value) return;

        if (label === 'Статус') {
          value.textContent = 'НЕ ПОДТВЕРЖДЁН';
          value.className = 'negative';
        }
        if (label === 'Качество') {
          value.textContent = 'НЕТ ИЗМЕРЕНИЙ';
          value.className = '';
        }
        if (label === 'Последнее действие' && (hasSyntheticAction || value.textContent.trim() !== '—')) {
          value.textContent = 'НЕТ ПОДТВЕРЖДЁННОГО СОБЫТИЯ';
          value.className = '';
        }
      });

      if (!card.querySelector('.truth-note')) {
        const note = document.createElement('p');
        note.className = 'truth-note';
        note.textContent = 'Статус, качество и действия показываются только при наличии heartbeat, времени события и записи Evidence Vault.';
        card.appendChild(note);
      }
    });
  }

  const observer = new MutationObserver(() => sanitizeBotCards());
  observer.observe(document.documentElement, { childList: true, subtree: true });
  document.addEventListener('DOMContentLoaded', () => sanitizeBotCards());
  sanitizeBotCards();
})();
