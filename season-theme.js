(() => {
  const root = document.documentElement;
  const button = document.querySelector(".season-toggle");
  const storageKey = "taiga-season-theme";
  let mode = root.dataset.season === "night" ? "night" : "day";

  function render() {
    if (!button) return;
    const night = mode === "night";
    button.setAttribute("aria-pressed", String(night));
    button.setAttribute("aria-label", night ? "Включить полярный день" : "Включить полярную ночь");
    button.title = night ? "Полярный день" : "Полярная ночь";
    button.innerHTML = night
      ? '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"/></svg>'
      : '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.4 15.2A8.5 8.5 0 0 1 8.8 3.6 8.6 8.6 0 1 0 20.4 15.2Z"/><path d="M16 3v3m-1.5-1.5h3"/></svg>';
  }

  if (button) {
    button.addEventListener("click", () => {
      mode = mode === "night" ? "day" : "night";
      root.dataset.season = mode;
      try { localStorage.setItem(storageKey, mode); } catch (_) {}
      render();
    });
    render();
  }
})();
