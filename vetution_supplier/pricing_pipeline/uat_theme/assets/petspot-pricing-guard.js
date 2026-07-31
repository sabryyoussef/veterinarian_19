(() => {
  const WA = '201000059085';
  const msgFor = () => {
    const ar = (document.documentElement.lang || '').toLowerCase().startsWith('ar');
    return ar
      ? { msg: 'السعر غير متاح حالياً', cta: 'تواصل عبر واتساب' }
      : { msg: 'Price unavailable', cta: 'Contact us on WhatsApp' };
  };
  const blockedIds = () => (window.__PETSPOT_BLOCKED_VARIANT_IDS || []).map(String);
  const isBlockedId = (id) => blockedIds().includes(String(id));
  const deny = () => {
    const t = msgFor();
    return new Response(
      JSON.stringify({ status: 422, message: t.msg, description: t.msg, petspot_blocked: true }),
      { status: 422, headers: { 'Content-Type': 'application/json' } }
    );
  };
  const origFetch = window.fetch.bind(window);
  window.fetch = async (input, init = {}) => {
    try {
      const url = typeof input === 'string' ? input : (input && input.url) || '';
      if (url.includes('/cart/add')) {
        const ids = [];
        const body = init && init.body;
        if (typeof body === 'string') {
          try {
            const j = JSON.parse(body);
            if (j.id) ids.push(String(j.id));
            (j.items || []).forEach((i) => ids.push(String(i.id)));
          } catch (_) {
            const p = new URLSearchParams(body);
            if (p.get('id')) ids.push(p.get('id'));
          }
        }
        if (ids.some(isBlockedId)) return deny();
      }
    } catch (e) {}
    return origFetch(input, init);
  };
  document.addEventListener(
    'submit',
    (e) => {
      try {
        const form = e.target;
        if (!form || !form.action) return;
        if (!String(form.action).includes('/cart/add')) return;
        const idInput = form.querySelector('[name="id"]');
        if (idInput && isBlockedId(idInput.value)) {
          e.preventDefault();
          e.stopPropagation();
          alert(msgFor().msg);
        }
      } catch (_) {}
    },
    true
  );
  window.PetSpotPricingGuard = { isBlockedId, msgFor, WA };
})();
