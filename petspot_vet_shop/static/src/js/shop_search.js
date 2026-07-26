/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

publicWidget.registry.PetspotShopSearch = publicWidget.Widget.extend({
    selector: ".o_petspot_search_chrome",
    events: {
        "input .o_petspot_live_search": "_onInput",
        "keydown .o_petspot_live_search": "_onKeydown",
    },

    start() {
        this._timer = null;
        this.suggestEl = this.el.querySelector("#o_petspot_suggest");
        return this._super(...arguments);
    },

    _onInput(ev) {
        clearTimeout(this._timer);
        const term = ev.currentTarget.value.trim();
        if (term.length < 2) {
            this._hide();
            return;
        }
        this._timer = setTimeout(() => this._fetch(term), 220);
    },

    _onKeydown(ev) {
        if (ev.key === "Escape") {
            this._hide();
        }
        if (ev.key === "Enter") {
            const term = ev.currentTarget.value.trim();
            if (term) {
                window.location.href = `/shop?search=${encodeURIComponent(term)}`;
            }
        }
    },

    async _fetch(term) {
        const data = await rpc("/petspot/shop/suggest", {term, mode: "all", limit: 8});
        if (!this.suggestEl) {
            return;
        }
        const parts = [];
        (data.products || []).forEach((p) => {
            const name = this._escape(p.name || "");
            const brand = this._escape(p.brand || "");
            const url = this._escapeAttr(p.url || "#");
            const img = this._escapeAttr(p.image_url || "");
            parts.push(
                `<a class="o_petspot_suggest_item" role="option" href="${url}">` +
                `<img src="${img}" alt="" width="40" height="40"/>` +
                `<span><strong>${name}</strong>${brand ? `<br/><small>${brand}</small>` : ""}</span></a>`
            );
        });
        (data.brands || []).forEach((b) => {
            const name = this._escape(b.name || "");
            const url = this._escapeAttr(b.url || "#");
            parts.push(`<a class="o_petspot_suggest_item" role="option" href="${url}">Brand: ${name}</a>`);
        });
        if (!parts.length) {
            this._hide();
            return;
        }
        this.suggestEl.innerHTML = parts.join("");
        this.suggestEl.hidden = false;
    },

    _escape(text) {
        return String(text)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    },

    _escapeAttr(text) {
        return this._escape(text).replace(/'/g, "&#39;");
    },

    _hide() {
        if (this.suggestEl) {
            this.suggestEl.hidden = true;
            this.suggestEl.innerHTML = "";
        }
    },
});

export default publicWidget.registry.PetspotShopSearch;
