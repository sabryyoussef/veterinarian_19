# -*- coding: utf-8 -*-
import json
import logging
import urllib.error
import urllib.request

from odoo import api, fields, models, _
from odoo.exceptions import UserError, AccessError

from .petspot_cta_parser import normalize_eg_phone

_logger = logging.getLogger(__name__)


class PetspotAvailabilityInquiry(models.Model):
    _name = "petspot.availability.inquiry"
    _description = "PetSpot Availability Inquiry (WhatsApp / Manual)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(required=True, copy=False, default="New")
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("review_required", "Review required"),
            ("store_check", "Store check"),
            ("supplier_check", "Supplier check"),
            ("available", "Available"),
            ("unavailable", "Unavailable"),
            ("quoted", "Quoted"),
            ("payment_pending", "Payment pending"),
            ("paid", "Paid"),
            ("fulfilled", "Fulfilled"),
            ("cancelled", "Cancelled"),
        ],
        default="draft",
        required=True,
        tracking=True,
        index=True,
    )
    partner_id = fields.Many2one("res.partner", tracking=True)
    phone = fields.Char(required=True, index=True, tracking=True)
    customer_name = fields.Char()

    product_id = fields.Many2one("product.product", tracking=True)
    product_tmpl_id = fields.Many2one(related="product_id.product_tmpl_id", store=True)
    default_code = fields.Char(string="SKU", index=True)
    shopify_product_id = fields.Char(index=True)
    shopify_variant_id = fields.Char(index=True)
    product_url = fields.Char()
    product_title_hint = fields.Char(
        string="Product title (hint only)",
        help="From CTA text — never used alone to resolve the product.",
    )
    requested_qty = fields.Float(default=1.0, required=True)
    review_required = fields.Boolean(default=False, tracking=True)
    review_reason = fields.Char()

    conversation_id = fields.Char(string="Chatwoot conversation ID", index=True)
    message_id = fields.Char(string="Chatwoot message ID", index=True)
    chatwoot_account_id = fields.Char(index=True)
    chatwoot_inbox_id = fields.Char(index=True)
    chatwoot_contact_id = fields.Char(index=True)
    ack_sent = fields.Boolean(default=False, copy=False)
    ack_sent_at = fields.Datetime(copy=False)
    channel = fields.Selection(
        [("whatsapp", "WhatsApp"), ("manual", "Manual"), ("other", "Other")],
        default="manual",
        required=True,
    )
    raw_message = fields.Text(
        help="Sanitized CTA / staff context. Not used as payment evidence.",
    )

    requested_fulfillment = fields.Selection(
        [
            ("shipblu_delivery", "ShipBlu delivery"),
            ("store_pickup", "Store pickup"),
            ("undecided", "Undecided"),
        ],
        default="undecided",
        required=True,
    )

    sale_order_id = fields.Many2one("sale.order", copy=False, tracking=True)
    case_id = fields.Many2one("petspot.fulfillment.case", copy=False)
    shopify_draft_order_id = fields.Char(
        string="Shopify Draft Order ID",
        copy=False,
        help="When Draft Order API is used; optional.",
    )
    payment_link = fields.Char()
    confirmed_price = fields.Float()
    confirmed_eta = fields.Date()
    note = fields.Text()
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    idempotency_key = fields.Char(index=True, copy=False)

    _sql_constraints = [
        (
            "petspot_inquiry_idem_unique",
            "unique(idempotency_key)",
            "Availability inquiry already exists for this key.",
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq.next_by_code("petspot.availability.inquiry") or "INQ/NEW"
            if not vals.get("idempotency_key"):
                account = vals.get("chatwoot_account_id") or "na"
                msg = vals.get("message_id")
                conv = vals.get("conversation_id")
                if account and conv and msg:
                    vals["idempotency_key"] = f"cw:{account}:{conv}:{msg}"
                elif msg:
                    vals["idempotency_key"] = f"inquiry:msg:{msg}"
                elif conv and vals.get("shopify_variant_id"):
                    vals["idempotency_key"] = (
                        f"inquiry:conv:{conv}:var:{vals['shopify_variant_id']}"
                    )
        return super().create(vals_list)

    @api.model
    def _find_or_create_partner_by_phone(self, phone, name=False):
        norm = normalize_eg_phone(phone) or (phone or "").strip()
        if not norm:
            raise UserError(_("Phone is required for availability inquiry."))
        Partner = self.env["res.partner"]
        candidates = {norm, norm.lstrip("+"), phone}
        if norm.startswith("+20") and len(norm) >= 12:
            candidates.add("0" + norm[3:])
            candidates.add(norm[1:])
        domain = [("phone", "in", list(candidates))]
        if "phone_sanitized" in Partner._fields:
            domain = ["|", ("phone", "in", list(candidates)), ("phone_sanitized", "in", list(candidates))]
        partner = Partner.search(domain, limit=1)
        if partner:
            return partner
        vals = {
            "name": name or norm,
            "phone": norm,
            "type": "contact",
            "comment": "Created from PetSpot Chatwoot availability intake",
        }
        if "mobile" in Partner._fields:
            vals["mobile"] = norm
        return Partner.create(vals)

    @api.model
    def _resolve_product_from_cta(self, parsed):
        """Variant map first, then exact SKU. Never guess from title."""
        Product = self.env["product.product"]
        variant_id = parsed.get("shopify_variant_id")
        sku = parsed.get("sku")
        if variant_id and "shopify.variant.map" in self.env:
            mapping = self.env["shopify.variant.map"].sudo().search(
                [("shopify_variant_id", "=", str(variant_id))],
                limit=1,
            )
            if mapping and mapping.product_id:
                return mapping.product_id, False
        if sku:
            product = Product.search([("default_code", "=", sku)], limit=1)
            if product:
                return product, False
            # Exact match only — no ilike / title search
        reason = "missing_variant_and_sku"
        if variant_id and not sku:
            reason = "variant_unmapped"
        elif sku and not variant_id:
            reason = "sku_not_found"
        elif variant_id and sku:
            reason = "variant_unmapped_and_sku_not_found"
        return Product.browse(), reason

    @api.model
    def _intake_from_chatwoot_cta(
        self,
        payload,
        parsed,
        account_id,
        inbox_id,
        conversation_id,
        contact_id,
        message_id,
    ):
        """Create/reuse one inquiry + fulfillment case. No SO/RFQ/payment/AWB."""
        idem = f"cw:{account_id}:{conversation_id}:{message_id}"
        existing = self.search([("idempotency_key", "=", idem)], limit=1)
        if existing:
            if not existing.case_id:
                existing.case_id = self.env["petspot.fulfillment.case"].bind_inquiry_case(existing)
            return existing

        sender = payload.get("sender") or {}
        phone_raw = (
            sender.get("phone_number")
            or sender.get("identifier")
            or (payload.get("conversation") or {}).get("meta", {}).get("sender", {}).get("phone_number")
            or ""
        )
        # Chatwoot sometimes puts phone on conversation.meta.sender
        conv = payload.get("conversation") or {}
        meta_sender = (conv.get("meta") or {}).get("sender") or {}
        phone_raw = phone_raw or meta_sender.get("phone_number") or meta_sender.get("identifier") or ""
        customer_name = sender.get("name") or meta_sender.get("name") or False
        phone = normalize_eg_phone(phone_raw) or (phone_raw or "").strip()
        if not phone:
            phone = "unknown-%s-%s" % (conversation_id, message_id)

        partner = self._find_or_create_partner_by_phone(phone, name=customer_name)
        product, review_reason = self._resolve_product_from_cta(parsed)
        review_required = not bool(product)

        vals = {
            "partner_id": partner.id,
            "phone": normalize_eg_phone(phone) or phone,
            "customer_name": customer_name or partner.name,
            "product_id": product.id if product else False,
            "default_code": parsed.get("sku") or (product.default_code if product else False),
            "shopify_variant_id": parsed.get("shopify_variant_id") or False,
            "product_url": parsed.get("product_url") or False,
            "product_title_hint": parsed.get("product_title") or False,
            "requested_qty": parsed.get("requested_qty") or 1.0,
            "channel": "whatsapp",
            "conversation_id": str(conversation_id),
            "message_id": str(message_id),
            "chatwoot_account_id": str(account_id),
            "chatwoot_inbox_id": str(inbox_id or ""),
            "chatwoot_contact_id": str(contact_id or ""),
            "raw_message": parsed.get("sanitized_message") or False,
            "idempotency_key": idem,
            "review_required": review_required,
            "review_reason": review_reason if review_required else False,
            "state": "review_required" if review_required else "draft",
        }
        # Serialize concurrent webhook workers for this message
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            (idem,),
        )
        raced = self.search([("idempotency_key", "=", idem)], limit=1)
        if raced:
            return raced

        inquiry = self.create(vals)
        case = self.env["petspot.fulfillment.case"].bind_inquiry_case(inquiry)
        inquiry.case_id = case.id
        inquiry.message_post(
            body=_(
                "Chatwoot intake: account=%s inbox=%s conv=%s msg=%s review=%s"
            )
            % (account_id, inbox_id, conversation_id, message_id, review_required)
        )
        if review_required:
            inquiry.activity_schedule(
                "mail.mail_activity_data_todo",
                summary=_("Availability inquiry needs product review"),
                note=_("Could not resolve product (%s). Original CTA preserved.")
                % (review_reason or "unknown"),
                user_id=self.env.user.id,
            )
        return inquiry

    def _send_chatwoot_acknowledgement(self):
        """Send one bilingual ack via Chatwoot API. Idempotent per inquiry."""
        self.ensure_one()
        if self.ack_sent:
            return True
        ICP = self.env["ir.config_parameter"].sudo()
        if ICP.get_param("petspot_fulfillment.chatwoot_ack_enabled", "True") != "True":
            return False
        if ICP.get_param("petspot_fulfillment.chatwoot_test_mode", "False") == "True":
            # Test mode: mark as sent without external call when no token
            token = ICP.get_param("petspot_fulfillment.chatwoot_api_token", "")
            if not token:
                self.write({"ack_sent": True, "ack_sent_at": fields.Datetime.now()})
                self.message_post(body=_("Ack skipped (test mode, no API token)."))
                return True
        base = (ICP.get_param("petspot_fulfillment.chatwoot_base_url", "") or "").rstrip("/")
        token = ICP.get_param("petspot_fulfillment.chatwoot_api_token", "")
        account = self.chatwoot_account_id or ICP.get_param(
            "petspot_fulfillment.chatwoot_account_id", "2"
        )
        if not base or not token or not self.conversation_id:
            _logger.warning(
                "petspot_ff ack skipped inquiry=%s (missing base/token/conversation)",
                self.id,
            )
            return False
        body = (
            "تم استلام طلب التوفر ✅\n"
            "فريق بت سبوت هيراجع التوفر والسعر وميعاد التوريد وهيتواصل معاك.\n"
            "Availability request received ✅\n"
            "Pet Spot will confirm availability, price and ETA shortly.\n"
            f"Ref: {self.name}"
        )
        url = f"{base}/api/v1/accounts/{account}/conversations/{self.conversation_id}/messages"
        data = json.dumps({
            "content": body,
            "message_type": "outgoing",
            "private": False,
        }).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "api_access_token": token,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                status = getattr(resp, "status", 200)
            if status >= 400:
                _logger.warning("petspot_ff ack HTTP %s inquiry=%s", status, self.id)
                return False
        except urllib.error.HTTPError as exc:
            _logger.warning("petspot_ff ack failed inquiry=%s http=%s", self.id, exc.code)
            return False
        except Exception:
            _logger.exception("petspot_ff ack error inquiry=%s", self.id)
            return False
        self.write({"ack_sent": True, "ack_sent_at": fields.Datetime.now()})
        self.message_post(body=_("Chatwoot acknowledgement sent once."))
        return True

    def action_check_store(self):
        for rec in self:
            rec.state = "store_check"
            qty = rec.product_id.qty_available if rec.product_id else 0.0
            rec.message_post(
                body=_("Store check: qty_available=%.2f for %s")
                % (qty, rec.product_id.display_name if rec.product_id else "?")
            )
            if rec.product_id and qty >= rec.requested_qty:
                rec.state = "available"
        return True

    def action_source_supplier(self):
        for rec in self:
            rec.state = "supplier_check"
            rec.message_post(body=_("Staff will source from supplier (manual)."))
        return True

    def action_mark_unavailable(self):
        self.write({"state": "unavailable"})
        return True

    def action_create_quotation(self):
        """Idempotent: return existing quotation if already linked."""
        self.ensure_one()
        if not self.env.user.has_group("petspot_fulfillment.group_fulfillment_user"):
            raise AccessError(_("Fulfillment user required."))
        if self.sale_order_id:
            return self._open_sale()
        if not self.product_id:
            raise UserError(_("Select a product before creating a quotation."))
        partner = self.partner_id
        if not partner:
            partner = self.env["res.partner"].create({
                "name": self.customer_name or self.phone,
                "phone": self.phone,
                "type": "contact",
            })
            self.partner_id = partner.id
        # Lock inquiry
        self.env.cr.execute(
            "SELECT id FROM petspot_availability_inquiry WHERE id=%s FOR UPDATE",
            (self.id,),
        )
        self.invalidate_recordset()
        if self.sale_order_id:
            return self._open_sale()
        so = self.env["sale.order"].create({
            "partner_id": partner.id,
            "origin": f"petspot-inquiry:{self.id}",
            "client_order_ref": self.name,
            "order_line": [(0, 0, {
                "product_id": self.product_id.id,
                "product_uom_qty": self.requested_qty,
                "price_unit": self.confirmed_price or self.product_id.lst_price,
            })],
        })
        self.sale_order_id = so.id
        self.state = "quoted"
        case = self.env["petspot.fulfillment.case"].get_or_create_for_sale_order(
            so, classification_source="inquiry"
        )
        case.write({
            "path": "manual_whatsapp",
            "inquiry_id": self.id,
            "delivery_method": self.requested_fulfillment
            if self.requested_fulfillment != "undecided"
            else "undecided",
            "classification_note": _("Created from availability inquiry %s") % self.name,
        })
        for line in case.line_ids:
            line.source = "manual_whatsapp"
        self.case_id = case.id
        case.action_transition("availability_check", source="inquiry_quote")
        self.message_post(body=_("Quotation %s created (idempotent bind).") % so.name)
        return self._open_sale()

    def _open_sale(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "sale.order",
            "view_mode": "form",
            "res_id": self.sale_order_id.id,
        }

    def action_record_payment_link(self):
        for rec in self:
            if not rec.payment_link:
                raise UserError(_("Set payment_link first."))
            rec.state = "payment_pending"
            rec.message_post(body=_("Payment link recorded: %s") % rec.payment_link)
        return True

    def action_mark_paid_from_trusted(self):
        """Only after trusted Shopify/Odoo payment data — not WhatsApp screenshots."""
        for rec in self:
            if not rec.sale_order_id:
                raise UserError(_("Create quotation first."))
            case = rec.case_id or self.env["petspot.fulfillment.case"].get_or_create_for_sale_order(
                rec.sale_order_id
            )
            _fin, pay = self.env["petspot.fulfillment.case"]._sale_payment_snapshot(rec.sale_order_id)
            if pay != "paid":
                raise UserError(
                    _("No trusted payment status on the sale order. "
                      "Use the Mark Paid wizard on the fulfillment case with a journal reference.")
                )
            rec.state = "paid"
            case.payment_status = "paid"
            case.shopify_financial_status = _fin or case.shopify_financial_status
            case.action_transition("paid", source="inquiry_payment")
        return True
