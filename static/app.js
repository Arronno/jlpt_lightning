(() => {
  'use strict';
  let composing = false;
  const fontSize = Number(document.documentElement.dataset.font);
  if (fontSize >= 24 && fontSize <= 64) document.documentElement.style.setProperty('--jp-size', `${fontSize}px`);
  const typing = (target) => target && (target.matches('input, textarea, select') || target.isContentEditable);
  document.addEventListener('compositionstart', () => { composing = true; });
  document.addEventListener('compositionend', () => { composing = false; });
  const reveal = () => {
    const panel = document.querySelector('#study-panel');
    const button = panel?.querySelector('[data-reveal]');
    if (!button || button.hidden) return;
    button.hidden = true;
    panel.querySelector('.card-answer').hidden = false;
    panel.querySelector('.rating-form').hidden = false;
    panel.querySelector('[name="revealed"]').value = 'yes';
    panel.querySelector('[data-rating="3"]').focus({preventScroll: true});
  };
  document.addEventListener('click', (event) => {
    if (event.target.closest('[data-reveal]')) reveal();
    const speak = event.target.closest('.speak');
    if (speak && 'speechSynthesis' in window) {
      const voice = speechSynthesis.getVoices().find(v => v.localService && /^ja(?:-|$)/i.test(v.lang));
      if (!voice) return;
      speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(speak.dataset.text);
      utterance.voice = voice;
      utterance.lang = voice.lang;
      utterance.rate = 0.85;
      speechSynthesis.speak(utterance);
    }
  });
  document.addEventListener('keydown', (event) => {
    if (event.isComposing || composing || event.keyCode === 229 || event.repeat || event.ctrlKey || event.altKey || event.metaKey || typing(event.target)) return;
    const panel = document.querySelector('#study-panel');
    if (!panel || !['cards', 'flashcards'].includes(panel.dataset.mode)) return;
    if (event.code === 'Space' && !panel.querySelector('[data-reveal]')?.hidden) {
      event.preventDefault(); reveal();
    } else if (/^[1-4]$/.test(event.key) && panel.querySelector('.rating-form')?.hidden === false) {
      event.preventDefault();
      const button = panel.querySelector(`[data-rating="${event.key}"]`);
      if (button && !button.disabled) button.click();
    }
  });
  // Enter during IME composition must not submit partially composed Japanese.
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && (composing || event.isComposing || event.keyCode === 229)) event.preventDefault();
  }, true);
  function initialize() {
    const voices = 'speechSynthesis' in window ? speechSynthesis.getVoices() : [];
    const available = voices.some(v => v.localService && /^ja(?:-|$)/i.test(v.lang));
    document.querySelectorAll('.speak').forEach(button => { button.hidden = !available; });
    document.querySelectorAll('.speech-status').forEach(label => {
      label.textContent = available ? 'Device pronunciation' : 'No local Japanese voice is available on this device.';
    });
    const answer = document.querySelector('#typing-answer');
    if (answer) answer.focus({preventScroll: true});
  }
  if ('speechSynthesis' in window) speechSynthesis.addEventListener('voiceschanged', initialize);
  document.addEventListener('htmx:afterSwap', () => {
    document.querySelector('#connection-error').hidden = true;
    initialize();
  });
  for (const event of ['htmx:sendError', 'htmx:responseError', 'htmx:timeout']) {
    document.addEventListener(event, () => { document.querySelector('#connection-error').hidden = false; });
  }
  initialize();
})();
