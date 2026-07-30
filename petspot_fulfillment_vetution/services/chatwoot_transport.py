# -*- coding: utf-8 -*-
"""Chatwoot transport for customer messaging (Phase 15B — mock by default).

Live HTTP calls are never implemented in this module. ICP
`petspot_fulfillment_vetution.chatwoot_transport` must stay `mock`; if it is
ever set to `live` (and force_mock is disabled), send_template() raises
rather than attempting any network call, so the module can never
accidentally message a real customer.

Two calling conventions are supported for compatibility across callers:
  ChatwootTransport(env).send_template(inquiry, template_key, context_dict={...})
  ChatwootTransport(env, force_mock=True).send_template(
      inquiry=inquiry, template_code="...", idempotency_key="...", context={...}
  )
Idempotency key defaults to inquiry_id + template_key + sha256(payload)[:32]
when not explicitly supplied.
"""

from __future__ import annotations

from odoo.exceptions import UserError


class ChatwootTransport:
    def __init__(self, env, force_mock=True):
        self.env = env
        self.force_mock = force_mock

    def send_template(
        self,
        inquiry,
        template_key=None,
        context_dict=None,
        *,
        template_code=None,
        idempotency_key=None,
        context=None,
        lang=None,
        case=None,
    ):
        template_key = template_key or template_code
        if not template_key:
            raise UserError("send_template requires a template_key/template_code.")

        Log = self.env["petspot.vetution.message.log"]
        Template = self.env["petspot.vetution.message.template"]

        ctx = dict(context_dict or context or {})
        resolved_lang = lang or ctx.get("lang") or "en"
        if resolved_lang not in ("en", "ar"):
            resolved_lang = "en"

        payload_hash = Log.hash_payload(ctx)
        if not idempotency_key:
            idempotency_key = Log.build_idempotency_key(inquiry.id, template_key, payload_hash)

        existing = Log.search([("idempotency_key", "=", idempotency_key)], limit=1)
        if existing:
            return existing

        ICP = self.env["ir.config_parameter"].sudo()
        transport_mode = (
            ICP.get_param("petspot_fulfillment_vetution.chatwoot_transport", "mock") or "mock"
        ).strip().lower()
        if transport_mode == "live" and not self.force_mock:
            raise UserError(
                "Live Chatwoot transport is not implemented in this module. "
                "Keep ICP petspot_fulfillment_vetution.chatwoot_transport=mock."
            )

        ctx.setdefault("sku", getattr(inquiry, "default_code", "") or "")
        ctx.setdefault("order", getattr(inquiry, "name", "") or "")
        ctx.setdefault("price", ctx.get("product_price") or ctx.get("order_total") or "")
        ctx.setdefault("tracking", ctx.get("tracking_number") or "")
        ctx.setdefault("eta", "")

        case_id = case.id if case else (inquiry.case_id.id if getattr(inquiry, "case_id", False) else False)
        vals = {
            "name": f"MSG/{template_key}/{inquiry.id}",
            "inquiry_id": inquiry.id,
            "case_id": case_id,
            "template_key": template_key,
            "lang": resolved_lang,
            "channel": "chatwoot",
            "idempotency_key": idempotency_key,
            "payload_hash": payload_hash,
            "transport": "mock",
        }
        try:
            vals["body_text"] = Template.render(template_key, resolved_lang, ctx)
            vals["state"] = "sent"
            vals["external_message_id"] = f"mock-{idempotency_key}"
            return Log.create(vals)
        except UserError as err:
            vals["body_text"] = ""
            vals["state"] = "failed"
            vals["error"] = str(err)
            Log.create(vals)
            raise
