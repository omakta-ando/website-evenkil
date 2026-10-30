(() => {
  const root = document.documentElement;
  const button = document.querySelector(".season-toggle");
  const storageKey = "taiga-season-theme";
  const seasonOrder = ["night", "spring", "summer", "day"];
  let mode = seasonOrder.includes(root.dataset.season) ? root.dataset.season : "day";

  function syncHeroSceneOffset() {
    const masthead = document.querySelector(".topline");
    const nav = document.querySelector(".nav");
    const offset = (masthead?.offsetHeight || 72) + (nav?.offsetHeight || 52);
    root.style.setProperty("--hero-scene-offset", `${offset}px`);
  }
  syncHeroSceneOffset();
  if ("ResizeObserver" in window) {
    const sceneObserver = new ResizeObserver(syncHeroSceneOffset);
    const masthead = document.querySelector(".topline");
    const nav = document.querySelector(".nav");
    if (masthead) sceneObserver.observe(masthead);
    if (nav) sceneObserver.observe(nav);
  }
  window.addEventListener("resize", syncHeroSceneOffset, { passive: true });

  function render() {
    const quoteBands = document.querySelectorAll(".quote-band");
    const quoteScenes = {
      day: { image: "media/taiga-river-hero-v1.png", tint: "rgba(245,243,233,.44),rgba(238,241,230,.36) 52%,rgba(232,237,224,.44)" },
      night: { image: "media/taiga-river-winter-aurora-v2.jpg", tint: "rgba(245,243,233,.44),rgba(238,241,230,.36) 52%,rgba(232,237,224,.44)" },
      spring: { image: "media/taiga-river-spring-v1.jpg", tint: "rgba(240,247,247,.44),rgba(232,244,242,.36) 52%,rgba(240,247,247,.44)" },
      summer: { image: "media/taiga-river-summer-eagle-v1.jpg", tint: "rgba(244,247,235,.44),rgba(236,244,226,.36) 52%,rgba(244,247,235,.44)" }
    };
    const scene = quoteScenes[mode];
    if (scene) {
      quoteBands.forEach((quoteBand) => {
        quoteBand.style.setProperty("background-image", `linear-gradient(110deg,${scene.tint}),url("${scene.image}")`, "important");
        quoteBand.style.setProperty("background-position", "center 52%", "important");
        quoteBand.style.setProperty("background-size", "cover", "important");
        quoteBand.style.setProperty("background-repeat", "no-repeat", "important");
      });
    }
    if (!button) return;
    const currentIndex = seasonOrder.indexOf(mode);
    const next = seasonOrder[(currentIndex + 1) % seasonOrder.length];
    const labels = { night: "Зима", spring: "Весна", summer: "Лето", day: "Осень" };
    const icons = {
      day: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19.5 4.5c-6.2.4-11.1 2-13.4 5.5-1.4 2.1-.9 4.7 1 5.9 1.1.7 2.5.8 3.9.2-.4 1.2-.1 2.4.8 3.1 1.3 1 3.1.5 4.1-1 2.1-3.2 3.1-8.1 3.6-13.7Z"/><path d="M5.8 19.2c3-4.1 6.4-7.2 11.5-10.5"/></svg>',
      night: '<svg viewBox="0 0 24 24" aria-hidden="true"><g><path d="M12 12V2.6M12 6.4 9.6 4M12 6.4 14.4 4"/></g><g transform="rotate(60 12 12)"><path d="M12 12V2.6M12 6.4 9.6 4M12 6.4 14.4 4"/></g><g transform="rotate(120 12 12)"><path d="M12 12V2.6M12 6.4 9.6 4M12 6.4 14.4 4"/></g><g transform="rotate(180 12 12)"><path d="M12 12V2.6M12 6.4 9.6 4M12 6.4 14.4 4"/></g><g transform="rotate(240 12 12)"><path d="M12 12V2.6M12 6.4 9.6 4M12 6.4 14.4 4"/></g><g transform="rotate(300 12 12)"><path d="M12 12V2.6M12 6.4 9.6 4M12 6.4 14.4 4"/></g></svg>',
      spring: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21v-9"/><path d="M12 15c-5.2 0-7.5-2.8-7.5-6.5C8.5 8.5 11 10.5 12 15Z"/><path d="M12 12c.2-4.4 2.8-7 7.5-7.5C19.2 9 16.8 11.5 12 12Z"/><path d="M8 21h8"/></svg>',
      summer: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42m0-14.14-1.42 1.42m-11.3 11.3-1.42 1.42"/></svg>'
    };
    button.removeAttribute("aria-pressed");
    button.setAttribute("aria-label", `Сейчас: ${labels[mode]}. Переключить на тему «${labels[next]}»`);
    button.title = `Следующая тема: ${labels[next]}`;
    button.innerHTML = icons[next];
    const accessibilityToggle = document.querySelector(".a11y-toggle");
    if (accessibilityToggle) accessibilityToggle.hidden = mode !== "summer";
  }

  if (button) {
    button.addEventListener("click", () => {
      mode = seasonOrder.includes(root.dataset.season) ? root.dataset.season : mode;
      mode = seasonOrder[(seasonOrder.indexOf(mode) + 1) % seasonOrder.length];
      root.dataset.season = mode;
      try { localStorage.setItem(storageKey, mode); } catch (_) {}
      render();
      root.dispatchEvent(new Event("season-theme-change"));
    });
    render();
  }

  root.addEventListener("season-theme-change", () => {
    if (!seasonOrder.includes(root.dataset.season)) return;
    mode = root.dataset.season;
    render();
  });
})();

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
  accessibleButton.hidden = root.dataset.season !== 'summer';
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
    }
  } catch (_) {}
  window.dispatchEvent(new Event('accessible-font-scale-change'));

  root.addEventListener('season-theme-change', () => {
    const summerSelected = root.dataset.season === 'summer';
    accessibleButton.hidden = !summerSelected;
    if (summerSelected || root.dataset.accessibility !== 'vision') return;

    delete root.dataset.accessibility;
    try {
      localStorage.removeItem(storage.enabled);
      localStorage.removeItem(storage.previousSeason);
    } catch (_) {}
    accessibleButton.setAttribute('aria-pressed', 'false');
    accessibleButton.setAttribute('aria-label', 'Включить летний режим для слабовидящих');
    accessibleButton.title = 'Летний режим для слабовидящих';
    stopLens();
    live.textContent = 'Увеличенный шрифт выключен при смене сезона.';
    window.dispatchEvent(new Event('accessible-font-scale-change'));
  });

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
      live.textContent = 'Летний режим для слабовидящих включён. Текст увеличен. Удерживайте правую кнопку мыши, чтобы включить лупу.';
    } else {
      delete root.dataset.accessibility;
      root.dataset.season = previousSeason;
      accessibleButton.setAttribute('aria-pressed', 'false');
      accessibleButton.setAttribute('aria-label', 'Включить летний режим для слабовидящих');
      accessibleButton.title = 'Летний режим для слабовидящих';
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
