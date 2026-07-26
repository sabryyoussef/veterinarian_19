/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

publicWidget.registry.PetspotVariantSelector = publicWidget.Widget.extend({
    selector: ".o_petspot_card_body",
    events: {
        "click .o_petspot_pack_btn": "_onSelectPack",
        "click .o_petspot_add_cart": "_onAddCart",
        "click .o_petspot_notify, .o_petspot_request": "_onNotify",
    },

    start() {
        this.payload = {};
        try {
            this.payload = JSON.parse(this.el.dataset.payload || "{}");
        } catch (_e) {
            this.payload = {};
        }
        return this._super(...arguments);
    },

    _variantById(id) {
        return (this.payload.variants || []).find((v) => String(v.id) === String(id));
    },

    _onSelectPack(ev) {
        const btn = ev.currentTarget;
        const variant = this._variantById(btn.dataset.variantId);
        if (!variant) {
            return;
        }
        this.el.querySelectorAll(".o_petspot_pack_btn").forEach((el) => {
            el.classList.toggle("is-selected", el === btn);
            el.setAttribute("aria-pressed", el === btn ? "true" : "false");
        });
        this._renderVariant(variant);
    },

    _renderVariant(v) {
        const price = this.el.querySelector('[data-role="price"]');
        const avail = this.el.querySelector('[data-role="availability"]');
        const expiry = this.el.querySelector('[data-role="expiry"]');
        const cta = this.el.querySelector('[data-role="cta"]');
        if (price) {
            price.textContent = v.pricing_ready && v.formatted_price ? v.formatted_price : "Price pending";
        }
        if (avail) {
            avail.textContent = v.availability_label || "Contact us";
        }
        if (expiry) {
            expiry.textContent = v.expiry_display || "";
        }
        if (!cta) {
            return;
        }
        let html = `<span class="text-muted small">Unavailable</span>`;
        if (v.add_to_cart_allowed) {
            html = `<button type="button" class="btn btn-primary o_petspot_add_cart" data-product-id="${v.id}">Add to Cart</button>`;
        } else if (v.notify_me_allowed) {
            html = `<button type="button" class="btn btn-outline-secondary o_petspot_notify" data-product-id="${v.id}" data-request-type="notify">Notify Me</button>`;
        } else if (v.available_on_request) {
            html = `<button type="button" class="btn btn-outline-secondary o_petspot_request" data-product-id="${v.id}" data-request-type="request">Available on Request</button>`;
        }
        cta.innerHTML = html;
    },

    async _onAddCart(ev) {
        const productId = parseInt(ev.currentTarget.dataset.productId, 10);
        if (!productId) {
            return;
        }
        try {
            await this.rpc("/shop/cart/add", {
                product_id: productId,
                product_template_id: this.payload.id,
                quantity: 1,
            });
            window.location.href = "/shop/cart";
        } catch (err) {
            const msg = (err && err.data && err.data.message) || (err && err.message) || "Could not add to cart.";
            window.alert(msg);
        }
    },

    async _onNotify(ev) {
        const productId = parseInt(ev.currentTarget.dataset.productId, 10);
        const requestType = ev.currentTarget.dataset.requestType || "notify";
        const email = window.prompt("Enter your email for updates:");
        if (!email) {
            return;
        }
        const result = await this.rpc("/petspot/shop/notify", {
            product_id: productId,
            email,
            request_type: requestType,
        });
        if (result && result.ok) {
            window.alert("Thank you — we recorded your request.");
        } else {
            window.alert("Could not save your request. Please try again.");
        }
    },
});

export default publicWidget.registry.PetspotVariantSelector;
