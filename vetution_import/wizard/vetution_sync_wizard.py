# -*- coding: utf-8 -*-

from odoo import api, fields, models


class VetutionSyncWizard(models.TransientModel):
    _name = "vetution.sync.wizard"
    _description = "Sync Catalog from Vetution"

    page_from = fields.Integer(
        string="Products page from",
        default=1,
        help="Inclusive. Leave as 1 for full sync.",
    )
    page_to = fields.Integer(
        string="Products page to",
        help="Inclusive. Empty = last page (62). Use 1 for a debug run.",
    )
    brand_page_from = fields.Integer(string="Brands page from", default=1)
    brand_page_to = fields.Integer(
        string="Brands page to",
        help="Empty = all brand pages (~13).",
    )
    product_slug = fields.Char(
        string="Single product slug",
        help="If set, sync only this product detail (ignores page range).",
    )
    only_missing = fields.Boolean(
        string="Only missing products",
        help="Skip templates that already have a vetution_id.",
    )
    import_prices = fields.Boolean(
        string="Import prices",
        default=False,
        help="Only writes list_price when API price > 0 and show is true. "
        "Default off — anonymous API returns zeros.",
    )
    publish_products = fields.Boolean(
        string="Publish on website",
        default=False,
        help="If enabled, set is_published=True on create/update. Default off for safety.",
    )
    log_text = fields.Text(string="Log", readonly=True)
    state = fields.Selection(
        selection=[
            ("draft", "Ready"),
            ("done", "Done"),
        ],
        default="draft",
    )

    def _append_log(self, message):
        self.ensure_one()
        stamp = fields.Datetime.now()
        line = f"[{stamp}] {message}"
        self.log_text = (self.log_text + "\n" + line) if self.log_text else line

    def _options(self):
        self.ensure_one()
        return {
            "page_from": self.page_from or 1,
            "page_to": self.page_to or None,
            "brand_page_from": self.brand_page_from or 1,
            "brand_page_to": self.brand_page_to or None,
            "slug": (self.product_slug or "").strip() or None,
            "only_missing": self.only_missing,
            "import_prices": self.import_prices,
            "publish_products": self.publish_products,
        }

    def _reload(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_sync_taxonomy(self):
        self.ensure_one()
        self._append_log("=== Sync taxonomy ===")
        opts = self._options()
        self.env["vetution.sync"].sync_taxonomy(
            wizard=self,
            brand_page_from=opts["brand_page_from"],
            brand_page_to=opts["brand_page_to"],
        )
        self.state = "done"
        return self._reload()

    def action_sync_products(self):
        self.ensure_one()
        self._append_log("=== Sync products ===")
        opts = self._options()
        self.env["vetution.sync"].sync_products(
            wizard=self,
            page_from=opts["page_from"],
            page_to=opts["page_to"],
            slug=opts["slug"],
            options=opts,
        )
        self.state = "done"
        return self._reload()

    def action_sync_cross_links(self):
        self.ensure_one()
        self._append_log("=== Sync cross-links ===")
        self.env["vetution.sync"].sync_cross_links(wizard=self)
        self.state = "done"
        return self._reload()

    def action_sync_full(self):
        self.ensure_one()
        self._append_log("=== Full sync ===")
        self.env["vetution.sync"].sync_full(wizard=self, options=self._options())
        self.state = "done"
        return self._reload()
