(() => {
  const marker = 'data-font-plus-two-base';
  const skipTags = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'SVG', 'PATH', 'DEFS', 'CLIPPATH', 'LINEARGRADIENT', 'RADIALGRADIENT', 'STOP', 'FILTER', 'MASK', 'SYMBOL', 'USE']);

  function enlarge(root) {
    const elements = [];
    if (root && root.nodeType === Node.ELEMENT_NODE) elements.push(root);
    if (root && root.querySelectorAll) elements.push(...root.querySelectorAll('*'));

    const pending = [];
    for (const element of elements) {
      if (skipTags.has(element.tagName) || element.closest('svg') || element.hasAttribute(marker)) continue;
      const hasText = [...element.childNodes].some(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim());
      const isControl = /^(INPUT|TEXTAREA|SELECT)$/.test(element.tagName);
      if (!hasText && !isControl) continue;
      const size = Number.parseFloat(getComputedStyle(element).fontSize);
      if (!Number.isFinite(size) || size <= 0) continue;
      pending.push([element, size]);
    }

    for (const [element, size] of pending) {
      element.setAttribute(marker, String(size));
      element.style.setProperty('font-size', `${fontSizeFor(size)}px`);
    }
  }

  function fontSizeFor(size) {
    const normal = size + 2;
    return document.documentElement.dataset.accessibility === 'vision'
      ? Math.max(normal, size * 1.35)
      : normal;
  }

  function refresh() {
    document.querySelectorAll(`[${marker}]`).forEach(element => {
      const base = Number.parseFloat(element.getAttribute(marker));
      if (Number.isFinite(base)) element.style.setProperty('font-size', `${fontSizeFor(base)}px`);
    });
  }

  enlarge(document.body);
  window.addEventListener('accessible-font-scale-change', refresh);
  new MutationObserver(records => {
    for (const record of records) {
      for (const node of record.addedNodes) enlarge(node);
      if (record.type === 'characterData') enlarge(record.target.parentElement);
    }
  }).observe(document.body, { childList: true, characterData: true, subtree: true });
})();
