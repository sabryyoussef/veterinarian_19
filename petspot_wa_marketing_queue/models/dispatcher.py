# -*- coding: utf-8 -*-
import random
from datetime import timedelta

from odoo import api, fields, models


class PetspotWaMarketingDispatcher(models.AbstractModel):
    _name = "petspot.wa.marketing.dispatcher"
    _description = "WhatsApp Marketing Rate-Limited Dispatcher"

    @api.model
    def cron_process_queue(self, limit=20):
        """Process due queue items with window, spacing, cap, and recheck."""
        settings = self.env["petspot.wa.marketing.settings"].sudo().get_settings()
        if settings.global_pause:
            return 0
        if not settings.in_send_window():
            return 0

        Item = self.env["petspot.wa.marketing.queue.item"].sudo()
        Eligibility = self.env["petspot.wa.marketing.queue.eligibility"].sudo()
        Client = self.env["petspot.wa.marketing.evolution.client"].sudo()
        Consent = self.env["petspot.wa.marketing.consent"].sudo()

        now = fields.Datetime.now()
        # Enforce spacing: if any sent in last spacing_min minutes, wait
        # spacing_min_minutes=0 is allowed in UAT tests (no wait).
        if settings.spacing_min_minutes and settings.spacing_min_minutes > 0:
            recent = Item.search(
                [
                    ("state", "=", "sent"),
                    ("sent_at", ">=", now - timedelta(minutes=settings.spacing_min_minutes)),
                ],
                limit=1,
            )
            if recent:
                return 0

        items = Item.search(
            [
                ("state", "=", "pending"),
                ("scheduled_at", "<=", now),
                ("campaign_id.state", "in", ("approved_scheduled", "sending")),
            ],
            order="scheduled_at, id",
            limit=limit,
        )
        processed = 0
        for item in items:
            campaign = item.campaign_id
            if campaign.state == "approved_scheduled":
                campaign.state = "sending"

            # Reserve cap first (atomic)
            if not settings.reserve_daily_slot():
                break

            item.state = "reserved"
            result = Eligibility.evaluate(
                item.partner_id,
                campaign=campaign,
                template=item.template_id,
                check_pause=True,
                check_instance=True,
                exclude_item=item,
            )
            if not result.get("eligible"):
                settings.release_daily_slot()
                item.write({"state": "skipped", "skip_reason": result.get("reason")})
                self.env["petspot.wa.marketing.event"].sudo().create(
                    {
                        "event_type": "dispatch_skip",
                        "campaign_id": campaign.id,
                        "queue_item_id": item.id,
                        "partner_id": item.partner_id.id,
                        "mobile_normalized": item.mobile_normalized,
                        "note": result.get("reason"),
                    }
                )
                continue

            # No automatic retry of uncertain — mark and pause on transport ambiguity
            send = Client.send_text(item.mobile_normalized, item.rendered_body)
            if send.get("ok"):
                settings.commit_daily_slot()
                item.write(
                    {
                        "state": "sent",
                        "sent_at": fields.Datetime.now(),
                        "evolution_message_id": send.get("message_id"),
                    }
                )
                # stamp last marketing contact
                consent = Consent.search(
                    [
                        ("mobile_normalized", "=", item.mobile_normalized),
                        ("channel", "=", "whatsapp"),
                        ("purpose", "=", "marketing"),
                    ],
                    limit=1,
                )
                if consent:
                    consent.write({"last_marketing_contact_at": fields.Datetime.now()})
                self.env["petspot.wa.marketing.event"].sudo().create(
                    {
                        "event_type": "dispatch",
                        "campaign_id": campaign.id,
                        "queue_item_id": item.id,
                        "partner_id": item.partner_id.id,
                        "mobile_normalized": item.mobile_normalized,
                        "note": f"message_id={send.get('message_id')} mock={send.get('mock')}",
                        "payload": str(send)[:2000],
                    }
                )
                settings.sudo().write(
                    {"rolling_send_count": (settings.rolling_send_count or 0) + 1}
                )
                # schedule next pending with spacing (no catch-up burst)
                lo = max(0, settings.spacing_min_minutes or 0)
                hi = max(lo, settings.spacing_max_minutes or 0)
                delay = random.randint(lo, hi) if hi else 0
                nxt = Item.search(
                    [
                        ("state", "=", "pending"),
                        ("campaign_id", "=", campaign.id),
                        ("id", "!=", item.id),
                    ],
                    order="scheduled_at, id",
                    limit=1,
                )
                if nxt and nxt.scheduled_at <= fields.Datetime.now():
                    nxt.scheduled_at = fields.Datetime.now() + timedelta(minutes=delay)
                processed += 1
                # One message per cron tick respects spacing
                break
            else:
                settings.release_daily_slot()
                # Unknown / fail — no automatic retry
                item.write(
                    {
                        "state": "uncertain" if send.get("error") == "transport" else "failed",
                        "last_error": (send.get("detail") or send.get("error") or "")[:500],
                    }
                )
                fails = (settings.consecutive_delivery_failures or 0) + 1
                settings.sudo().write({"consecutive_delivery_failures": fails})
                self.env["petspot.wa.marketing.event"].sudo().create(
                    {
                        "event_type": "dispatch_fail",
                        "campaign_id": campaign.id,
                        "queue_item_id": item.id,
                        "partner_id": item.partner_id.id,
                        "mobile_normalized": item.mobile_normalized,
                        "note": item.last_error,
                        "payload": str(send)[:2000],
                    }
                )
                if fails >= 2:
                    settings.action_set_global_pause(True, reason="two_consecutive_delivery_failures")
                processed += 1
                break

        # Complete campaigns with no pending/reserved
        for camp in self.env["petspot.wa.marketing.campaign"].sudo().search(
            [("state", "=", "sending")]
        ):
            left = camp.queue_item_ids.filtered(lambda i: i.state in ("pending", "reserved"))
            if not left:
                camp.state = "completed"
        return processed

    @api.model
    def handle_inbound_text(self, mobile_raw, text):
        """Process STOP/وقف/wrong-number style replies for marketing."""
        text_n = (text or "").strip()
        Eligibility = self.env["petspot.wa.marketing.queue.eligibility"]
        mobile = Eligibility.normalize_mobile(mobile_raw) or mobile_raw
        Consent = self.env["petspot.wa.marketing.consent"].sudo()
        Item = self.env["petspot.wa.marketing.queue.item"].sudo()
        settings = self.env["petspot.wa.marketing.settings"].sudo().get_settings()

        lower = text_n.lower()
        is_stop = text_n in ("وقف", "وقف.") or lower in ("stop", "unsubscribe", "إلغاء")
        is_wrong = lower in ("wrong", "wrong number", "رقم غلط", "غلط")

        if is_stop:
            Consent.register_inbound_opt_out_keyword(mobile_raw or mobile, text_n)
            pending = Item.search(
                [
                    ("mobile_normalized", "=", mobile),
                    ("state", "in", ("pending", "reserved")),
                ]
            )
            pending.action_cancel(reason="opt_out_stop")
            settings.sudo().write(
                {"rolling_opt_out_count": (settings.rolling_opt_out_count or 0) + 1}
            )
            self.env["petspot.wa.marketing.event"].sudo().create(
                {
                    "event_type": "opt_out",
                    "mobile_normalized": mobile,
                    "note": f"keyword={text_n}",
                }
            )
            self._maybe_pause_opt_out_rate(settings)
            return {"handled": "opt_out", "cancelled": len(pending)}

        if is_wrong:
            consent = Consent.search(
                [
                    ("mobile_normalized", "=", mobile),
                    ("channel", "=", "whatsapp"),
                    ("purpose", "=", "marketing"),
                ],
                limit=1,
            )
            if consent:
                consent.action_mark_wrong_number(source="whatsapp_inbound", notes=text_n)
            pending = Item.search(
                [
                    ("mobile_normalized", "=", mobile),
                    ("state", "in", ("pending", "reserved")),
                ]
            )
            pending.action_cancel(reason="wrong_number")
            self.env["petspot.wa.marketing.event"].sudo().create(
                {
                    "event_type": "wrong_number",
                    "mobile_normalized": mobile,
                    "note": text_n,
                }
            )
            return {"handled": "wrong_number", "cancelled": len(pending)}

        return {"handled": False}

    @api.model
    def _maybe_pause_opt_out_rate(self, settings):
        sends = settings.rolling_send_count or 0
        opts = settings.rolling_opt_out_count or 0
        # Rolling window approximation: last 20 sends
        window = min(max(sends, 1), 20)
        if sends >= 20 and (opts / 20.0) > 0.10:
            settings.action_set_global_pause(True, reason="opt_out_rate_above_10pct_rolling_20")
        elif sends >= window and window >= 10 and (opts / float(window)) > 0.10:
            settings.action_set_global_pause(True, reason="opt_out_rate_above_10pct")

    @api.model
    def cron_health_check(self):
        settings = self.env["petspot.wa.marketing.settings"].sudo().get_settings()
        if settings.mock_send:
            return True
        state = self.env["petspot.wa.marketing.evolution.client"].connection_state()
        if state.get("state") != "open":
            settings.action_set_global_pause(True, reason=f"evolution_disconnect:{state.get('state')}")
            self.env["petspot.wa.marketing.event"].sudo().create(
                {"event_type": "health", "note": str(state)[:500]}
            )
        return True
