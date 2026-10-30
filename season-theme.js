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
  }

  if (button) {
    button.addEventListener("click", () => {
      mode = seasonOrder[(seasonOrder.indexOf(mode) + 1) % seasonOrder.length];
      root.dataset.season = mode;
      try { localStorage.setItem(storageKey, mode); } catch (_) {}
      render();
    });
    render();
  }
})();
