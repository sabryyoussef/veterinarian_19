# -*- coding: utf-8 -*-
"""Redirect mistaken /odoo/web/database/* URLs to real database routes.

Moved out of ``linkedin_connector`` so that addon is not loaded in
``server_wide_modules`` (which pins an old Python copy of models until process
restart). This tiny module stays server-wide; list it in ``server_wide_modules``
instead of ``linkedin_connector``.

The web client is served under ``/odoo/<path>``. If someone concatenates that
prefix with ``/web/database/...`` (e.g. ``/odoo/web/database/m``), the SPA
route would handle the request instead of the database manager or selector.
These endpoints 303-redirect to the canonical ``/web/database/...`` URLs.
"""

from odoo import http
from odoo.http import request


class DatabaseUrlCompat(http.Controller):
    @http.route("/odoo/web/database/selector", type="http", auth="none", readonly=True)
    def redirect_selector(self):
        return request.redirect("/web/database/selector", 303)

    @http.route(
        ["/odoo/web/database/manager", "/odoo/web/database/m"],
        type="http",
        auth="none",
        readonly=True,
    )
    def redirect_manager(self):
        return request.redirect("/web/database/manager", 303)
