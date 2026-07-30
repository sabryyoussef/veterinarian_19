# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, AccessError, ValidationError

from .petspot_fulfillment_constants import (
    FULFILLMENT_PATHS,
    DELIVERY_METHOD,
    ORCH_STATES,
    ALLOWED_TRANSITIONS,
    SHOPIFY_PAID_STATUSES,
)


class PetspotFulfillmentCase(models.Model):
    _name = "petspot.fulfillment.case"
    _description = "PetSpot Fulfillment Case"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"
    _rec_name = "name"

    name = fields.Char(required=True, copy=False, default="New", tracking=True)
    active = fields.Boolean(default=True)

    # Idempotency identities (immutable where possible)
    shopify_store_id = fields.Char(
        string="Shopify Store GID/ID",
        index=True,
        help="Immutable Shopify shop identifier when known.",
    )
    shopify_order_id = fields.Char(
        string="Shopify Order ID",
        index=True,
        copy=False,
        help="Immutable Shopify order id (numeric), never display name alone.",
    )
    shopify_order_name = fields.Char(string="Shopify Order Name", help="Display only (#1004).")
    idempotency_key = fields.Char(
        string="Idempotency Key",
        index=True,
        copy=False,
        help="Canonical key shopify:<store>:<order_id> or inquiry:<id>.",
    )

    sale_order_id = fields.Many2one(
        "sale.order",
        string="Sale Order",
        index=True,
        ondelete="cascade",
        tracking=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Customer",
        compute="_compute_partner_id",
        store=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        related="sale_order_id.currency_id",
        store=True,
        readonly=True,
    )

    path = fields.Selection(
        FULFILLMENT_PATHS,
        string="Fulfillment Path",
        default="mixed",
        required=True,
        tracking=True,
    )
    delivery_method = fields.Selection(
        DELIVERY_METHOD,
        default="undecided",
        required=True,
        tracking=True,
    )
    state = fields.Selection(
        ORCH_STATES,
        default="new",
        required=True,
        tracking=True,
        index=True,
    )
    classification_source = fields.Selection(
        [
            ("manual", "Manual"),
            ("auto", "Automatic"),
            ("inquiry", "From inquiry"),
        ],
        default="manual",
        required=True,
    )
    classification_note = fields.Text(
        string="Classification Explanation",
        help="Explainable reason for automatic/manual classification.",
    )

    # Links
    purchase_order_ids = fields.Many2many(
        "purchase.order",
        "petspot_ff_case_purchase_rel",
        "case_id",
        "purchase_id",
        string="RFQ / Purchase Orders",
    )
    purchase_order_count = fields.Integer(compute="_compute_counts")
    inquiry_id = fields.Many2one(
        "petspot.availability.inquiry",
        string="Availability Inquiry",
        copy=False,
    )
    inquiry_count = fields.Integer(compute="_compute_counts")
    picking_ids = fields.Many2many(
        "stock.picking",
        compute="_compute_pickings",
        string="Pickings",
    )
    picking_count = fields.Integer(compute="_compute_counts")
    shipblu_shipment_ids = fields.Many2many(
        "shipblu.shipment",
        compute="_compute_shipblu",
        string="ShipBlu Shipments",
    )
    shipblu_count = fields.Integer(compute="_compute_counts")

    line_ids = fields.One2many(
        "petspot.fulfillment.line",
        "case_id",
        string="Lines",
    )
    transition_ids = fields.One2many(
        "petspot.fulfillment.transition",
        "case_id",
        string="Transitions",
    )

    # Payment
    shopify_financial_status = fields.Char(
        string="Shopify Financial Status",
        help="Trusted Shopify financial_status when available.",
    )
    payment_status = fields.Selection(
        [
            ("unknown", "Unknown"),
            ("unpaid", "Unpaid"),
            ("paid", "Paid (trusted)"),
            ("manual_paid", "Manually marked paid"),
            ("refund_review", "Refund review"),
        ],
        default="unknown",
        required=True,
        tracking=True,
    )
    payment_reference = fields.Char(tracking=True)
    customer_approval_required = fields.Boolean(default=False, tracking=True)
    customer_approved = fields.Boolean(default=False, tracking=True)
    customer_approval_note = fields.Text()

    # Supplier summary
    supplier_confirmed = fields.Boolean(default=False, tracking=True)
    supplier_eta = fields.Date(tracking=True)
    supplier_cost = fields.Monetary(currency_field="currency_id", tracking=True)
    supplier_reference = fields.Char(tracking=True)
    supplier_notes = fields.Text()

    block_message = fields.Text(
        string="Blocking Message",
        compute="_compute_block_message",
        help="Human-readable missing prerequisites.",
    )
    automation_enabled = fields.Boolean(
        string="Automation Enabled",
        default=False,
        help="When false, only human-driven transitions (cutover safety).",
        tracking=True,
    )
    cutover_eligible = fields.Boolean(
        default=True,
        help="False for historical orders before cutover timestamp.",
    )

    _sql_constraints = [
        (
            "petspot_ff_idempotency_unique",
            "unique(idempotency_key)",
            "A fulfillment case with this idempotency key already exists.",
        ),
        (
            "petspot_ff_shopify_order_unique",
            "unique(shopify_store_id, shopify_order_id)",
            "A fulfillment case for this Shopify store/order already exists.",
        ),
    ]

    @api.depends("sale_order_id.partner_id", "inquiry_id.partner_id")
    def _compute_partner_id(self):
        for case in self:
            case.partner_id = (
                case.sale_order_id.partner_id
                or case.inquiry_id.partner_id
            )

    @api.depends("sale_order_id", "purchase_order_ids", "inquiry_id")
    def _compute_counts(self):
        for case in self:
            case.purchase_order_count = len(case.purchase_order_ids)
            case.inquiry_count = 1 if case.inquiry_id else 0
            case.picking_count = len(case.picking_ids)
            case.shipblu_count = len(case.shipblu_shipment_ids)

    def _compute_pickings(self):
        for case in self:
            if case.sale_order_id:
                case.picking_ids = case.sale_order_id.picking_ids
            else:
                case.picking_ids = False

    def _compute_shipblu(self):
        Shipment = self.env["shipblu.shipment"]
        for case in self:
            if not case.sale_order_id:
                case.shipblu_shipment_ids = False
                continue
            domain = [("sale_order_id", "=", case.sale_order_id.id)]
            if "sale_id" in Shipment._fields:
                domain = ["|", ("sale_order_id", "=", case.sale_order_id.id),
                          ("sale_id", "=", case.sale_order_id.id)]
            # Fall back: shipments linked via picking
            pickings = case.sale_order_id.picking_ids
            shipments = Shipment.browse()
            if "picking_id" in Shipment._fields and pickings:
                shipments |= Shipment.search([("picking_id", "in", pickings.ids)])
            if "sale_order_id" in Shipment._fields:
                shipments |= Shipment.search([("sale_order_id", "=", case.sale_order_id.id)])
            case.shipblu_shipment_ids = shipments

    def _compute_block_message(self):
        for case in self:
            case.block_message = "\n".join(case._get_blockers()) or False

    def _get_blockers(self):
        self.ensure_one()
        blockers = []
        if self.state in ("cancelled", "unavailable", "completed"):
            return blockers
        if self.delivery_method == "shipblu_delivery":
            if self.payment_status not in ("paid", "manual_paid") and self.state not in (
                "paid", "purchase_confirmed", "awaiting_receipt", "ready_for_delivery",
                "shipping_created", "delivered",
            ):
                blockers.append(_("Payment policy not satisfied."))
            if self.path in ("supplier_b2b", "mixed") and not self.supplier_confirmed:
                if any(l.source == "supplier_b2b" for l in self.line_ids):
                    blockers.append(_("Supplier availability not confirmed for B2B line(s)."))
            if self.customer_approval_required and not self.customer_approved:
                blockers.append(_("Customer approval required for price/ETA change."))
            if self.state not in (
                "ready_for_delivery", "shipping_created", "delivered", "completed",
            ):
                blockers.append(_("Order not ready for ShipBlu (state=%s).") % self.state)
            if self.shipblu_count:
                blockers.append(_("ShipBlu AWB already linked — Duplicate Guard applies."))
        if self.delivery_method == "store_pickup" and self.state == "shipping_created":
            blockers.append(_("Store pickup must not create a ShipBlu AWB."))
        if not self.sale_order_id and self.path != "manual_whatsapp":
            blockers.append(_("No linked sale order."))
        return blockers

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq.next_by_code("petspot.fulfillment.case") or "FF/NEW"
            if not vals.get("idempotency_key"):
                store = vals.get("shopify_store_id") or "nostore"
                oid = vals.get("shopify_order_id")
                if oid:
                    vals["shopify_store_id"] = vals.get("shopify_store_id") or "nostore"
                    vals["idempotency_key"] = f"shopify:{store}:{oid}"
        return super().create(vals_list)

    @api.model
    def _sale_payment_snapshot(self, sale_order):
        """Trusted payment signal from Shopify/Odoo fields (never WhatsApp)."""
        amount_paid = float(getattr(sale_order, "shopify_amount_paid", 0.0) or 0.0)
        order_total = float(
            getattr(sale_order, "shopify_order_total", 0.0)
            or sale_order.amount_total
            or 0.0
        )
        fin_field = getattr(sale_order, "shopify_financial_status", False) or ""
        fin_norm = str(fin_field).strip().lower() if fin_field else ""
        if not fin_norm:
            if amount_paid > 0 and order_total > 0 and amount_paid + 0.009 >= order_total:
                fin_norm = "paid"
            elif amount_paid > 0:
                fin_norm = "partially_paid"
            elif getattr(sale_order, "shopify_order_id", False):
                fin_norm = "pending"
        if fin_norm in SHOPIFY_PAID_STATUSES or (
            sale_order.invoice_status == "invoiced" and sale_order.state in ("sale", "done")
        ):
            return fin_norm or "paid", "paid"
        if getattr(sale_order, "shopify_order_id", False):
            if fin_norm in ("pending", "authorized", "unpaid", ""):
                return fin_norm or "pending", "unpaid"
            return fin_norm or "unknown", "unknown"
        return fin_norm or False, "unknown"

    @api.model
    def get_or_create_for_sale_order(self, sale_order, classification_source="auto"):
        """Idempotent case bind for a sale.order (Shopify or manual)."""
        sale_order.ensure_one()
        existing = self.search([("sale_order_id", "=", sale_order.id)], limit=1)
        if existing:
            # Refresh trusted payment snapshot if Shopify already paid after create
            fin, pay = self._sale_payment_snapshot(sale_order)
            vals = {}
            if fin and existing.shopify_financial_status != fin:
                vals["shopify_financial_status"] = fin
            if pay == "paid" and existing.payment_status not in ("paid", "manual_paid", "refund_review"):
                vals["payment_status"] = "paid"
                if existing.state in ("new", "payment_pending"):
                    vals["state"] = "paid"
            if vals:
                existing.write(vals)
            return existing

        shopify_order_id = getattr(sale_order, "shopify_order_id", False) or False
        store_id = False
        if hasattr(sale_order, "shopify_instance_id") and sale_order.shopify_instance_id:
            store = sale_order.shopify_instance_id
            store_id = str(getattr(store, "shopify_shop_id", False) or store.id)
        elif hasattr(sale_order, "shopify_store_id") and sale_order.shopify_store_id:
            store = sale_order.shopify_store_id
            store_id = str(getattr(store, "shop_id", False) or store.id)

        # Unique lookup by Shopify ids first
        if shopify_order_id and store_id:
            by_shopify = self.search([
                ("shopify_store_id", "=", store_id),
                ("shopify_order_id", "=", str(shopify_order_id)),
            ], limit=1)
            if by_shopify:
                if not by_shopify.sale_order_id:
                    by_shopify.sale_order_id = sale_order.id
                return by_shopify

        fin, payment_status = self._sale_payment_snapshot(sale_order)
        state = "new"
        if payment_status == "paid":
            state = "paid"
        elif payment_status == "unpaid" and shopify_order_id:
            state = "payment_pending"

        key = f"shopify:{store_id or 'nostore'}:{shopify_order_id}" if shopify_order_id else f"odoo-so:{sale_order.id}"
        case = self.create({
            "sale_order_id": sale_order.id,
            "shopify_store_id": (store_id or "nostore") if shopify_order_id else False,
            "shopify_order_id": str(shopify_order_id) if shopify_order_id else False,
            "shopify_order_name": sale_order.client_order_ref or sale_order.name,
            "idempotency_key": key,
            "shopify_financial_status": fin or False,
            "payment_status": payment_status,
            "state": state,
            "classification_source": classification_source,
            "company_id": sale_order.company_id.id,
            "automation_enabled": self._automation_flag(),
            "cutover_eligible": self._is_cutover_eligible(sale_order),
        })
        case._sync_lines_from_sale()
        case._auto_classify(force=False)
        case.message_post(body=_("Fulfillment case created for %s") % sale_order.display_name)
        return case

    @api.model
    def bind_inquiry_case(self, inquiry):
        """Link/create orchestration case for Path B inquiry — no SO/RFQ/AWB."""
        inquiry.ensure_one()
        if inquiry.case_id:
            return inquiry.case_id
        existing = self.search([("inquiry_id", "=", inquiry.id)], limit=1)
        if existing:
            return existing
        key = inquiry.idempotency_key or f"inquiry:{inquiry.id}"
        by_key = self.search([("idempotency_key", "=", key)], limit=1)
        if by_key:
            if not by_key.inquiry_id:
                by_key.inquiry_id = inquiry.id
            return by_key
        case = self.create({
            "idempotency_key": key,
            "inquiry_id": inquiry.id,
            "path": "manual_whatsapp",
            "state": "availability_check",
            "classification_source": "inquiry",
            "classification_note": _("Bound from availability inquiry %s") % inquiry.name,
            "delivery_method": inquiry.requested_fulfillment
            if inquiry.requested_fulfillment != "undecided"
            else "undecided",
            "payment_status": "unpaid",
            "company_id": inquiry.company_id.id,
            "automation_enabled": False,
        })
        if inquiry.product_id:
            self.env["petspot.fulfillment.line"].create({
                "case_id": case.id,
                "product_id": inquiry.product_id.id,
                "product_uom_qty": inquiry.requested_qty,
                "source": "manual_whatsapp",
            })
        case.message_post(
            body=_("Path B case from Chatwoot/manual inquiry (no quotation auto-created).")
        )
        return case

    @api.model
    def _automation_flag(self):
        return self.env["ir.config_parameter"].sudo().get_param(
            "petspot_fulfillment.automation_enabled", "False"
        ) == "True"

    @api.model
    def _is_cutover_eligible(self, sale_order):
        raw = self.env["ir.config_parameter"].sudo().get_param(
            "petspot_fulfillment.cutover_timestamp", ""
        )
        if not raw:
            return True
        try:
            cutover = fields.Datetime.to_datetime(raw)
        except Exception:
            return True
        return (sale_order.create_date or fields.Datetime.now()) >= cutover

    def _sync_lines_from_sale(self):
        self.ensure_one()
        Line = self.env["petspot.fulfillment.line"]
        if not self.sale_order_id:
            return
        existing = {l.sale_line_id.id: l for l in self.line_ids if l.sale_line_id}
        for sol in self.sale_order_id.order_line.filtered(lambda l: not l.display_type):
            if sol.id in existing:
                continue
            Line.create({
                "case_id": self.id,
                "sale_line_id": sol.id,
                "product_id": sol.product_id.id,
                "product_uom_qty": sol.product_uom_qty,
                "source": "unclassified",
            })

    def _auto_classify(self, force=False):
        """Derive path from lines/vendor data; always overridable."""
        for case in self:
            if case.classification_source == "manual" and not force:
                continue
            notes = []
            for line in case.line_ids:
                if line.source != "unclassified" and not force:
                    continue
                vendor = line.product_id.seller_ids[:1] if line.product_id else False
                qty_available = line.product_id.qty_available if line.product_id else 0.0
                if vendor:
                    line.source = "supplier_b2b"
                    line.vendor_id = vendor.partner_id.id
                    notes.append(
                        _("Line %s → supplier_b2b (vendor %s)")
                        % (line.product_id.display_name, vendor.partner_id.display_name)
                    )
                elif qty_available >= line.product_uom_qty:
                    line.source = "store_stock"
                    notes.append(
                        _("Line %s → store_stock (qty_available=%.2f)")
                        % (line.product_id.display_name, qty_available)
                    )
                else:
                    line.source = "unclassified"
                    notes.append(
                        _("Line %s → unclassified (no vendor / insufficient stock)")
                        % (line.product_id.display_name,)
                    )
            raw_sources = set(case.line_ids.mapped("source"))
            sources = raw_sources - {"unclassified"}
            # Any unclassified line beside classified ones → mixed (staff must decide)
            if "unclassified" in raw_sources and sources:
                path = "mixed"
            elif not sources:
                path = "mixed"
            elif sources == {"store_stock"}:
                path = "store_stock"
            elif sources == {"supplier_b2b"}:
                path = "supplier_b2b"
            elif sources == {"manual_whatsapp"}:
                path = "manual_whatsapp"
            elif sources == {"unavailable"}:
                path = "unavailable"
            else:
                path = "mixed"
            case.write({
                "path": path,
                "classification_source": "auto",
                "classification_note": "\n".join(notes) or case.classification_note,
            })

    def action_transition(self, new_state, source="manual", note=False, force=False):
        """Validated, audited, idempotent state transition."""
        for case in self:
            if case.state == new_state:
                case.message_post(body=_("Idempotent transition: already in %s") % new_state)
                continue
            allowed = ALLOWED_TRANSITIONS.get(case.state, frozenset())
            if new_state not in allowed and not force:
                raise UserError(
                    _("Transition %s → %s is not allowed.") % (case.state, new_state)
                )
            if not self.env.user.has_group("petspot_fulfillment.group_fulfillment_user"):
                raise AccessError(_("You cannot change fulfillment state."))
            # Gate checks for specific targets (force skips hard prereqs that
            # would otherwise block TEST synthetic FSM shortcuts).
            if not force:
                case._validate_transition_prereqs(new_state)
            elif new_state == "shipping_created":
                # Even forced mock AWB still requires trusted payment and forbids pickup.
                if case.delivery_method == "store_pickup":
                    raise UserError(_("Store pickup must not create ShipBlu AWB."))
                if case.payment_status not in ("paid", "manual_paid"):
                    raise UserError(_("Cannot create shipping: payment policy not satisfied."))
            old = case.state
            case.write({"state": new_state})
            self.env["petspot.fulfillment.transition"].create({
                "case_id": case.id,
                "from_state": old,
                "to_state": new_state,
                "source": source,
                "user_id": self.env.user.id,
                "note": note or False,
            })
            case.message_post(
                body=_("State %s → %s (%s)") % (old, new_state, source)
            )
        return True

    def _validate_transition_prereqs(self, new_state):
        self.ensure_one()
        if new_state == "purchase_confirmed":
            if self.customer_approval_required and not self.customer_approved:
                raise UserError(_("Customer approval is required before confirming purchase."))
            if self.payment_status not in ("paid", "manual_paid"):
                raise UserError(_("Payment must be confirmed before purchase confirmation."))
            if not self.purchase_order_ids:
                raise UserError(_("No RFQ/PO linked."))
        if new_state == "shipping_created":
            if self.delivery_method == "store_pickup":
                raise UserError(_("Store pickup must not create ShipBlu AWB."))
            blockers = self._get_blockers()
            # Recompute as if ready
            if self.payment_status not in ("paid", "manual_paid"):
                raise UserError(_("Cannot create shipping: payment policy not satisfied."))
            if self.customer_approval_required and not self.customer_approved:
                raise UserError(_("Cannot create shipping: customer approval missing."))
            if self.state not in ("ready_for_delivery",):
                raise UserError(_("Cannot create shipping unless state is ready_for_delivery."))
        if new_state == "paid" and self.payment_status not in ("paid", "manual_paid"):
            # Allow if Shopify financial says paid
            fin = (self.shopify_financial_status or "").lower()
            if fin not in SHOPIFY_PAID_STATUSES:
                raise UserError(
                    _("Cannot mark orchestration paid without trusted payment data. "
                      "Use Mark Paid wizard with reference.")
                )

    # --- UI actions ---
    def action_open_sale(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "sale.order",
            "view_mode": "form",
            "res_id": self.sale_order_id.id,
        }

    def action_open_purchases(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("RFQ / PO"),
            "res_model": "purchase.order",
            "view_mode": "list,form",
            "domain": [("id", "in", self.purchase_order_ids.ids)],
        }

    def action_open_inquiry(self):
        self.ensure_one()
        if not self.inquiry_id:
            raise UserError(_("No availability inquiry linked."))
        return {
            "type": "ir.actions.act_window",
            "res_model": "petspot.availability.inquiry",
            "view_mode": "form",
            "res_id": self.inquiry_id.id,
        }

    def action_create_draft_rfq(self):
        """Idempotent draft RFQ for supplier_b2b lines."""
        self.ensure_one()
        if not self.env.user.has_group("petspot_fulfillment.group_fulfillment_purchase"):
            raise AccessError(_("Purchase role required to create RFQ."))
        return self.env["petspot.fulfillment.case"]._create_draft_rfq_for_case(self)

    @api.model
    def _create_draft_rfq_for_case(self, case):
        case.ensure_one()
        # Lock case row
        self.env.cr.execute(
            "SELECT id FROM petspot_fulfillment_case WHERE id=%s FOR UPDATE",
            (case.id,),
        )
        b2b_lines = case.line_ids.filtered(lambda l: l.source == "supplier_b2b")
        if not b2b_lines:
            case._auto_classify(force=False)
            b2b_lines = case.line_ids.filtered(lambda l: l.source == "supplier_b2b")
        if not b2b_lines:
            raise UserError(_("No supplier_b2b lines to RFQ."))

        # Group by vendor — never mix vendors
        by_vendor = {}
        missing = []
        for line in b2b_lines:
            vendor = line.vendor_id
            if not vendor and line.product_id.seller_ids:
                vendor = line.product_id.seller_ids[0].partner_id
                line.vendor_id = vendor.id
            if not vendor:
                missing.append(line.product_id.display_name)
                continue
            by_vendor.setdefault(vendor, self.env["petspot.fulfillment.line"])
            by_vendor[vendor] |= line
        if missing:
            case.activity_schedule(
                "mail.mail_activity_data_todo",
                summary=_("Missing vendor for RFQ"),
                note=_("Products without vendor: %s") % ", ".join(missing),
                user_id=self.env.user.id,
            )
            raise UserError(
                _("Missing vendor for: %s. Automation blocked; activity assigned.")
                % ", ".join(missing)
            )

        Purchase = self.env["purchase.order"]
        created_or_existing = Purchase.browse()
        for vendor, lines in by_vendor.items():
            # Idempotent: find existing draft RFQ for this case+vendor
            existing = case.purchase_order_ids.filtered(
                lambda p: p.partner_id == vendor and p.state in ("draft", "sent")
            )
            if existing:
                created_or_existing |= existing
                continue
            # Also search by origin marker
            marker = f"petspot-ff:{case.id}:vendor:{vendor.id}"
            found = Purchase.search([
                ("partner_id", "=", vendor.id),
                ("origin", "ilike", marker),
                ("state", "in", ("draft", "sent")),
            ], limit=1)
            if found:
                case.purchase_order_ids = [(4, found.id)]
                created_or_existing |= found
                continue

            po_lines = []
            Pol = Purchase.order_line
            for line in lines:
                seller = False
                if hasattr(line.product_id, "_select_seller"):
                    try:
                        seller = line.product_id._select_seller(
                            partner_id=vendor,
                            quantity=line.product_uom_qty,
                        )
                    except Exception:
                        seller = False
                price = seller.price if seller else line.product_id.standard_price
                line_vals = {
                    "product_id": line.product_id.id,
                    "name": line.product_id.display_name,
                    "product_qty": line.product_uom_qty,
                    "price_unit": price,
                    "date_planned": fields.Datetime.now(),
                }
                uom_field = "product_uom_id" if "product_uom_id" in Pol._fields else "product_uom"
                if uom_field in Pol._fields:
                    line_vals[uom_field] = line.product_id.uom_id.id
                po_lines.append((0, 0, line_vals))

            po = Purchase.create({
                "partner_id": vendor.id,
                "origin": f"{case.sale_order_id.name if case.sale_order_id else case.name} | {marker}",
                "company_id": case.company_id.id,
                "order_line": po_lines,
            })
            if "petspot_fulfillment_case_id" in Purchase._fields:
                po.petspot_fulfillment_case_id = case.id
            case.purchase_order_ids = [(4, po.id)]
            for line in lines:
                line.purchase_line_id = po.order_line.filtered(
                    lambda l: l.product_id == line.product_id
                )[:1].id
            created_or_existing |= po
            case.message_post(body=_("Draft RFQ %s created for %s") % (po.name, vendor.display_name))

        if case.state in ("new", "availability_check", "paid"):
            case.action_transition("supplier_rfq", source="rfq_action")
        return {
            "type": "ir.actions.act_window",
            "name": _("RFQ / PO"),
            "res_model": "purchase.order",
            "view_mode": "list,form",
            "domain": [("id", "in", created_or_existing.ids)],
        }

    def action_record_supplier_confirmation(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Supplier confirmation"),
            "res_model": "petspot.supplier.confirm.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_case_id": self.id},
        }

    def action_mark_paid_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Mark Paid"),
            "res_model": "petspot.mark.paid.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_case_id": self.id},
        }

    def action_request_customer_approval(self):
        for case in self:
            case.write({
                "customer_approval_required": True,
                "customer_approved": False,
            })
            case.action_transition("customer_approval_required", source="approval_gate")
        return True

    def action_customer_approved(self):
        for case in self:
            case.write({"customer_approved": True})
            case.message_post(body=_("Customer approval recorded."))
            if case.payment_status in ("paid", "manual_paid"):
                case.action_transition("paid", source="customer_approval")
            else:
                case.action_transition("payment_pending", source="customer_approval")
        return True

    def action_confirm_purchase(self):
        self.ensure_one()
        if not self.env.user.has_group("petspot_fulfillment.group_fulfillment_manager"):
            raise AccessError(_("Manager role required to confirm purchase."))
        self._validate_transition_prereqs("purchase_confirmed")
        for po in self.purchase_order_ids.filtered(lambda p: p.state in ("draft", "sent")):
            po.button_confirm()
        if self.sale_order_id and self.sale_order_id.state in ("draft", "sent"):
            self.sale_order_id.action_confirm()
        self.action_transition("purchase_confirmed", source="purchase_confirm")
        self.action_transition("awaiting_receipt", source="purchase_confirm")
        return True

    def action_mark_ready_for_delivery(self):
        for case in self:
            if case.delivery_method == "store_pickup":
                case.action_transition("store_pickup_ready", source="ready")
            else:
                case.delivery_method = case.delivery_method if case.delivery_method != "undecided" else "shipblu_delivery"
                case.action_transition("ready_for_delivery", source="ready")
        return True

    def action_create_shipblu(self):
        """Gate then delegate to existing ShipBlu create — never bypass Duplicate Guard."""
        self.ensure_one()
        if self.delivery_method == "store_pickup":
            raise UserError(_("Store pickup must not create a ShipBlu AWB."))
        self._validate_transition_prereqs("shipping_created")
        if self.shipblu_count:
            raise UserError(_("ShipBlu shipment already linked (Duplicate Guard)."))
        pickings = self.sale_order_id.picking_ids.filtered(
            lambda p: p.state not in ("done", "cancel") and p.picking_type_code == "outgoing"
        )
        if not pickings:
            raise UserError(_("No outgoing picking ready for ShipBlu."))
        # Prefer existing send_to_shipper / create action on picking if present
        created = False
        for picking in pickings:
            if hasattr(picking, "send_to_shipper"):
                picking.send_to_shipper()
                created = True
            elif hasattr(picking, "action_shipblu_create_shipment"):
                picking.action_shipblu_create_shipment()
                created = True
        if not created:
            raise UserError(
                _("No ShipBlu create method found on picking. "
                  "Use the ShipBlu portal/wizard; Duplicate Guard still applies.")
            )
        self.invalidate_recordset()
        self.action_transition("shipping_created", source="shipblu")
        return True

    def action_store_pickup_handover(self):
        for case in self:
            if case.delivery_method != "store_pickup":
                raise UserError(_("Not a store pickup case."))
            case.action_transition("completed", source="pickup_handover")
        return True

    def action_mark_unavailable(self):
        for case in self:
            if case.payment_status in ("paid", "manual_paid"):
                case.payment_status = "refund_review"
                case.action_transition("exception", source="unavailable_paid")
                case.message_post(
                    body=_("Paid order unavailable — moved to exception/refund review. "
                           "No automatic refund issued.")
                )
            else:
                case.action_transition("unavailable", source="unavailable")
        return True
