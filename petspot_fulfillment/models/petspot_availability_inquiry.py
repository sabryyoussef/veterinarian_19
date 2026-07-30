# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, AccessError


class PetspotAvailabilityInquiry(models.Model):
    _name = "petspot.availability.inquiry"
    _description = "PetSpot Availability Inquiry (WhatsApp / Manual)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(required=True, copy=False, default="New")
    state = fields.Selection(
        [
            ("draft", "Draft"),
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
    requested_qty = fields.Float(default=1.0, required=True)

    conversation_id = fields.Char(string="Chatwoot/Conversation ID", index=True)
    message_id = fields.Char(string="Message ID", index=True)
    channel = fields.Selection(
        [("whatsapp", "WhatsApp"), ("manual", "Manual"), ("other", "Other")],
        default="manual",
        required=True,
    )
    raw_message = fields.Text(
        help="Optional staff-pasted context. Not parsed automatically.",
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
                msg = vals.get("message_id")
                conv = vals.get("conversation_id")
                if msg:
                    vals["idempotency_key"] = f"inquiry:msg:{msg}"
                elif conv and vals.get("shopify_variant_id"):
                    vals["idempotency_key"] = (
                        f"inquiry:conv:{conv}:var:{vals['shopify_variant_id']}"
                    )
        return super().create(vals_list)

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
