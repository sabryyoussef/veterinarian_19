# -*- coding: utf-8 -*-
import json
import logging
import re
from datetime import timedelta

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class SurveyUserInput(models.Model):
    _inherit = "survey.user_input"

    petspot_campaign_id = fields.Many2one("petspot.campaign", index=True, copy=False)
    petspot_campaign_step_id = fields.Many2one("petspot.campaign.step", copy=False)
    loyalty_card_id = fields.Many2one("loyalty.card", copy=False, readonly=True)
    reward_sent = fields.Boolean(default=False, copy=False, readonly=True)
    reward_phone = fields.Char(readonly=True, copy=False)
    reward_partner_id = fields.Many2one("res.partner", readonly=True, copy=False)
    crm_lead_id = fields.Many2one("crm.lead", readonly=True, copy=False)
    portal_booking_token_id = fields.Many2one(
        "petspot.portal.token", copy=False, readonly=True, string="Booking portal token"
    )

    def _mark_done(self):
        super()._mark_done()
        self._petspot_process_campaign_rewards()

    def _petspot_process_campaign_rewards(self):
        for user_input in self.filtered(
            lambda u: u.state == "done" and not u.test_entry
        ):
            try:
                user_input._petspot_handle_campaign_completion()
            except Exception:
                _logger.exception(
                    "PetSpot campaign reward failed for user_input %s", user_input.id
                )

    def _petspot_handle_campaign_completion(self):
        self.ensure_one()
        step = self.petspot_campaign_step_id or self.survey_id.petspot_campaign_step_id
        campaign = self.petspot_campaign_id or (step.campaign_id if step else False)
        if not step and self.survey_id:
            step = self.env["petspot.campaign.step"].search(
                [("survey_id", "=", self.survey_id.id)], limit=1
            )
            campaign = step.campaign_id if step else campaign

        if campaign and not self.petspot_campaign_id:
            self.petspot_campaign_id = campaign.id
        if step and not self.petspot_campaign_step_id:
            self.petspot_campaign_step_id = step.id

        self._petspot_sync_crm_lead(campaign, step)

        if not step or not step.issue_reward:
            return
        requires_pass = step.reward_discount_percent < 15
        if requires_pass and not self.scoring_success:
            return
        if self.loyalty_card_id or self.reward_sent:
            return

        phone = self._petspot_extract_phone()
        if phone and campaign:
            norm = campaign._normalize_phone(phone)
            duplicate = self.search(
                [
                    ("petspot_campaign_id", "=", campaign.id),
                    ("loyalty_card_id", "!=", False),
                    ("reward_phone", "=", norm),
                    ("id", "!=", self.id),
                ],
                limit=1,
            )
            if duplicate:
                _logger.info(
                    "Skipping duplicate reward for phone %s campaign %s",
                    norm,
                    campaign.code,
                )
                return

        program = campaign._get_reward_program_for_step(step) if campaign else step.reward_program_id
        if not program:
            return

        partner = self.partner_id or self._petspot_find_or_create_partner()
        expiration = fields.Date.today() + timedelta(days=campaign.discount_validity_days or 30)
        card = self.env["loyalty.card"].sudo().create(
            {
                "program_id": program.id,
                "partner_id": partner.id if partner else False,
                "points": 1,
                "expiration_date": expiration,
                "petspot_campaign_id": campaign.id,
                "survey_user_input_id": self.id,
            }
        )
        self.write(
            {
                "loyalty_card_id": card.id,
                "reward_sent": True,
                "reward_phone": campaign._normalize_phone(phone) if phone else False,
                "reward_partner_id": partner.id if partner else False,
            }
        )
        self.env["loyalty.history"].sudo().create(
            {
                "description": _("PetSpot campaign reward — %s") % campaign.name,
                "card_id": card.id,
                "issued": 1,
            }
        )
        self._petspot_send_reward_notifications(campaign, step, card, partner, phone)

    def _petspot_create_booking_token(self, campaign, step, card, partner, phone):
        """Mint clinic portal booking link with discount pre-filled."""
        self.ensure_one()
        if "petspot.portal.token" not in self.env:
            return self.env["petspot.portal.token"]
        Token = self.env["petspot.portal.token"].sudo()
        if self.portal_booking_token_id and self.portal_booking_token_id.state == "open":
            return self.portal_booking_token_id
        existing = Token.search(
            [
                ("loyalty_card_id", "=", card.id),
                ("state", "=", "open"),
            ],
            limit=1,
            order="id desc",
        )
        if existing:
            self.portal_booking_token_id = existing.id
            return existing
        contact = self._petspot_extract_contact()
        token = Token.create_patient_token(
            {
                "prefill_owner_name": contact["name"] or (partner.name if partner else ""),
                "prefill_phone": phone or contact["phone"] or "",
                "prefill_pet_name": contact.get("pet_type") or "",
                "prefill_discount_code": card.code,
                "prefill_discount_percent": step.reward_discount_percent or 10,
                "loyalty_card_id": card.id,
                "petspot_campaign_id": campaign.id,
                "survey_user_input_id": self.id,
            }
        )
        self.portal_booking_token_id = token.id
        return token

    def _petspot_extract_contact(self):
        self.ensure_one()
        name = self.nickname or ""
        email = self.email or ""
        phone = ""
        pet_type = ""
        for line in self.user_input_line_ids:
            question = line.question_id
            role = question.petspot_field_role
            if role == "name" and line.value_char_box:
                name = line.value_char_box
            elif role == "phone" and line.value_char_box:
                phone = line.value_char_box
            elif role == "email" and line.value_char_box:
                email = line.value_char_box
            elif role == "pet_type" and line.value_char_box:
                pet_type = line.value_char_box
            elif not role:
                title = (question.title or "").lower()
                if "phone" in title or "موبايل" in title or "واتساب" in title:
                    phone = phone or (line.value_char_box or "")
                elif "name" in title or "اسم" in title:
                    name = name or (line.value_char_box or "")
                elif "email" in title or "بريد" in title:
                    email = email or (line.value_char_box or "")
        return {"name": name.strip(), "email": email.strip(), "phone": phone.strip(), "pet_type": pet_type.strip()}

    def _petspot_extract_phone(self):
        return self._petspot_extract_contact()["phone"]

    def _petspot_find_or_create_partner(self):
        self.ensure_one()
        contact = self._petspot_extract_contact()
        Partner = self.env["res.partner"].sudo()
        if self.partner_id:
            return self.partner_id
        domain = []
        if contact["email"]:
            domain = [("email", "=ilike", contact["email"])]
        elif contact["phone"]:
            norm = re.sub(r"\D", "", contact["phone"])
            domain = [("phone", "ilike", norm[-10:])]
        partner = Partner.search(domain, limit=1) if domain else Partner.browse()
        if not partner and (contact["name"] or contact["phone"] or contact["email"]):
            partner = Partner.create(
                {
                    "name": contact["name"] or contact["phone"] or contact["email"] or _("Campaign Guest"),
                    "email": contact["email"] or False,
                    "phone": contact["phone"] or False,
                }
            )
        return partner

    def _petspot_sync_crm_lead(self, campaign, step):
        self.ensure_one()
        contact = self._petspot_extract_contact()
        if not contact["phone"] and not contact["email"]:
            return self.crm_lead_id

        tag = self.env.ref(
            "petspot_campaign_rewards.crm_tag_petspot_campaign",
            raise_if_not_found=False,
        )
        Lead = self.env["crm.lead"].sudo()
        lead = self.crm_lead_id
        if not lead and contact["phone"]:
            norm = re.sub(r"\D", "", contact["phone"])
            lead = Lead.search([("phone", "ilike", norm[-10:])], limit=1)
        if not lead and contact["email"]:
            lead = Lead.search([("email_from", "=ilike", contact["email"])], limit=1)

        desc = _(
            "Campaign: %(campaign)s\nStep: %(step)s\nScore: %(score).0f%%\nPet type: %(pet)s"
        ) % {
            "campaign": campaign.name if campaign else "-",
            "step": step.title if step else "-",
            "score": self.scoring_percentage or 0,
            "pet": contact["pet_type"] or "-",
        }
        vals = {
            "name": contact["name"] or _("PetSpot Campaign Lead"),
            "contact_name": contact["name"] or False,
            "email_from": contact["email"] or False,
            "phone": contact["phone"] or False,
            "description": desc,
            "petspot_campaign_id": campaign.id if campaign else False,
        }
        if lead:
            lead.write({k: v for k, v in vals.items() if v})
        else:
            lead = Lead.create(vals)
        if tag:
            lead.write({"tag_ids": [(4, tag.id)]})
        if not self.crm_lead_id:
            self.crm_lead_id = lead.id
        return lead

    def _petspot_send_reward_notifications(self, campaign, step, card, partner, phone):
        self.ensure_one()
        booking_token = self._petspot_create_booking_token(campaign, step, card, partner, phone)
        book_url = booking_token.access_url if booking_token else ""
        ICP = self.env["ir.config_parameter"].sudo()
        base_url = ICP.get_param("web.base.url", "").rstrip("/")
        reward_url = f"{base_url}/campaign/reward/{self.access_token}"
        expiry = card.expiration_date.strftime("%Y-%m-%d") if card.expiration_date else "-"
        discount = step.reward_discount_percent or 10
        book_line = ""
        if book_url:
            book_line = _(
                "\n📅 Book your appointment now:\n%(book)s\n"
            ) % {"book": book_url}
        message = _(
            "🎉 Congratulations from PetSpot El Sahel!\n\n"
            "You passed: %(step)s\n"
            "Your discount code: %(code)s\n"
            "Discount: %(discount)s%% off clinic services\n"
            "Valid until: %(expiry)s\n\n"
            "Redeem at Amwaj 1 or Haram — show this code at reception.\n"
            "📞 Call center 01201568888 | Amwaj 01280833332 | Haram 01000059085\n"
            "%(book)s"
            "🌐 %(url)s"
        ) % {
            "step": step.title,
            "code": card.code,
            "discount": discount,
            "expiry": expiry,
            "book": book_line,
            "url": reward_url,
        }

        contact = self._petspot_extract_contact()
        email = contact["email"] or (partner.email if partner else "")
        if email:
            template = self.env.ref(
                "petspot_campaign_rewards.mail_template_campaign_reward",
                raise_if_not_found=False,
            )
            if template:
                template.with_context(
                    discount_code=card.code,
                    reward_url=reward_url,
                    book_url=book_url,
                    discount_percent=discount,
                    expiry_date=expiry,
                ).send_mail(self.id, force_send=True, email_layout_xmlid="mail.mail_notification_light")

        send_wa = ICP.get_param("petspot_campaign.send_whatsapp_rewards", "True") == "True"
        wa_phone = phone or contact["phone"] or (partner.phone if partner else "")
        if send_wa and wa_phone:
            self._petspot_queue_whatsapp(wa_phone, message, card)

    def _petspot_queue_whatsapp(self, phone, text, card):
        ICP = self.env["ir.config_parameter"].sudo()
        evo_url = ICP.get_param("integration_bridge.evolution_url", "http://127.0.0.1:8080").rstrip("/")
        evo_key = ICP.get_param("integration_bridge.evolution_key", "")
        evo_instance = ICP.get_param("integration_bridge.evolution_instance", "sabry min")
        clean = re.sub(r"\D", "", phone or "")
        if clean.startswith("0"):
            clean = "20" + clean[1:]
        elif clean and not clean.startswith("20"):
            clean = "20" + clean
        endpoint = f"{evo_url}/message/sendText/{evo_instance}"
        self.env["integration.outbound.queue"].sudo().create_outbound_message(
            name=_("Campaign reward → %s") % clean,
            platform="evolution",
            endpoint_url=endpoint,
            payload={"number": clean, "text": text, "options": {"delay": 1000}},
            headers={"apikey": evo_key, "Content-Type": "application/json"},
            related_model="loyalty.card",
            related_res_id=card.id,
            priority=8,
        )
