// Renders the shared sidebar + top bar. Each page sets data-page / data-title / data-crumbs on <body>.
const I = {
  home: '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/>',
  users: '<circle cx="9" cy="8" r="3.2"/><path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6"/><path d="M16 4.5a3 3 0 010 6M21 20c0-2.6-1.6-4.8-4-5.6"/>',
  ruler: '<path d="M3 17L17 3l4 4L7 21z"/><path d="M7 13l2 2M10 10l2 2M13 7l2 2"/>',
  quote: '<path d="M6 3h9l4 4v14H6z"/><path d="M15 3v4h4M9 12h7M9 16h7M9 8h3"/>',
  factory: '<path d="M3 21V10l6 4V10l6 4V6h6v15z"/><path d="M7 18h2M12 18h2M17 18h2"/>',
  box: '<path d="M3 7l9-4 9 4v10l-9 4-9-4z"/><path d="M3 7l9 4 9-4M12 11v10"/>',
  cart: '<circle cx="9" cy="20" r="1.5"/><circle cx="18" cy="20" r="1.5"/><path d="M2 3h3l2.5 12h11L21 7H6"/>',
  cash: '<rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="12" cy="12" r="2.5"/><path d="M6 9v6M18 9v6"/>',
  layers: '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
  shield: '<path d="M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6z"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.6 1.6 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.6 1.6 0 00-2.7 1.1V21a2 2 0 11-4 0v-.1a1.6 1.6 0 00-2.7-1.1l-.1.1a2 2 0 11-2.8-2.8l.1-.1A1.6 1.6 0 003 15H3a2 2 0 110-4h.1a1.6 1.6 0 001.1-2.7l-.1-.1a2 2 0 112.8-2.8l.1.1A1.6 1.6 0 009.7 4V3a2 2 0 114 0v.1a1.6 1.6 0 002.7 1.1l.1-.1a2 2 0 112.8 2.8l-.1.1a1.6 1.6 0 001.1 2.7H21a2 2 0 110 4h-.1a1.6 1.6 0 00-1.5 1z"/>',
  bell: '<path d="M6 16V11a6 6 0 1112 0v5l2 2H4z"/><path d="M10 20a2 2 0 004 0"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
  chev: '<path d="M6 9l6 6 6-6"/>',
};
window.ICON = (name, extra = "") => `<svg viewBox="0 0 24 24" ${extra}>${I[name]}</svg>`;

(function () {
  const b = document.body;
  const page = b.dataset.page;
  const nav = [
    ["", [["dashboard", "home", "لوحة التحكم"]]],
    ["المبيعات", [["customers", "users", "العملاء"], ["surveys", "ruler", "المعاينات", "4"], ["quotes", "quote", "عروض الأسعار", "7"]]],
    ["الإنتاج", [["workorders", "factory", "أوامر التصنيع", "12"], ["inventory", "box", "المخازن"], ["purchasing", "cart", "المشتريات"]]],
    ["الحسابات", [["treasury", "cash", "الخزينة"]]],
    ["الإعداد", [["library", "layers", "مكتبة القطاعات"], ["users", "shield", "المستخدمين والصلاحيات"], ["settings", "gear", "الإعدادات"]]],
  ];
  const navHtml = nav.map(([g, items]) => (g ? `<div class="nav-group">${g}</div>` : "") + items.map(([id, ic, label, badge]) =>
    `<a class="${id === page ? "active" : ""}">${ICON(ic)}<span>${label}</span>${badge ? `<span class="badge num">${badge}</span>` : ""}</a>`).join("")).join("");
  const sidebar = `<aside class="sidebar">
    <div class="brand"><div class="brand-mark">M</div><div><div class="brand-name">MYTech</div><div class="brand-sub">Solutions</div></div></div>
    <nav class="nav">${navHtml}</nav>
    <div class="sidebar-foot">
      <div class="conn"><span class="dot"></span>متصل بسيرفر المصنع</div>
      <div style="color:#7F92AA;margin-top:4px" class="row"><span class="num">192.168.1.10</span><span style="margin-inline-start:auto" class="num">v0.1.0</span></div>
    </div></aside>`;
  const top = `<header class="topbar">
    <div><div class="crumbs">${b.dataset.crumbs || ""}</div><div class="page-title">${b.dataset.title || ""}</div></div>
    <div class="search">${ICON("search", 'style="width:16px;height:16px;stroke:#8A96A6;fill:none;stroke-width:2"')}<span>بحث عن عميل، عرض سعر، أمر…</span><kbd class="num">Ctrl K</kbd></div>
    <div class="select">الفرع: ${b.dataset.branch || "المصنع الرئيسي"} ${ICON("chev", 'style="width:14px;height:14px;stroke:#667085;fill:none;stroke-width:2"')}</div>
    <div class="icon-btn">${ICON("bell")}<span class="pip"></span></div>
    <div class="user"><div class="avatar">${b.dataset.initial || "أ"}</div><div><b>${b.dataset.user || "أحمد سامي"}</b><small>${b.dataset.role || "مدير"}</small></div></div>
  </header>`;
  const content = b.innerHTML;
  b.innerHTML = `<div class="app">${sidebar}<div class="main">${top}<div class="content">${content}</div></div></div>`;
})();
