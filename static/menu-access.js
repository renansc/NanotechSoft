(() => {
  const element = document.getElementById('menuAccessState');
  if (!element) return;
  const items = JSON.parse(element.textContent);
  if (!items.length) return;
  function destination(value) {
    const url = new URL(value, location.origin);
    let path = url.pathname.replace(/\/$/, '').replace('/original', '').replace('/apps/riob/embed', '/apps/riob') || '/';
    const query = new URLSearchParams([...url.searchParams].filter(([key]) => ['view', 'secao', 'painel', 'visao'].includes(key)).sort());
    if (path === '/apps/chamados' && !query.has('view')) query.set('view', 'chamados');
    if (path === '/apps/zap/settings' && !query.has('secao')) query.set('secao', 'estados');
    if (path === '/apps/riob-email/riob' && !query.has('painel')) query.set('painel', 'resumo');
    const hash = path === '/apps/tecnologia' && url.hash === '#backup' ? '#backup-visao' : url.hash;
    return path + (query.size ? '?' + query : '') + (hash || (['/apps/tecnologia', '/apps/riob'].includes(path) ? '#dashboard' : path === '/config' ? '#minha-conta' : ''));
  }
  const rules = new Map(items.map(item => [destination(item.url), item.allowed]));
  function permitted(url) { return rules.get(destination(url)) !== false; }
  window.nanotechMenuAllowed = permitted;
  function guard() {
    const blocked = !permitted(location.href);
    document.documentElement.classList.toggle('menu-access-blocked', blocked);
    let notice = document.getElementById('menuAccessDenied');
    if (!notice) {
      notice = document.createElement('p');
      notice.id = 'menuAccessDenied';
      notice.setAttribute('role', 'alert');
      notice.textContent = 'Este item do menu nao esta liberado para seu usuario.';
      element.before(notice);
    }
    notice.hidden = !blocked;
    return !blocked;
  }
  document.addEventListener('click', event => {
    const link = event.target.closest('a[href]');
    if (link && new URL(link.href).origin === location.origin && !permitted(link.href)) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);
  window.addEventListener('hashchange', event => { if (!guard()) event.stopImmediatePropagation(); }, true);
  window.addEventListener('popstate', guard, true);
  window.addEventListener('nanotech:navigation', guard, true);
  for (const method of ['pushState', 'replaceState']) {
    const original = history[method];
    history[method] = function (...args) {
      const result = original.apply(this, args);
      guard();
      return result;
    };
  }
  guard();
})();
