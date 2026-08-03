# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request, content_disposition
import base64


class SabryDeveloperWebsite(http.Controller):
    """Path-prefixed routes so PetSpot (/) is never hijacked on shared domain."""

    def _render(self, template):
        # Do not reassign request.website (multi-company ACL can 403 public users).
        # Templates use sabry_layout which omits PetSpot chrome.
        return request.render(template, {})

    @http.route(["/sabry", "/sabry/home"], type="http", auth="public", website=True)
    def sabry_home(self, **kwargs):
        return self._render("sabry_developer_website.page_home")

    @http.route(["/sabry/about"], type="http", auth="public", website=True)
    def sabry_about(self, **kwargs):
        return self._render("sabry_developer_website.page_about")

    @http.route(["/sabry/services"], type="http", auth="public", website=True)
    def sabry_services(self, **kwargs):
        return self._render("sabry_developer_website.page_services")

    @http.route(["/sabry/portfolio"], type="http", auth="public", website=True)
    def sabry_portfolio(self, **kwargs):
        return self._render("sabry_developer_website.page_portfolio")

    @http.route(["/sabry/experience"], type="http", auth="public", website=True)
    def sabry_experience(self, **kwargs):
        return self._render("sabry_developer_website.page_experience")

    @http.route(["/sabry/cv"], type="http", auth="public", website=True)
    def sabry_cv(self, **kwargs):
        return self._render("sabry_developer_website.page_cv")

    @http.route(["/sabry/contact"], type="http", auth="public", website=True)
    def sabry_contact(self, **kwargs):
        return self._render("sabry_developer_website.page_contact")

    @http.route(
        ["/sabry/contact/submit"],
        type="http",
        auth="public",
        website=True,
        methods=["POST"],
        csrf=False,
    )
    def sabry_contact_submit(self, **post):
        sabry = request.env.ref(
            "sabry_odoo_company_isolation.company_sabry_odoo_development",
            raise_if_not_found=False,
        )
        Lead = request.env["crm.lead"].sudo()
        team = request.env["crm.team"].sudo().search(
            [("name", "=", "Odoo Partner Outreach")], limit=1
        )
        vals = {
            "name": post.get("name") or "Sabry website contact",
            "contact_name": post.get("contact_name"),
            "email_from": post.get("email_from"),
            "partner_name": post.get("partner_name"),
            "description": post.get("description"),
            "type": "lead",
            "user_id": False,
        }
        if sabry:
            vals["company_id"] = sabry.id
        if team:
            vals["team_id"] = team.id
        lead_env = Lead.sudo()
        if sabry:
            lead_env = lead_env.with_company(sabry).with_context(
                allowed_company_ids=sabry.ids,
                mail_create_nosubscribe=True,
            )
        lead_env.create(vals)
        return request.redirect("/sabry/contact?sent=1")

    @http.route(["/sabry/cv/download"], type="http", auth="public", website=True)
    def sabry_cv_download(self, **kwargs):
        Attachment = request.env["ir.attachment"].sudo()
        att = Attachment.search(
            [("name", "=", "Sabry_Youssef_CV.pdf"), ("mimetype", "=", "application/pdf")],
            order="id desc",
            limit=1,
        )
        if not att or not att.datas:
            return request.not_found()
        content = base64.b64decode(att.datas)
        headers = [
            ("Content-Type", "application/pdf"),
            ("Content-Length", len(content)),
            ("Content-Disposition", content_disposition("Sabry_Youssef_CV.pdf")),
        ]
        return request.make_response(content, headers=headers)
