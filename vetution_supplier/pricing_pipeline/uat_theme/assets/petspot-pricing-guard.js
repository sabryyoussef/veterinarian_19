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

  function scrubCardLe1() {
    try {
      const nodes = document.querySelectorAll('.petspot-product-card__price');
      const t = msgFor();
      nodes.forEach((el) => {
        const txt = (el.textContent || '').replace(/\s+/g, ' ').trim();
        if (/^LE\s*1([.,]00)?$/i.test(txt) || /^E£\s*1([.,]00)?$/i.test(txt) || /^\s*1([.,]00)?\s*LE$/i.test(txt)) {
          el.innerHTML =
            '<span class="petspot-price-unavailable__msg">' +
            t.msg +
            '</span> <a class="petspot-price-unavailable__wa" href="https://wa.me/' +
            WA +
            '" target="_blank" rel="noopener">' +
            t.cta +
            '</a>';
          el.setAttribute('data-petspot-pricing-blocked', 'true');
        }
      });
    } catch (e) {}
  }
  document.addEventListener('DOMContentLoaded', scrubCardLe1);
  new MutationObserver(() => scrubCardLe1()).observe(document.documentElement, {
    childList: true,
    subtree: true,
  });
})();
