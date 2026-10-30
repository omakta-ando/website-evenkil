(() => {
  const root = document.documentElement;
  const nav = document.querySelector('.nav .navlinks');
  if (!nav || nav.querySelector('.a11y-toggle')) return;

  const storage = {
    enabled: 'taiga-accessible-summer',
    previousSeason: 'taiga-season-before-accessible-summer'
  };
  const seasonToggle = nav.querySelector('.season-toggle');
  const accessibleButton = document.createElement('button');
  accessibleButton.className = 'a11y-toggle';
  accessibleButton.type = 'button';
  accessibleButton.textContent = 'Aa';
  accessibleButton.setAttribute('aria-label', 'Включить летний режим для слабовидящих');
  accessibleButton.title = 'Летний режим для слабовидящих';
  accessibleButton.setAttribute('aria-pressed', 'false');
  accessibleButton.setAttribute('data-accessibility-ui', 'true');
  accessibleButton.dataset.a11yControl = 'vision';
  accessibleButton.setAttribute('aria-keyshortcuts', 'Alt+Shift+V');
  accessibleButton.addEventListener('click', toggleVisionMode);
  if (seasonToggle) seasonToggle.after(accessibleButton);
  else nav.append(accessibleButton);

  const lensButton = document.createElement('button');
  lensButton.className = 'magnifier-toggle';
  lensButton.type = 'button';
  lensButton.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.8" cy="10.8" r="6.4"></circle><path d="m15.5 15.5 5 5"></path><path d="M10.8 7.5v6.6M7.5 10.8h6.6"></path></svg>';
  lensButton.setAttribute('aria-label', 'Включить лупу');
  lensButton.title = 'Лупа: удерживайте правую кнопку мыши или включите режим кнопкой';
  lensButton.setAttribute('aria-pressed', 'false');
  lensButton.setAttribute('data-accessibility-ui', 'true');
  lensButton.addEventListener('click', toggleStickyLens);
  accessibleButton.after(lensButton);

  const live = document.createElement('span');
  live.className = 'a11y-live';
  live.setAttribute('aria-live', 'polite');
  live.setAttribute('aria-atomic', 'true');
  live.setAttribute('data-accessibility-ui', 'true');
  nav.append(live);

  const lens = document.createElement('div');
  lens.id = 'accessibility-magnifier';
  lens.className = 'accessibility-magnifier';
  lens.setAttribute('aria-hidden', 'true');
  lens.setAttribute('data-accessibility-ui', 'true');
  const frame = document.createElement('iframe');
  frame.title = 'Увеличенное изображение страницы';
  frame.setAttribute('sandbox', 'allow-same-origin');
  frame.setAttribute('tabindex', '-1');
  lens.append(frame);
  document.body.append(lens);

  let previousSeason = 'day';
  let rightHeld = false;
  let stickyLens = false;
  let lensReady = false;
  let pointer = { x: Math.round(innerWidth / 2), y: Math.round(innerHeight / 2) };
  const magnification = 1.8;
  const diameter = 210;

  try {
    if (localStorage.getItem(storage.enabled) === 'true') {
      previousSeason = localStorage.getItem(storage.previousSeason) || 'day';
      root.dataset.accessibility = 'vision';
      root.dataset.season = 'summer';
      accessibleButton.setAttribute('aria-pressed', 'true');
      accessibleButton.setAttribute('aria-label', 'Выключить летний режим для слабовидящих');
      accessibleButton.title = 'Выключить летний режим для слабовидящих';
      if (seasonToggle) {
        seasonToggle.disabled = true;
        seasonToggle.title = 'Сначала выключите летний режим для слабовидящих';
      }
    }
  } catch (_) {}
  window.dispatchEvent(new Event('accessible-font-scale-change'));

  function toggleVisionMode() {
    const enabled = root.dataset.accessibility !== 'vision';
    try {
      if (enabled) {
        previousSeason = root.dataset.season || 'day';
        localStorage.setItem(storage.previousSeason, previousSeason);
        localStorage.setItem(storage.enabled, 'true');
      } else {
        localStorage.removeItem(storage.enabled);
        localStorage.removeItem(storage.previousSeason);
      }
    } catch (_) {}

    if (enabled) {
      root.dataset.accessibility = 'vision';
      root.dataset.season = 'summer';
      accessibleButton.setAttribute('aria-pressed', 'true');
      accessibleButton.setAttribute('aria-label', 'Выключить летний режим для слабовидящих');
      accessibleButton.title = 'Выключить летний режим для слабовидящих';
      if (seasonToggle) {
        seasonToggle.disabled = true;
        seasonToggle.title = 'Сначала выключите летний режим для слабовидящих';
      }
      live.textContent = 'Летний режим для слабовидящих включён. Текст увеличен. Удерживайте правую кнопку мыши, чтобы включить лупу.';
    } else {
      delete root.dataset.accessibility;
      root.dataset.season = previousSeason;
      accessibleButton.setAttribute('aria-pressed', 'false');
      accessibleButton.setAttribute('aria-label', 'Включить летний режим для слабовидящих');
      accessibleButton.title = 'Летний режим для слабовидящих';
      if (seasonToggle) {
        seasonToggle.disabled = false;
        seasonToggle.title = 'Переключить сезон';
      }
      stopLens();
      live.textContent = 'Летний режим для слабовидящих выключен.';
    }
    window.dispatchEvent(new Event('accessible-font-scale-change'));
    root.dispatchEvent(new Event('season-theme-change'));
  }

  function makeSnapshot() {
    const copy = document.documentElement.cloneNode(true);
    copy.querySelectorAll('script, #accessibility-magnifier, [data-accessibility-ui]').forEach(node => node.remove());
    const base = document.createElement('base');
    base.href = document.baseURI;
    copy.querySelector('head')?.prepend(base);
    frame.onload = () => {
      lensReady = true;
      frame.contentWindow?.scrollTo(0, window.scrollY);
      moveLens(pointer.x, pointer.y);
    };
    frame.srcdoc = `<!doctype html>${copy.outerHTML}`;
    lensReady = false;
  }

  function moveLens(x, y) {
    pointer = { x, y };
    lens.style.left = `${Math.max(0, Math.min(innerWidth - diameter, x - diameter / 2))}px`;
    lens.style.top = `${Math.max(0, Math.min(innerHeight - diameter, y - diameter / 2))}px`;
    const offsetX = diameter / 2 - x * magnification;
    const offsetY = diameter / 2 - y * magnification;
    frame.style.transform = `translate(${offsetX}px, ${offsetY}px) scale(${magnification})`;
  }

  function showLens(x, y, refresh = false) {
    moveLens(x, y);
    if (!lensReady || refresh) makeSnapshot();
    lens.classList.add('is-visible');
    if (lensReady) moveLens(x, y);
  }

  function stopLens() {
    rightHeld = false;
    stickyLens = false;
    lens.classList.remove('is-visible');
    lensButton.setAttribute('aria-pressed', 'false');
    lensButton.setAttribute('aria-label', 'Включить лупу');
    lensButton.title = 'Лупа: удерживайте правую кнопку мыши или включите режим кнопкой';
  }

  function toggleStickyLens() {
    stickyLens = !stickyLens;
    lensButton.setAttribute('aria-pressed', String(stickyLens));
    lensButton.setAttribute('aria-label', stickyLens ? 'Выключить лупу' : 'Включить лупу');
    lensButton.title = stickyLens ? 'Выключить режим лупы' : 'Включить режим лупы';
    if (stickyLens) {
      showLens(pointer.x, pointer.y, true);
      live.textContent = 'Лупа включена. Перемещайте указатель по странице; нажмите кнопку лупы ещё раз, чтобы выключить.';
    } else {
      lens.classList.remove('is-visible');
      live.textContent = 'Лупа выключена.';
    }
  }

  window.addEventListener('pointermove', event => {
    pointer = { x: event.clientX, y: event.clientY };
    if (rightHeld || stickyLens) moveLens(event.clientX, event.clientY);
  }, { passive: true });

  window.addEventListener('pointerdown', event => {
    if (event.pointerType !== 'mouse' || event.button !== 2 || root.dataset.accessibility !== 'vision') return;
    event.preventDefault();
    rightHeld = true;
    showLens(event.clientX, event.clientY, true);
  });
  window.addEventListener('pointerup', event => {
    if (event.button === 2 && rightHeld) {
      rightHeld = false;
      if (!stickyLens) lens.classList.remove('is-visible');
    }
  });
  window.addEventListener('contextmenu', event => {
    if (root.dataset.accessibility === 'vision') event.preventDefault();
  });
  window.addEventListener('blur', () => { if (!stickyLens) stopLens(); });
  window.addEventListener('resize', () => moveLens(pointer.x, pointer.y), { passive: true });
  window.addEventListener('scroll', () => {
    if (lens.classList.contains('is-visible')) frame.contentWindow?.scrollTo(0, window.scrollY);
    moveLens(pointer.x, pointer.y);
  }, { passive: true });
  window.addEventListener('keydown', event => {
    if (event.altKey && event.shiftKey && event.key.toLowerCase() === 'v') {
      event.preventDefault();
      toggleVisionMode();
    }
    if (event.key === 'Escape' && (stickyLens || rightHeld)) stopLens();
  });
})();
