/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

publicWidget.registry.PetspotShopFilters = publicWidget.Widget.extend({
    selector: ".o_petspot_sidebar",
    events: {
        "click .o_petspot_filter_toggle": "_onToggle",
    },

    _onToggle(ev) {
        const btn = ev.currentTarget;
        const drawer = this.el.querySelector("#o_petspot_filter_drawer");
        if (!drawer) {
            return;
        }
        const open = drawer.classList.toggle("is-open");
        btn.setAttribute("aria-expanded", open ? "true" : "false");
    },
});

export default publicWidget.registry.PetspotShopFilters;
