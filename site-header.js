(() => {
  const mount = document.getElementById("site-header-root");
  if (!mount) return;

  const page = location.pathname.split("/").pop() || "index.html";
  const links = [
    ["index.html#news", "Новости регионов", "index.html"],
    ["history.html", "Об эвенках", "history.html"],
    ["map.html", "Эвэды Буга", "map.html"],
    ["gallery.html", "Галерея", "gallery.html"],
    ["index.html#resources", "Полезные ресурсы", "resources"],
    ["sources.html", "Источники", "sources.html"],
    ["contact.html", "Написать нам", "contact.html"]
  ];
  const nav = links.map(([href, label, key]) => {
    const active = key === page || (page === "index.html" && key === "resources" && location.hash === "#resources");
    return '<a href="' + href + '"' + (active ? ' aria-current="page"' : "") + '>' + label + '</a>';
  }).join("");

  mount.innerHTML = `
    <div class="topline"><div class="wrap"><span>Новости и знания об эвенках России</span></div></div>
    <header class="nav">
      <div class="wrap">
        <a class="brand" href="index.html"><span class="brand-mark"><img src="taezhnye-golosa-sevek-mo.svg?v=20261001-logo-1" alt=""></span>таёжная нить</a>
        <nav class="navlinks" aria-label="Основная навигация">
          ${nav}
          <span class="nav-social" aria-label="Социальные сети">
            <a href="https://t.me/taiga_thread" aria-label="Telegram" title="Telegram" target="_blank" rel="noopener noreferrer"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21.5 3.7 18.2 20c-.2 1.1-.8 1.4-1.6.9l-4.5-3.3-2.2 2.1c-.2.2-.4.4-.8.4l.3-4.6 8.4-7.6c.4-.3-.1-.5-.6-.2L6.8 14.4l-4.4-1.4c-1-.3-1-1 .2-1.5L20 3.1c.9-.3 1.7.2 1.5.6Z"/></svg></a>
            <a href="https://www.facebook.com/groups/1427835186122942/" aria-label="Группа в Facebook" title="Facebook" target="_blank" rel="noopener noreferrer"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M13.4 21v-8.2h2.8l.4-3.2h-3.2v-2c0-.9.3-1.5 1.6-1.5h1.7V3.2c-.3 0-1.3-.1-2.5-.1-2.5 0-4.2 1.5-4.2 4.3v2.4H7.2V13h2.8v8h3.4Z"/></svg></a>
          </span>
          <button class="season-toggle" type="button" aria-label="Включить полярную ночь" title="Полярная ночь" aria-pressed="false"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.4 15.2A8.5 8.5 0 0 1 8.8 3.6 8.6 8.6 0 1 0 20.4 15.2Z"/><path d="M16 3v3m-1.5-1.5h3"/></svg></button>
        </nav>
        <button class="menu" aria-label="Меню">☰</button>
      </div>
    </header>`;
})();