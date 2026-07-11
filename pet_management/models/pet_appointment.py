from datetime import timedelta
from odoo import models, fields, api, _ # type
from odoo.exceptions import UserError, ValidationError

class PetAppointment(models.Model):
    _name = 'pet.appointment'
    _description = 'Pet Appointment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'start_datetime desc'

    CLINICAL_PRIMARY_TYPES = (
        'emergency', 'checkup', 'surgery', 'dental', 'home_visit', 'comprehensive',
    )

    pet_id = fields.Many2one(
        'pet.pet', required=False, ondelete='cascade', tracking=True,
        domain="[('owner_id', '=', intake_owner_id)]",
        help="The pet for this appointment. Required before clinical work; "
             "may be empty briefly after save so reception can create it via Pet / Health Details.")
    # Editable owner for reception intake. Related owner_id stays the pet-derived truth once pet_id is set.
    intake_owner_id = fields.Many2one(
        'res.partner', string='Owner', tracking=True, index=True,
        help="Owner selected during appointment intake. Must match the selected pet's owner.")
    owner_id = fields.Many2one(related='pet_id.owner_id', store=True, readonly=True, help="Pet owner")
    # Odoo 19 base res.partner has phone only (no separate mobile). One stored contact field.
    # Writable so reception can fill phone/email on the appointment after creating a contact without them.
    owner_phone = fields.Char(
        related='intake_owner_id.phone', string='Phone / Mobile', store=True, readonly=False,
        help="Owner contact number from partner phone (editable; writes back to the contact)")
    owner_email = fields.Char(
        related='intake_owner_id.email', string='Email', store=True, readonly=False,
        help="Owner email (editable; writes back to the contact)")
    owner_contact_display = fields.Char(
        string='Phone / Mobile', compute='_compute_owner_contact_display', store=True,
        help="Single contact number for kanban/reception display")
    pet_species_id = fields.Many2one(related='pet_id.species_id', string='Species', store=True, readonly=True)
    pet_breed_id = fields.Many2one(related='pet_id.breed_id', string='Breed', store=True, readonly=True)
    pet_gender = fields.Selection(
        related='pet_id.gender', string='Gender', readonly=True,
    )
    pet_dob = fields.Date(related='pet_id.dob', string='Date of Birth', readonly=True)
    pet_age_display = fields.Char(related='pet_id.age_display', string='Age', readonly=True)
    allergies_display = fields.Text(string='Allergies', compute='_compute_health_display')
    chronic_conditions_display = fields.Text(string='Chronic Conditions', compute='_compute_health_display')
    dietary_restrictions_display = fields.Text(string='Dietary Restrictions', compute='_compute_health_display')
    behavior_notes_display = fields.Text(string='Behavior Notes', compute='_compute_health_display')
    # Appointment Categories (can select multiple)
    is_medical = fields.Boolean(string='Medical', default=False, help="Include medical services")
    is_vaccination = fields.Boolean(string='Include Vaccination', default=False, help="Include vaccination services")
    is_grooming = fields.Boolean(string='Grooming', default=False, help="Include grooming services")
    is_training = fields.Boolean(string='Training', default=False, help="Include training services")
    is_boarding = fields.Boolean(string='Boarding', default=False, help="Include boarding services")
    
    # Primary appointment type for categorization
    primary_type = fields.Selection([
        ('checkup', 'Regular Exam'), ('emergency', 'Emergency Exam'),
        ('home_visit', 'Home Visit'),
        ('surgery', 'Surgery'),
        ('dental', 'Dental'), ('comprehensive', 'Comprehensive Care'), ('other', 'Other')
    ], required=True, default='emergency', tracking=True, help="Primary type of appointment")
    name = fields.Char(string='Reference', readonly=True, copy=False, default=lambda s: _('New'), help="Appointment reference")
    title = fields.Char(
        required=True, tracking=True,
        default=lambda self: self._format_appointment_title(_('New'), fields.Datetime.now()),
        help="Appointment title (auto: serial | date time)")
    start_datetime = fields.Datetime(required=True, index=True, tracking=True,
        help="Appointment start time (defaults to the next available slot)")
    end_datetime = fields.Datetime(required=True, index=True, tracking=True,
        help="Appointment end time (follows start using the default duration)")
    vet_employee_id = fields.Many2one(
        'hr.employee', string='Veterinarian', tracking=True,
        default=lambda self: self.env.user.employee_id.id if self.env.user.employee_id else False,
        help="Veterinarian assigned to this appointment")
    resource_id = fields.Many2one(
        'res.partner',
        domain=lambda self: [('id', '=', self.env.user.partner_id.id)] if self.env.user.has_group('pet_management.group_pet_staff_appointments') else [],
        help="Legacy staff field (deprecated — use Veterinarian employee instead)"
    )
    room_id = fields.Many2one('pet.kennel', string='Room', help="Room or kennel for the appointment")
    notes = fields.Text(help="Additional notes about the appointment")
    state = fields.Selection([
        ('draft','Draft'), ('confirmed','Confirmed'), ('in_progress','In Progress'), 
        ('done','Done'), ('cancelled','Cancelled'), ('rescheduled','Rescheduled')
    ], default='draft', index=True, tracking=True, help="Current status of the appointment")
    
    # Enhanced Fields
    duration_minutes = fields.Float(compute='_compute_duration', store=True, help="Duration in minutes")
    duration_display = fields.Char(compute='_compute_duration', store=True, help="Duration in readable format")
    cost = fields.Float(compute='_compute_cost', store=True, help="Automatically calculated cost from connected facility")
    amount_total = fields.Monetary(
        compute='_compute_amount_total', store=True, currency_field='currency_id',
        string='Amount', help="Real billable amount: invoice total when invoiced, otherwise the computed service cost")
    payment_status = fields.Selection([
        ('not_invoiced', 'Not Invoiced'),
        ('draft', 'Draft Invoice'),
        ('pending', 'Not Paid'),
        ('partial', 'Partial'),
        ('paid', 'Paid'),
        ('overpaid', 'Overpaid'),
        ('cancelled', 'Cancelled'),
        ('inconsistent', 'Inconsistent'),
    ], string='Payment Status', compute='_compute_payment_status', store=True,
       help="Payment status aggregated from appointment-linked accounting documents")
    billing_revision = fields.Integer(default=0, copy=False)
    is_complimentary = fields.Boolean(
        string='Complimentary', default=False, tracking=True, copy=False,
        help='Zero-value / complimentary visit. Skips paid-invoice expectations.')
    complimentary_reason = fields.Text(
        string='Complimentary Reason', copy=False,
        help='Required when the appointment is marked complimentary.')
    # Layered billing totals (service → SO → draft → posted → paid → residual → variance)
    service_total = fields.Monetary(
        compute='_compute_billing_totals', store=True, currency_field='currency_id',
        string='Service Total',
        help='Computed service/cost total from facilities and extra lines.')
    sale_order_total = fields.Monetary(
        compute='_compute_billing_totals', store=True, currency_field='currency_id',
        string='Sale Order Total')
    draft_invoice_total = fields.Monetary(
        compute='_compute_billing_totals', store=True, currency_field='currency_id',
        string='Draft Invoice Total')
    total_invoiced = fields.Monetary(
        compute='_compute_billing_totals', store=True, currency_field='currency_id',
        string='Posted Invoice Total',
        help='Net posted customer invoices/credit notes linked to this appointment.')
    total_paid = fields.Monetary(
        compute='_compute_billing_totals', store=True, currency_field='currency_id')
    total_residual = fields.Monetary(
        compute='_compute_billing_totals', store=True, currency_field='currency_id')
    total_customer_credit = fields.Monetary(
        compute='_compute_billing_totals', store=True, currency_field='currency_id',
        help='Unreconciled payment credits explicitly linked to this appointment')
    billing_variance = fields.Monetary(
        compute='_compute_billing_totals', store=True, currency_field='currency_id',
        string='Billing Variance',
        help='Posted invoiced total minus service total (positive = invoiced above services).')
    has_billing_mismatch = fields.Boolean(
        compute='_compute_billing_warning', store=True, index=True,
        help='True when billing integrity warnings are present.')
    billing_warning = fields.Text(
        compute='_compute_billing_warning', store=True,
        help='Human-readable billing integrity warnings for the form banner')
    follow_up_date = fields.Date(help="Recommended follow-up date")
    follow_up_notes = fields.Text(help="Follow-up instructions")
    
    # Calendar Integration Fields
    sync_to_calendar = fields.Boolean(default=True, help="Sync this appointment to calendar")
    calendar_event_id = fields.Many2one('calendar.event', string='Calendar Event', ondelete='set null', help="Linked calendar event")
    enable_calendar_integration = fields.Boolean(compute='_compute_enable_calendar_integration', help="Whether calendar integration is enabled")
    has_calendar_event = fields.Boolean(compute='_compute_has_calendar_event', help="Whether a calendar event is linked")
    
    # Inventory Integration Fields (only if stock module is installed)
    inventory_items_ids = fields.One2many('pet.appointment.inventory', 'appointment_id', string='Inventory Items', help="Items used during appointment")
    inventory_cost = fields.Float(compute='_compute_inventory_cost', store=True, help="Total cost of inventory items used")

    # Additional ad-hoc service/charge lines (billed on top of facility services)
    extra_service_line_ids = fields.One2many(
        'pet.appointment.service.line', 'appointment_id', string='Additional Services',
        help="Extra services or charges added manually; included in the total and the invoice")
    extra_service_cost = fields.Monetary(
        compute='_compute_extra_service_cost', store=True, currency_field='currency_id',
        help="Total of the additional service lines")
    
    # Service Selection Fields (for specific service types)
    service_id = fields.Many2one('pet.grooming.service', string='Grooming Service', help="Selected grooming service")
    program_id = fields.Many2one('pet.training.program', string='Training Program', help="Selected training program")
    vaccine_id = fields.Many2one('pet.vaccine', string='Vaccine', help="Selected vaccine")
    kennel_id = fields.Many2one('pet.kennel', string='Boarding Facility', help="Selected boarding facility")
    
    # Facility Connection Fields (for created facility entries)
    medical_visit_id = fields.Many2one('pet.medical.visit', string='Medical Visit', help="Connected medical visit")
    vaccination_id = fields.Many2one('pet.vaccination', string='Vaccination', help="Connected vaccination")
    grooming_session_id = fields.Many2one('pet.grooming.session', string='Grooming Session', help="Connected grooming session")
    training_session_id = fields.Many2one('pet.training.session', string='Training Session', help="Connected training session")
    boarding_stay_id = fields.Many2one('pet.boarding.stay', string='Boarding Stay', help="Connected boarding stay")
    
    # Auto-creation flags
    auto_create_facility = fields.Boolean(default=True, help="Automatically create facility entry when appointment is confirmed")
    
    # Computed Fields
    days_since_appointment = fields.Integer(compute='_compute_days_since_appointment', store=False, help="Days since the appointment")
    is_overdue = fields.Boolean(compute='_compute_is_overdue', search='_search_is_overdue', store=False, help="Whether appointment is overdue")
    is_today = fields.Boolean(compute='_compute_is_today', store=False, help="Whether appointment is today")
    state_color = fields.Integer(compute='_compute_state_color', string='State Color', store=True, help="Color index for status display")
    
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company, help="Company this appointment belongs to")
    
    # Sales / Invoice Related Fields
    sale_order_id = fields.Many2one('sale.order', string='Sale Order', readonly=True, copy=False, help="Sales order (quotation) generated for this appointment so it appears in the Sales app")
    invoice_ids = fields.One2many(
        'account.move', 'appointment_id', string='Invoices',
        domain=[('move_type', 'in', ('out_invoice', 'out_refund'))],
        copy=False,
        help='All customer invoices/credit notes explicitly linked to this appointment.',
    )
    invoice_count = fields.Integer(compute='_compute_invoice_count')
    invoice_id = fields.Many2one(
        'account.move', string='Primary Invoice', readonly=True, copy=False,
        help='Display/primary invoice (posted preferred, then draft). Does not hide additional invoices.',
    )
    invoice_state = fields.Selection([
        ('no_invoice', 'No Invoice'),
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('cancelled', 'Cancelled')
    ], string='Invoice Status', compute='_compute_invoice_state', store=True, help="Status of the primary invoice")
    invoice_amount = fields.Monetary(related='invoice_id.amount_total', string='Invoice Amount', readonly=True, help="Total amount of the primary invoice")
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', readonly=True, help="Currency")
    has_active_invoice = fields.Boolean(compute='_compute_has_active_invoice')
    
    # Service Status Fields (to track completion status)
    medical_visit_status = fields.Selection(related='medical_visit_id.status', string='Medical Status', readonly=True, help="Status of medical visit")
    vaccination_status = fields.Selection(related='vaccination_id.state', string='Vaccination Status', readonly=True, help="Status of vaccination")
    grooming_session_status = fields.Selection(related='grooming_session_id.state', string='Grooming Status', readonly=True, help="Status of grooming session")
    training_session_status = fields.Selection(related='training_session_id.state', string='Training Status', readonly=True, help="Status of training session")
    boarding_stay_status = fields.Selection(related='boarding_stay_id.state', string='Boarding Status', readonly=True, help="Status of boarding stay")
    
    # Computed cost fields for table display
    medical_visit_cost = fields.Float(related='medical_visit_id.cost', string='Medical Cost', readonly=True, help="Cost of medical visit")
    vaccination_cost = fields.Monetary(related='vaccination_id.cost', string='Vaccination Cost', readonly=True, help="Cost of vaccination")
    vaccine_cost = fields.Float(related='vaccine_id.cost', string='Vaccine Cost', readonly=True, help="Cost of vaccine")
    grooming_session_cost = fields.Float(related='grooming_session_id.total_cost', string='Grooming Session Cost', readonly=True, help="Cost of grooming session")
    grooming_service_cost = fields.Float(related='service_id.base_price', string='Grooming Service Cost', readonly=True, help="Cost of grooming service")
    training_session_cost = fields.Monetary(related='training_session_id.session_cost', string='Training Session Cost', readonly=True, help="Cost of training session")
    training_program_cost = fields.Monetary(related='program_id.base_price', string='Training Program Cost', readonly=True, help="Cost of training program")
    boarding_stay_cost = fields.Float(related='boarding_stay_id.total_cost', string='Boarding Stay Cost', readonly=True, help="Cost of boarding stay")

    @api.depends('invoice_id', 'invoice_id.state', 'invoice_ids', 'invoice_ids.state')
    def _compute_invoice_state(self):
        """Compute invoice state from the primary invoice."""
        for rec in self:
            if rec.invoice_id:
                state_mapping = {
                    'draft': 'draft',
                    'posted': 'posted',
                    'cancel': 'cancelled',
                }
                rec.invoice_state = state_mapping.get(rec.invoice_id.state, 'draft')
            else:
                rec.invoice_state = 'no_invoice'

    @api.depends('invoice_ids')
    def _compute_invoice_count(self):
        for rec in self:
            rec.invoice_count = len(rec._get_linked_invoices())

    @api.depends('invoice_ids', 'invoice_ids.state', 'invoice_id')
    def _compute_has_active_invoice(self):
        for rec in self:
            rec.has_active_invoice = bool(
                rec._get_linked_invoices().filtered(lambda m: m.state != 'cancel')
            )

    @api.depends('start_datetime', 'end_datetime')
    def _compute_duration(self):
        for rec in self:
            if rec.start_datetime and rec.end_datetime:
                delta = rec.end_datetime - rec.start_datetime
                rec.duration_minutes = delta.total_seconds() / 60.0
                hours = int(delta.total_seconds() // 3600)
                minutes = int((delta.total_seconds() % 3600) // 60)
                if hours > 0:
                    rec.duration_display = f"{hours}h {minutes}m" if minutes > 0 else f"{hours}h"
                else:
                    rec.duration_display = f"{minutes}m"
            else:
                rec.duration_minutes = 0.0
                rec.duration_display = "0m"

    @api.depends('start_datetime')
    def _compute_days_since_appointment(self):
        today = fields.Date.today()
        for rec in self:
            if rec.start_datetime:
                appointment_date = rec.start_datetime.date()
                rec.days_since_appointment = (today - appointment_date).days
            else:
                rec.days_since_appointment = 0

    @api.depends('start_datetime', 'state')
    def _compute_is_overdue(self):
        today = fields.Datetime.now()
        for rec in self:
            rec.is_overdue = (
                rec.start_datetime and 
                rec.start_datetime < today and 
                rec.state in ['draft', 'confirmed']
            )

    @api.depends('start_datetime')
    def _compute_is_today(self):
        today = fields.Date.today()
        for rec in self:
            if rec.start_datetime:
                rec.is_today = rec.start_datetime.date() == today
            else:
                rec.is_today = False

    @api.depends('state')
    def _compute_state_color(self):
        color_map = {
            'draft': 1,        # blue
            'confirmed': 2,    # orange
            'in_progress': 3,  # green
            'done': 4,         # green
            'cancelled': 0,    # grey
            'rescheduled': 5,  # purple
        }
        for rec in self:
            rec.state_color = color_map.get(rec.state, 1)

    @api.depends('extra_service_line_ids.price_subtotal')
    def _compute_extra_service_cost(self):
        for rec in self:
            rec.extra_service_cost = sum(rec.extra_service_line_ids.mapped('price_subtotal'))

    @api.depends('medical_visit_id.cost', 'vaccination_id.cost', 'grooming_session_id.total_cost', 
                 'training_session_id.session_cost', 'boarding_stay_id.total_cost', 'vaccine_id.cost', 'service_id.base_price', 'program_id.base_price',
                 'medical_visit_id.status', 'vaccination_id.state', 'grooming_session_id.state', 'training_session_id.state', 'boarding_stay_id.state',
                 'extra_service_line_ids.price_subtotal')
    def _compute_cost(self):
        for rec in self:
            cost = 0.0
            # Add costs only from completed/done services
            
            # Medical Visit - only count if completed
            if rec.medical_visit_id and rec.medical_visit_id.status == 'completed':
                cost += rec.medical_visit_id.cost or 0.0
            
            # Vaccination - only count if administered
            if rec.vaccination_id and rec.vaccination_id.state == 'administered':
                cost += rec.vaccination_id.cost or 0.0
            
            # Vaccine - always count (no status field, assume completed when selected)
            if rec.vaccine_id:
                cost += rec.vaccine_id.cost or 0.0
            
            # Grooming Session - only count if completed
            if rec.grooming_session_id and rec.grooming_session_id.state == 'completed':
                cost += rec.grooming_session_id.total_cost or 0.0
            elif rec.service_id and rec.grooming_session_id and rec.grooming_session_id.state == 'completed':
                # If grooming session is completed, also add base service price
                cost += rec.service_id.base_price or 0.0
            
            # Training Session - only count if completed
            if rec.training_session_id and rec.training_session_id.state == 'completed':
                cost += rec.training_session_id.session_cost or 0.0
            elif rec.program_id and rec.training_session_id and rec.training_session_id.state == 'completed':
                # If training session is completed, also add base program price
                cost += rec.program_id.base_price or 0.0
            
            # Boarding Stay - only count if checked out (completed)
            if rec.boarding_stay_id and rec.boarding_stay_id.state == 'checked_out':
                cost += rec.boarding_stay_id.total_cost or 0.0

            # Additional manual service lines - always counted
            cost += sum(rec.extra_service_line_ids.mapped('price_subtotal'))

            rec.cost = cost

    @api.depends('invoice_id', 'invoice_id.amount_total', 'cost',
                 'total_invoiced', 'is_complimentary')
    def _compute_amount_total(self):
        """Real billable amount: prefer posted invoiced total, else cost."""
        for rec in self:
            if rec.is_complimentary:
                rec.amount_total = 0.0
            elif rec.total_invoiced:
                rec.amount_total = rec.total_invoiced
            elif rec.invoice_id and rec.invoice_id.amount_total:
                rec.amount_total = rec.invoice_id.amount_total
            else:
                rec.amount_total = rec.cost

    @api.depends(
        'invoice_ids', 'invoice_ids.state', 'invoice_ids.amount_total',
        'invoice_ids.amount_residual', 'invoice_ids.payment_state',
        'invoice_ids.move_type', 'invoice_id', 'invoice_id.state',
        'invoice_id.amount_total', 'invoice_id.amount_residual',
        'invoice_id.payment_state', 'state', 'sale_order_id',
        'sale_order_id.amount_total', 'cost', 'is_complimentary',
    )
    def _compute_billing_totals(self):
        for rec in self:
            all_inv = rec._get_linked_invoices().filtered(
                lambda m: m.move_type in ('out_invoice', 'out_refund') and m.state != 'cancel'
            )
            posted = all_inv.filtered(lambda m: m.state == 'posted')
            drafts = all_inv.filtered(lambda m: m.state == 'draft')
            invoiced = 0.0
            residual = 0.0
            paid = 0.0
            draft_total = 0.0
            for inv in posted:
                sign = -1.0 if inv.move_type == 'out_refund' else 1.0
                invoiced += sign * (inv.amount_total or 0.0)
                residual += sign * (inv.amount_residual or 0.0)
                paid += sign * ((inv.amount_total or 0.0) - (inv.amount_residual or 0.0))
            for inv in drafts:
                sign = -1.0 if inv.move_type == 'out_refund' else 1.0
                draft_total += sign * (inv.amount_total or 0.0)
            credit = 0.0
            PaymentMove = rec.env['account.move'].sudo()
            pay_moves = PaymentMove.search([
                ('appointment_id', '=', rec.id),
                ('move_type', '=', 'entry'),
                ('state', '=', 'posted'),
            ])
            for aml in pay_moves.line_ids.filtered(
                lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled
            ):
                credit += max(aml.credit - aml.debit, 0.0)
            so_total = rec.sale_order_id.amount_total if rec.sale_order_id else 0.0
            service = rec.cost or 0.0
            rec.service_total = service
            rec.sale_order_total = so_total
            rec.draft_invoice_total = draft_total
            rec.total_invoiced = invoiced
            rec.total_paid = paid
            rec.total_residual = residual
            rec.total_customer_credit = credit
            rec.billing_variance = invoiced - service

    @api.depends(
        'state', 'invoice_ids', 'invoice_ids.state', 'invoice_ids.payment_state',
        'invoice_id', 'invoice_id.state', 'invoice_id.payment_state',
        'total_invoiced', 'total_paid', 'total_residual', 'total_customer_credit',
        'has_active_invoice', 'is_complimentary',
    )
    def _compute_payment_status(self):
        """Aggregate payment status from all appointment-linked accounting docs."""
        for rec in self:
            if rec.state == 'cancelled':
                rec.payment_status = 'cancelled'
                continue
            if rec.is_complimentary and not rec._get_linked_invoices().filtered(
                lambda m: m.move_type == 'out_invoice' and m.state != 'cancel'
            ):
                rec.payment_status = 'paid'
                continue
            invoices = rec._get_linked_invoices().filtered(
                lambda m: m.move_type == 'out_invoice' and m.state != 'cancel'
            )
            if not invoices:
                rec.payment_status = 'not_invoiced'
                continue
            posted = invoices.filtered(lambda m: m.state == 'posted')
            drafts = invoices.filtered(lambda m: m.state == 'draft')
            currency = rec.currency_id
            rounding = currency.rounding if currency else 0.01
            if drafts and rec.total_customer_credit and not posted:
                rec.payment_status = 'inconsistent'
                continue
            if not posted:
                rec.payment_status = 'draft'
                continue
            if rec.total_customer_credit and rec.total_residual <= rounding and rec.total_paid:
                if rec.total_customer_credit > rounding:
                    rec.payment_status = 'overpaid'
                else:
                    rec.payment_status = 'paid'
                continue
            if rec.total_residual <= rounding and rec.total_invoiced > 0:
                if rec.total_customer_credit > rounding:
                    rec.payment_status = 'overpaid'
                else:
                    rec.payment_status = 'paid'
            elif rec.total_paid > rounding and rec.total_residual > rounding:
                rec.payment_status = 'partial'
            elif rec.total_paid > rec.total_invoiced + rounding:
                rec.payment_status = 'overpaid'
            else:
                rec.payment_status = 'pending'

    @api.depends(
        'invoice_ids', 'invoice_ids.state', 'invoice_ids.is_additional_invoice',
        'sale_order_id', 'sale_order_id.amount_total', 'total_invoiced',
        'total_customer_credit', 'payment_status', 'invoice_id', 'state',
        'cost', 'billing_variance', 'draft_invoice_total', 'is_complimentary',
        'service_total',
    )
    def _compute_billing_warning(self):
        for rec in self:
            warnings = []
            invoices = rec._get_linked_invoices().filtered(lambda m: m.state != 'cancel')
            primaries = invoices.filtered(
                lambda m: m.move_type == 'out_invoice' and not m.is_additional_invoice
            )
            if len(primaries) > 1:
                warnings.append(_('Multiple primary invoices exist for this appointment.'))
            if invoices.filtered(lambda m: m.state == 'draft') and rec.total_customer_credit:
                warnings.append(_('Posted payment credits exist while invoice(s) are still draft.'))
            if rec.payment_status == 'overpaid':
                warnings.append(_('Payments/credits exceed posted invoice totals.'))
            if rec.sale_order_id and rec.total_invoiced and not rec.is_complimentary:
                so_total = rec.sale_order_id.amount_total or 0.0
                if abs(so_total - rec.total_invoiced) > 0.05:
                    warnings.append(_(
                        'Sale order total (%(so)s) differs from posted invoiced total (%(inv)s).',
                        so=so_total, inv=rec.total_invoiced,
                    ))
            if rec.invoice_id and rec.invoice_id not in invoices and invoices:
                warnings.append(_('Primary invoice pointer does not match linked invoices.'))
            if rec.state == 'done' and not invoices and not rec.is_complimentary:
                warnings.append(_('Appointment is done but has no invoice.'))
            if not rec.is_complimentary and abs(rec.billing_variance or 0.0) > 0.05 and rec.total_invoiced:
                warnings.append(_(
                    'Service total (%(svc)s) differs from posted invoiced total (%(inv)s).',
                    svc=rec.service_total or rec.cost or 0.0,
                    inv=rec.total_invoiced,
                ))
            if rec.draft_invoice_total and rec.total_invoiced:
                warnings.append(_(
                    'Draft invoice total (%(draft)s) coexists with posted invoices (%(posted)s).',
                    draft=rec.draft_invoice_total, posted=rec.total_invoiced,
                ))
            if rec.is_complimentary and not (rec.complimentary_reason or '').strip():
                warnings.append(_('Complimentary appointment requires a reason.'))
            rec.billing_warning = '\n'.join(warnings) if warnings else False
            rec.has_billing_mismatch = bool(rec.billing_warning)

    @api.constrains('pet_id', 'intake_owner_id')
    def _check_intake_owner_pet_consistency(self):
        for rec in self:
            if rec.pet_id and rec.intake_owner_id and rec.pet_id.owner_id != rec.intake_owner_id:
                raise ValidationError(
                    _("The selected pet does not belong to the selected owner.")
                )

    @api.model
    def _clinical_primary_types(self):
        return set(self.CLINICAL_PRIMARY_TYPES)

    @api.depends('intake_owner_id', 'intake_owner_id.phone', 'owner_phone')
    def _compute_owner_contact_display(self):
        for rec in self:
            phone = (rec.owner_phone or '').strip()
            if not phone and rec.intake_owner_id:
                phone = (rec.intake_owner_id.phone or '').strip()
            rec.owner_contact_display = phone or False

    @api.depends(
        'pet_id', 'pet_id.allergies', 'pet_id.chronic_conditions',
        'pet_id.dietary_restrictions', 'pet_id.behavior_notes',
    )
    def _compute_health_display(self):
        for rec in self:
            pet = rec.pet_id
            rec.allergies_display = ((pet.allergies or '').strip() or _('No')) if pet else _('No')
            rec.chronic_conditions_display = (
                ((pet.chronic_conditions or '').strip() or _('No')) if pet else _('No')
            )
            rec.dietary_restrictions_display = (
                ((pet.dietary_restrictions or '').strip() or _('No')) if pet else _('No')
            )
            rec.behavior_notes_display = (
                ((pet.behavior_notes or '').strip() or _('No')) if pet else _('No')
            )

    @api.model
    def _get_default_duration_timedelta(self):
        """Default appointment length from settings (hours)."""
        hours = float(
            self.env['ir.config_parameter'].sudo().get_param(
                'pet_management.appointment_duration_default', 1.0
            ) or 1.0
        )
        if hours <= 0:
            hours = 1.0
        return timedelta(hours=hours)

    @api.model
    def _round_datetime_up(self, dt, minutes=15):
        """Round datetime up to the next slot boundary (default 15 minutes)."""
        if not dt:
            return dt
        remainder = (dt.minute % minutes) * 60 + dt.second
        micro = dt.microsecond
        if remainder == 0 and micro == 0:
            return dt.replace(second=0, microsecond=0)
        delta_seconds = (minutes * 60) - remainder
        return (dt + timedelta(seconds=delta_seconds)).replace(second=0, microsecond=0)

    @api.model
    def _appointment_slot_busy(self, start_dt, end_dt, vet_id=False, room_id=False, exclude_id=False):
        """True when vet and/or room already has an overlapping non-cancelled appointment."""
        if not start_dt or not end_dt or end_dt <= start_dt:
            return False
        if not vet_id and not room_id:
            return False
        domain = [
            ('state', 'not in', ['cancelled']),
            ('start_datetime', '<', end_dt),
            ('end_datetime', '>', start_dt),
        ]
        if exclude_id:
            domain.append(('id', '!=', exclude_id))
        if vet_id and room_id:
            domain = domain + ['|', ('vet_employee_id', '=', vet_id), ('room_id', '=', room_id)]
        elif vet_id:
            domain.append(('vet_employee_id', '=', vet_id))
        else:
            domain.append(('room_id', '=', room_id))
        return bool(self.search(domain, limit=1))

    @api.model
    def _find_next_available_slot(
        self, start_from=None, vet_id=False, room_id=False, exclude_id=False, duration=None,
    ):
        """Return (start, end) for the next free slot, skipping vet/room conflicts."""
        duration = duration or self._get_default_duration_timedelta()
        if duration.total_seconds() <= 0:
            duration = timedelta(hours=1.0)
        cursor = self._round_datetime_up(start_from or fields.Datetime.now())
        if not vet_id and not room_id:
            return cursor, cursor + duration

        horizon = cursor + timedelta(days=14)
        domain = [
            ('state', 'not in', ['cancelled']),
            ('end_datetime', '>', cursor),
            ('start_datetime', '<', horizon),
        ]
        if exclude_id:
            domain.append(('id', '!=', exclude_id))
        if vet_id and room_id:
            domain = domain + ['|', ('vet_employee_id', '=', vet_id), ('room_id', '=', room_id)]
        elif vet_id:
            domain.append(('vet_employee_id', '=', vet_id))
        else:
            domain.append(('room_id', '=', room_id))

        busy = self.search(domain, order='start_datetime asc, id asc')
        for appt in busy:
            if appt.end_datetime <= cursor:
                continue
            if appt.start_datetime >= cursor + duration:
                return cursor, cursor + duration
            cursor = self._round_datetime_up(appt.end_datetime)
        return cursor, cursor + duration

    def _duration_for_start_change(self):
        """Prefer saved appointment duration; otherwise settings default."""
        self.ensure_one()
        origin = self._origin
        if origin and origin.id and origin.start_datetime and origin.end_datetime:
            origin_delta = origin.end_datetime - origin.start_datetime
            if origin_delta.total_seconds() > 0:
                return origin_delta
        if (
            self.id
            and self.start_datetime
            and self.end_datetime
            and self.end_datetime > self.start_datetime
        ):
            return self.end_datetime - self.start_datetime
        return self._get_default_duration_timedelta()

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'primary_type' in fields_list and not res.get('primary_type'):
            res['primary_type'] = 'emergency'
        primary = res.get('primary_type') or 'emergency'
        if primary in self._clinical_primary_types():
            res['is_medical'] = True
        pet_id = res.get('pet_id') or self.env.context.get('default_pet_id')
        if pet_id and not res.get('intake_owner_id'):
            pet = self.env['pet.pet'].browse(pet_id)
            if pet.exists() and pet.owner_id:
                res['intake_owner_id'] = pet.owner_id.id

        duration = self._get_default_duration_timedelta()
        vet_id = res.get('vet_employee_id') or (
            self.env.user.employee_id.id if self.env.user.employee_id else False
        )
        room_id = res.get('room_id') or False
        ctx_start = self.env.context.get('default_start_datetime')
        ctx_end = self.env.context.get('default_end_datetime')

        if ctx_start:
            start_dt = fields.Datetime.to_datetime(ctx_start)
            if ctx_end:
                end_dt = fields.Datetime.to_datetime(ctx_end)
            else:
                end_dt = start_dt + duration
            if 'start_datetime' in fields_list:
                res['start_datetime'] = start_dt
            if 'end_datetime' in fields_list:
                res['end_datetime'] = end_dt
        elif 'start_datetime' in fields_list or 'end_datetime' in fields_list:
            start_dt, end_dt = self._find_next_available_slot(
                vet_id=vet_id, room_id=room_id, duration=duration,
            )
            if 'start_datetime' in fields_list:
                res['start_datetime'] = start_dt
            if 'end_datetime' in fields_list:
                res['end_datetime'] = end_dt
        return res

    @api.onchange('primary_type')    @api.onchange('primary_type')
    def _onchange_primary_type_medical(self):
        if self.primary_type in self._clinical_primary_types():
            self.is_medical = True

    @api.onchange('intake_owner_id')
    def _onchange_intake_owner_id(self):
        if not self.intake_owner_id:
            self.pet_id = False
            return
        if self.pet_id and self.pet_id.owner_id != self.intake_owner_id:
            self.pet_id = False
        pets = self.env['pet.pet'].search([('owner_id', '=', self.intake_owner_id.id)])
        if len(pets) == 1:
            self.pet_id = pets
        elif len(pets) == 0:
            self.pet_id = False
        # Multiple pets: do not auto-select after clearing a mismatched pet.

    @api.onchange('pet_id')
    def _onchange_pet_id_intake_owner(self):
        if self.pet_id and self.pet_id.owner_id:
            self.intake_owner_id = self.pet_id.owner_id


    def _check_pet_required_for_operation(self):
        """Block operational/billing workflows until a pet is linked."""
        for rec in self:
            if not rec.pet_id:
                raise UserError(_(
                    "Select or create a pet before confirming or billing this appointment."
                ))

    def action_open_pet_quick_wizard(self):
        """Open Pet / Health Details. Appointment must already be saved."""
        self.ensure_one()
        if not self.env['pet.appointment'].browse(self.id).exists():
            raise UserError(_(
                "Save the appointment before creating or editing pet health details."
            ))
        owner = self.intake_owner_id or self.owner_id
        if not owner:
            raise UserError(_("Select an owner before creating a pet."))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Pet / Health Details'),
            'res_model': 'pet.appointment.pet.quick.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_appointment_id': self.id,
                'default_owner_id': owner.id,
            },
        }

    def _sync_intake_owner_from_pet_vals(self, vals):
        """Ensure intake_owner_id stays consistent with pet_id on create/write."""
        if vals.get('pet_id') and not vals.get('intake_owner_id'):
            pet = self.env['pet.pet'].browse(vals['pet_id'])
            if pet.owner_id:
                vals['intake_owner_id'] = pet.owner_id.id
        return vals

    @api.constrains('is_complimentary', 'complimentary_reason')
    def _check_complimentary_reason(self):
        for rec in self:
            if rec.is_complimentary and not (rec.complimentary_reason or '').strip():
                raise ValidationError(_(
                    'Complimentary appointments require a reason '
                    '(e.g. staff pet, goodwill, warranty redo).'
                ))

    @api.depends('inventory_items_ids', 'inventory_items_ids.total_cost')
    def _compute_inventory_cost(self):
        """Compute total inventory cost for this appointment"""
        for rec in self:
            rec.inventory_cost = sum(rec.inventory_items_ids.mapped('total_cost'))

    def _compute_enable_calendar_integration(self):
        """Compute whether calendar integration is enabled"""
        for rec in self:
            rec.enable_calendar_integration = rec._is_calendar_module_installed()

    @api.depends('calendar_event_id')
    def _compute_has_calendar_event(self):
        """Compute whether a calendar event exists."""
        for rec in self:
            rec.has_calendar_event = bool(rec.calendar_event_id)

    @api.constrains('start_datetime', 'end_datetime')
    def _check_range(self):
        for rec in self:
            if rec.start_datetime and rec.end_datetime and rec.end_datetime <= rec.start_datetime:
                raise ValidationError('End must be after Start.')

    @api.constrains("vet_employee_id", "room_id", "start_datetime", "end_datetime")
    def _check_overlap(self):
        for rec in self:
            # Check veterinarian overlap
            if rec.vet_employee_id:
                vet_overlap = self.search([
                    ("id", "!=", rec.id),
                    ("vet_employee_id", "=", rec.vet_employee_id.id),
                    ("start_datetime", "<=", rec.end_datetime),
                    ("end_datetime", ">=", rec.start_datetime),
                    ("state", "not in", ["cancelled"])
                ], limit=1)
                if vet_overlap:
                    raise ValidationError(_('Veterinarian %s is already booked during this time period.') % rec.vet_employee_id.name)
            
            # Check room overlap
            if rec.room_id:
                room_overlap = self.search([
                    ("id", "!=", rec.id),
                    ("room_id", "=", rec.room_id.id),
                    ("start_datetime", "<=", rec.end_datetime),
                    ("end_datetime", ">=", rec.start_datetime),
                    ("state", "not in", ["cancelled"])
                ], limit=1)
                if room_overlap:
                    raise ValidationError(f"Room {rec.room_id.name} is already booked during this time period.")

    def _search_is_overdue(self, operator, value):
        """Search method for is_overdue field"""
        now = fields.Datetime.now()
        if operator == '=' and value:
            return [
                ('start_datetime', '<', now),
                ('state', 'in', ['draft', 'confirmed'])
            ]
        elif operator == '=' and not value:
            return [
                '|',
                ('start_datetime', '=', False),
                '|',
                ('start_datetime', '>=', now),
                ('state', 'not in', ['draft', 'confirmed'])
            ]
        return []

    def set_to_confirmed(self):
        self._check_pet_required_for_operation()
        for rec in self:
            rec.state = 'confirmed'

    def set_to_in_progress(self):
        self._check_pet_required_for_operation()
        for rec in self:
            rec.state = 'in_progress'

    def set_to_done(self):
        self._check_pet_required_for_operation()
        for rec in self:
            rec.state = 'done'

    def set_to_cancel(self):
        for rec in self:
            rec.state = 'cancelled'

    def set_to_reschedule(self):
        for rec in self:
            rec.state = 'rescheduled'

    def set_to_draft(self):
        for rec in self:
            rec.state = 'draft'

    def _get_primary_type_label(self):
        """Human-readable appointment type for notifications."""
        self.ensure_one()
        labels = dict(self._fields['primary_type']._description_selection(self.env))
        return labels.get(self.primary_type) or self.title or 'pet care'

    def action_send_notification(self):
        """Create and send notification for this appointment"""
        self._check_pet_required_for_operation()
        for rec in self:
            # Determine notification type and priority based on appointment state and timing
            now = fields.Datetime.now()
            time_diff = (rec.start_datetime - now).total_seconds() / 3600  # hours
            
            if rec.state == 'draft':
                notification_type = 'appointment_reminder'
                priority = 'medium'
                message = f"Appointment scheduled: {rec.pet_id.name} has a {rec._get_primary_type_label()} appointment on {rec.start_datetime.strftime('%B %d, %Y at %I:%M %p')}."
            elif rec.state == 'confirmed':
                if time_diff <= 24:  # Within 24 hours
                    notification_type = 'appointment_reminder'
                    priority = 'high'
                    message = f"REMINDER: {rec.pet_id.name}'s {rec._get_primary_type_label()} appointment is tomorrow at {rec.start_datetime.strftime('%I:%M %p')}. Please arrive 10 minutes early."
                else:
                    notification_type = 'appointment_reminder'
                    priority = 'medium'
                    message = f"Confirmed: {rec.pet_id.name}'s {rec._get_primary_type_label()} appointment is scheduled for {rec.start_datetime.strftime('%B %d, %Y at %I:%M %p')}."
            elif rec.state == 'in_progress':
                notification_type = 'general'
                priority = 'medium'
                message = f"In Progress: {rec.pet_id.name}'s {rec._get_primary_type_label()} appointment is currently in progress with {rec.vet_employee_id.name if rec.vet_employee_id else 'staff'}."
            elif rec.state == 'done':
                notification_type = 'general'
                priority = 'low'
                message = f"Completed: {rec.pet_id.name}'s {rec._get_primary_type_label()} appointment was completed on {rec.start_datetime.strftime('%B %d, %Y')}. Follow-up: {rec.follow_up_date.strftime('%B %d, %Y') if rec.follow_up_date else 'Not required'}."
            elif rec.state == 'cancelled':
                notification_type = 'general'
                priority = 'low'
                message = f"Cancelled: {rec.pet_id.name}'s {rec._get_primary_type_label()} appointment scheduled for {rec.start_datetime.strftime('%B %d, %Y at %I:%M %p')} has been cancelled."
            elif rec.state == 'rescheduled':
                notification_type = 'general'
                priority = 'medium'
                message = f"Rescheduled: {rec.pet_id.name}'s {rec._get_primary_type_label()} appointment has been rescheduled. New time: {rec.start_datetime.strftime('%B %d, %Y at %I:%M %p')}."
            else:
                notification_type = 'general'
                priority = 'low'
                message = f"Update: {rec.pet_id.name}'s {rec._get_primary_type_label()} appointment status is {rec.state}."
            
            # Create notification
            notification = self.env['pet.notification'].sudo().create({
                'name': f'Appointment Notification - {rec.pet_id.name}',
                'pet_id': rec.pet_id.id,
                'notification_type': notification_type,
                'message': message,
                'priority': priority,
                'status': 'draft',
                'related_appointment_id': rec.id,
                'date_scheduled': fields.Datetime.now(),
                'is_enabled': True,
                'auto_send': True,
                'preferred_time': 'morning',
                'send_email': True,
                'send_in_app': True,
            })
            
            # Send notification immediately
            notification.action_send_notification()
            
        return {
            'type': 'ir.actions.act_window',
            'name': 'Notification Sent',
            'res_model': 'pet.notification',
            'res_id': notification.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_create_reminder_notification(self):
        """Create a reminder notification for this appointment"""
        self._check_pet_required_for_operation()
        for rec in self:
            if rec.state not in ['draft', 'confirmed']:
                continue
                
            # Check if reminder already exists
            existing = self.env['pet.notification'].search([
                ('related_appointment_id', '=', rec.id),
                ('notification_type', '=', 'appointment_reminder'),
                ('status', 'in', ['draft', 'sent'])
            ])
            
            if not existing:
                notification = self.env['pet.notification'].sudo().create({
                    'name': f'Appointment Reminder - {rec.pet_id.name}',
                    'pet_id': rec.pet_id.id,
                    'notification_type': 'appointment_reminder',
                    'message': f"Reminder: {rec.pet_id.name}'s {rec._get_primary_type_label()} appointment is scheduled for {rec.start_datetime.strftime('%B %d, %Y at %I:%M %p')}. Please arrive 10 minutes early.",
                    'priority': 'high' if (rec.start_datetime - fields.Datetime.now()).total_seconds() <= 86400 else 'medium',  # 24 hours
                    'status': 'draft',
                    'related_appointment_id': rec.id,
                    'date_scheduled': fields.Datetime.now(),
                    'is_enabled': True,
                    'auto_send': True,
                    'preferred_time': 'morning',
                    'send_email': True,
                    'send_in_app': True,
                })
                
                return {
                    'type': 'ir.actions.act_window',
                    'name': 'Reminder Created',
                    'res_model': 'pet.notification',
                    'res_id': notification.id,
                    'view_mode': 'form',
                    'target': 'current',
                }

    def action_view_pet(self):
        """Action to view the pet record"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Pet',
            'res_model': 'pet.pet',
            'res_id': self.pet_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
    
    def action_view_medical_visit(self):
        """Open the medical visit form view"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Medical Visit',
            'res_model': 'pet.medical.visit',
            'view_mode': 'form',
            'res_id': self.medical_visit_id.id,
            'target': 'current',
        }
    
    def action_view_vaccination(self):
        """Open the vaccination form view"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Vaccination',
            'res_model': 'pet.vaccination',
            'view_mode': 'form',
            'res_id': self.vaccination_id.id,
            'target': 'current',
        }
    
    def action_view_vaccine(self):
        """Open the vaccine form view"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Vaccine',
            'res_model': 'pet.vaccine',
            'view_mode': 'form',
            'res_id': self.vaccine_id.id,
            'target': 'current',
        }
    
    def action_view_grooming_session(self):
        """Open the grooming session form view"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Grooming Session',
            'res_model': 'pet.grooming.session',
            'view_mode': 'form',
            'res_id': self.grooming_session_id.id,
            'target': 'current',
        }
    
    def action_view_grooming_service(self):
        """Open the grooming service form view"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Grooming Service',
            'res_model': 'pet.grooming.service',
            'view_mode': 'form',
            'res_id': self.service_id.id,
            'target': 'current',
        }
    
    def action_view_boarding_stay(self):
        """Open the boarding stay form view"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Boarding Stay',
            'res_model': 'pet.boarding.stay',
            'view_mode': 'form',
            'res_id': self.boarding_stay_id.id,
            'target': 'current',
        }
    
    def action_view_kennel(self):
        """Open the kennel form view"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Kennel',
            'res_model': 'pet.kennel',
            'view_mode': 'form',
            'res_id': self.kennel_id.id,
            'target': 'current',
        }
    
    def action_view_training_session(self):
        """Open the training session form view"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Training Session',
            'res_model': 'pet.training.session',
            'view_mode': 'form',
            'res_id': self.training_session_id.id,
            'target': 'current',
        }
    
    def action_view_training_program(self):
        """Open the training program form view"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Training Program',
            'res_model': 'pet.training.program',
            'view_mode': 'form',
            'res_id': self.program_id.id,
            'target': 'current',
        }

    def action_create_facility_entry(self):
        """Create facility entries based on selected service types"""
        self._check_pet_required_for_operation()
        for rec in self:
            if not rec.auto_create_facility:
                continue
                
            # Create medical visit if medical services are selected
            if rec.is_medical or rec.primary_type in ['checkup', 'emergency', 'home_visit', 'surgery', 'dental', 'comprehensive']:
                rec._create_medical_visit()
            
            # Create vaccination if vaccination services are selected
            if rec.is_vaccination and rec.vaccine_id:
                rec._create_vaccination()
            
            # Create grooming session if grooming services are selected
            if rec.is_grooming and rec.service_id:
                rec._create_grooming_session()
            
            # Create training session if training services are selected
            if rec.is_training and rec.program_id:
                rec._create_training_session()
            
            # Create boarding stay if boarding services are selected
            if rec.is_boarding and rec.kennel_id:
                rec._create_boarding_stay()

    def action_create_medical_visit(self):
        """Manually create medical visit entry"""
        self._check_pet_required_for_operation()
        for rec in self:
            rec._create_medical_visit()

    def action_create_vaccination(self):
        """Manually create vaccination entry"""
        self._check_pet_required_for_operation()
        for rec in self:
            if rec.vaccine_id:
                rec._create_vaccination()
            else:
                raise ValidationError("Please select a vaccine before creating vaccination entry.")

    def action_create_grooming_session(self):
        """Manually create grooming session entry"""
        self._check_pet_required_for_operation()
        for rec in self:
            if rec.service_id:
                rec._create_grooming_session()
            else:
                raise ValidationError("Please select a grooming service before creating grooming session.")

    def action_create_training_session(self):
        """Manually create training session entry"""
        self._check_pet_required_for_operation()
        for rec in self:
            if rec.program_id:
                rec._create_training_session()
            else:
                raise ValidationError("Please select a training program before creating training session.")

    def action_create_boarding_stay(self):
        """Manually create boarding stay entry"""
        self._check_pet_required_for_operation()
        for rec in self:
            if rec.kennel_id:
                rec._create_boarding_stay()
            else:
                raise ValidationError("Please select a kennel before creating boarding stay.")

    @api.model
    def _map_primary_type_to_visit_type(self, primary_type):
        mapping = {
            'comprehensive': 'checkup',
        }
        visit_types = dict(self.env['pet.medical.visit'].VISIT_TYPE_SELECTION)
        if primary_type in visit_types:
            return primary_type
        return mapping.get(primary_type, 'other')

    def _vet_partner_id(self, employee=None):
        """Map hr.employee to res.partner for legacy vet_id fields on visits/vaccinations."""
        employee = employee or self.vet_employee_id
        if not employee:
            return False
        if employee.work_contact_id:
            return employee.work_contact_id.id
        if employee.user_id and employee.user_id.partner_id:
            return employee.user_id.partner_id.id
        return False

    def _format_appointment_title(self, name, start_datetime=None):
        """Build default title: APT26-0001 | 08/07/2026 14:30"""
        start_dt = start_datetime or fields.Datetime.now()
        local_dt = fields.Datetime.context_timestamp(self, start_dt)
        stamp = local_dt.strftime('%d/%m/%Y %H:%M')
        ref = name if name and name != _('New') else _('Appointment')
        return f'{ref} | {stamp}'

    @api.onchange('start_datetime')
    def _onchange_start_datetime_title(self):
        """Keep end in sync with start, and refresh draft title on new appointments."""
        if not self.start_datetime:
            return
        self.end_datetime = self.start_datetime + self._duration_for_start_change()
        if not self._origin.id:
            self.title = self._format_appointment_title(self.name or _('New'), self.start_datetime)

    @api.onchange('vet_employee_id', 'room_id')
    def _onchange_vet_or_room_find_slot(self):
        """If the current window conflicts for vet/room, jump to the next free slot."""
        if not self.start_datetime:
            return
        if self.state in ('done', 'cancelled'):
            return
        duration = self._duration_for_start_change()
        end_dt = self.start_datetime + duration
        vet_id = self.vet_employee_id.id if self.vet_employee_id else False
        room_id = self.room_id.id if self.room_id else False
        exclude_id = self._origin.id if self._origin.id else False
        if not self._appointment_slot_busy(
            self.start_datetime, end_dt, vet_id=vet_id, room_id=room_id, exclude_id=exclude_id,
        ):
            self.end_datetime = end_dt
            return
        start_dt, end_dt = self._find_next_available_slot(
            start_from=self.start_datetime,
            vet_id=vet_id,
            room_id=room_id,
            exclude_id=exclude_id,
            duration=duration,
        )
        self.start_datetime = start_dt
        self.end_datetime = end_dt
        if not exclude_id:
            self.title = self._format_appointment_title(self.name or _('New'), start_dt)

    def _create_medical_visit(self):
        """Create medical visit entry"""
        if not self.medical_visit_id:
            visit_vals = {
                'pet_id': self.pet_id.id,
                'date': self.start_datetime,
                'visit_type': self._map_primary_type_to_visit_type(self.primary_type),
                'reason': self.title,
                'vet_employee_id': self.vet_employee_id.id if self.vet_employee_id else False,
                'vet_id': self._vet_partner_id(),
                'plan': self.notes,
                'appointment_id': self.id,
            }
            visit = self.env['pet.medical.visit'].sudo().create(visit_vals)
            self.medical_visit_id = visit.id

    def _create_vaccination(self):
        """Create vaccination entry"""
        if not self.vaccination_id and self.vaccine_id:
            vacc_vals = {
                'pet_id': self.pet_id.id,
                'vaccine_id': self.vaccine_id.id,
                'date_administered': self.start_datetime.date(),
                'vet_employee_id': self.vet_employee_id.id if self.vet_employee_id else False,
                'vet_id': self._vet_partner_id(),
                'notes': self.notes,
                'appointment_id': self.id,
                'state': 'scheduled',
                'vaccination_type': 'initial',
            }
            vaccination = self.env['pet.vaccination'].sudo().create(vacc_vals)
            self.vaccination_id = vaccination.id

    def _create_grooming_session(self):
        """Create grooming session entry"""
        if not self.grooming_session_id and self.service_id:
            # Find a valid groomer (employee) or leave it empty
            groomer_id = self.vet_employee_id.id if self.vet_employee_id else False
            if not groomer_id:
                # Try to find any available groomer
                groomer = self.env['hr.employee'].search([('active', '=', True)], limit=1)
                if groomer:
                    groomer_id = groomer.id
            
            session_vals = {
                'pet_id': self.pet_id.id,
                'service_id': self.service_id.id,
                'appointment_datetime': self.start_datetime,
                'groomer_id': groomer_id,
                'notes': self.notes,
                'appointment_id': self.id,
                'state': 'confirmed',
            }
            session = self.env['pet.grooming.session'].sudo().create(session_vals)
            self.grooming_session_id = session.id

    def _create_training_session(self):
        """Create training session entry"""
        if not self.training_session_id and self.program_id:
            # Find a valid trainer (employee) or leave it empty
            trainer_id = self.vet_employee_id.id if self.vet_employee_id else False
            if not trainer_id:
                # Try to find any available trainer
                trainer = self.env['hr.employee'].search([('active', '=', True)], limit=1)
                if trainer:
                    trainer_id = trainer.id
            
            session_vals = {
                'pet_id': self.pet_id.id,
                'program_id': self.program_id.id,
                'session_datetime': self.start_datetime,
                'trainer_id': trainer_id,
                'session_notes': self.notes,
                'appointment_id': self.id,
                'state': 'confirmed',
            }
            session = self.env['pet.training.session'].sudo().create(session_vals)
            self.training_session_id = session.id

    def _create_boarding_stay(self):
        """Create boarding stay entry"""
        if not self.boarding_stay_id and self.kennel_id:
            stay_vals = {
                'pet_id': self.pet_id.id,
                'kennel_id': self.kennel_id.id,
                'check_in': self.start_datetime,
                'check_out': self.end_datetime,
                'special_instructions': self.notes,
                'appointment_id': self.id,
                'state': 'confirmed',
            }
            stay = self.env['pet.boarding.stay'].sudo().create(stay_vals)
            self.boarding_stay_id = stay.id

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to generate sequence and auto-create facility entry"""
        for vals in vals_list:
            self._sync_intake_owner_from_pet_vals(vals)
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('pet.appointment') or _('New')
            if not vals.get('vet_employee_id') and self.env.user.employee_id:
                vals['vet_employee_id'] = self.env.user.employee_id.id
            primary = vals.get('primary_type', 'emergency')
            if primary in self._clinical_primary_types() and 'is_medical' not in vals:
                vals['is_medical'] = True

            # Apply default duration / next available slot when times are missing
            if vals.get('start_datetime') and not vals.get('end_datetime'):
                start_dt = vals['start_datetime']
                if isinstance(start_dt, str):
                    start_dt = fields.Datetime.to_datetime(start_dt)
                vals['end_datetime'] = start_dt + self._get_default_duration_timedelta()
            elif not vals.get('start_datetime') or not vals.get('end_datetime'):
                start_dt, end_dt = self._find_next_available_slot(
                    vet_id=vals.get('vet_employee_id') or False,
                    room_id=vals.get('room_id') or False,
                )
                vals.setdefault('start_datetime', start_dt)
                vals.setdefault('end_datetime', end_dt)

            if not vals.get('title'):
                vals['title'] = self._format_appointment_title(
                    vals.get('name', _('New')),
                    vals.get('start_datetime'),
                )
                
        appointments = super().create(vals_list)
        for appointment in appointments:
            if appointment.auto_create_facility and appointment.state == 'confirmed':
                appointment.action_create_facility_entry()
            
            # Auto-sync to calendar if enabled
            if appointment.sync_to_calendar and appointment._is_calendar_module_installed():
                icp = self.env['ir.config_parameter'].sudo()
                enable_calendar = icp.get_param('pet_management.enable_calendar_integration') in (True, 'True', '1', 1)
                if enable_calendar:
                    appointment.action_sync_to_calendar()
                    
        return appointments

    def write(self, vals):
        """Override write to auto-create facility entry when confirmed and refresh invoice when needed"""
        self._sync_intake_owner_from_pet_vals(vals)
        # Changing start without end keeps the same duration and moves the end.
        if 'start_datetime' in vals and 'end_datetime' not in vals and len(self) == 1:
            start_dt = fields.Datetime.to_datetime(vals['start_datetime'])
            duration = self._get_default_duration_timedelta()
            if self.start_datetime and self.end_datetime and self.end_datetime > self.start_datetime:
                duration = self.end_datetime - self.start_datetime
            vals['end_datetime'] = start_dt + duration
        if vals.get('state') in ('confirmed', 'in_progress', 'done'):
            # Guard even if state is written directly (not only via set_to_* helpers).
            if 'pet_id' in vals and not vals.get('pet_id'):
                raise UserError(_(
                    "Select or create a pet before confirming or billing this appointment."
                ))
            if not vals.get('pet_id'):
                self.filtered(lambda r: not r.pet_id)._check_pet_required_for_operation()
        # Clear service fields when service types are unchecked
        service_type_mappings = {
            'is_medical': ['medical_visit_id'],
            'is_vaccination': ['vaccination_id', 'vaccine_id'],
            'is_grooming': ['grooming_session_id', 'service_id'],
            'is_training': ['training_session_id', 'program_id'],
            'is_boarding': ['boarding_stay_id', 'kennel_id']
        }
        
        # Check if any service type is being unchecked
        for service_type, related_fields in service_type_mappings.items():
            if service_type in vals and not vals[service_type]:
                # Clear all related fields when service type is unchecked
                for field in related_fields:
                    if field not in vals:  # Only clear if not explicitly set
                        vals[field] = False

        result = super().write(vals)

        # Propagate a changed veterinarian to already-created facility records
        if 'vet_employee_id' in vals:
            for rec in self:
                vet = rec.vet_employee_id.id if rec.vet_employee_id else False
                partner = rec._vet_partner_id()
                if rec.medical_visit_id:
                    rec.medical_visit_id.write({'vet_employee_id': vet, 'vet_id': partner})
                if rec.vaccination_id:
                    rec.vaccination_id.write({'vet_employee_id': vet, 'vet_id': partner})

        # Auto-create facility entry when confirmed
        if 'state' in vals and vals['state'] == 'confirmed':
            for rec in self:
                if rec.auto_create_facility:
                    rec.action_create_facility_entry()
        
        # Auto-link facility records to appointment
        facility_fields = [
            'medical_visit_id', 'vaccination_id', 'grooming_session_id', 
            'training_session_id', 'boarding_stay_id'
        ]
        
        for field in facility_fields:
            if field in vals and vals[field]:
                for rec in self:
                    facility_record = getattr(rec, field)
                    if facility_record and hasattr(facility_record, 'appointment_id'):
                        facility_record.write({'appointment_id': rec.id})
        
        return result

    def _refresh_invoice_sync(self):
        """Synchronous method to refresh invoice without UI interaction"""
        if self.invoice_id and self.invoice_state == 'draft':
            # First, recalculate appointment cost to ensure it's up to date
            self._compute_cost()
            
            # Clear existing invoice lines
            self.invoice_id.invoice_line_ids.unlink()
            
            # Recreate invoice lines with current data
            invoice_lines = self._prepare_invoice_lines()
            total_amount = 0.0
            
            for line_vals in invoice_lines:
                line_vals['move_id'] = self.invoice_id.id
                line = self.env['account.move.line'].sudo().create(line_vals)
                total_amount += line.price_subtotal
            
            # Manually update invoice amounts to avoid expensive compute methods
            self.invoice_id.write({
                'amount_untaxed': total_amount,
                'amount_total': total_amount,  # Assuming no taxes for now
            })

    def name_get(self):
        """Custom name_get to show pet name and title in Many2one selection"""
        result = []
        for rec in self:
            pet_name = rec.pet_id.name if rec.pet_id else 'Unknown Pet'
            title = rec.title if rec.title else 'No Title'
            name = f"{pet_name} - {title}"
            result.append((rec.id, name))
        return result

    def _get_generic_service_product(self):
        """Find or create a generic service product used for sale order lines
        that have no dedicated product (grooming, training, boarding, discounts...).
        invoice_policy='order' guarantees confirmed lines are immediately invoiceable."""
        Product = self.env['product.product'].sudo()
        product = Product.search([('default_code', '=', 'PET-SERVICE')], limit=1)
        if not product:
            product = Product.create({
                'name': 'Pet Care Service',
                'default_code': 'PET-SERVICE',
                'type': 'service',
                'invoice_policy': 'order',
                'list_price': 0.0,
                'taxes_id': [(6, 0, [])],
            })
        return product

    def _lock_appointment_row(self):
        """Acquire a PostgreSQL row lock before billing create/check operations."""
        self.ensure_one()
        self.env.cr.execute(
            'SELECT id FROM pet_appointment WHERE id = %s FOR UPDATE',
            [self.id],
        )
        self.invalidate_recordset()

    def _get_linked_invoices(self):
        """Return all customer invoices/credit notes for this appointment.

        Primary: explicit appointment_id. Legacy fallback: sale_order invoices
        and singular invoice_id. Origin text is last resort and only when it
        exactly matches this appointment name.
        """
        self.ensure_one()
        Move = self.env['account.move']
        invoices = self.invoice_ids
        if self.sale_order_id:
            invoices |= self.sale_order_id.invoice_ids
        if self.invoice_id:
            invoices |= self.invoice_id
        if not invoices and self.name:
            # Last-resort legacy: exact origin match only
            invoices |= Move.search([
                ('move_type', 'in', ('out_invoice', 'out_refund')),
                ('invoice_origin', 'in', [self.name, self.sale_order_id.name if self.sale_order_id else '']),
                ('partner_id', '=', self.owner_id.id),
            ]) if self.owner_id else Move.browse()
        return invoices.filtered(lambda m: m.move_type in ('out_invoice', 'out_refund'))

    def _recompute_primary_invoice(self):
        """Set invoice_id to preferred primary: posted > draft > oldest."""
        for rec in self:
            invoices = rec._get_linked_invoices().filtered(
                lambda m: m.move_type == 'out_invoice' and m.state != 'cancel'
            )
            posted = invoices.filtered(lambda m: m.state == 'posted').sorted('id')
            drafts = invoices.filtered(lambda m: m.state == 'draft').sorted('id')
            primary = posted[:1] or drafts[:1] or invoices.sorted('id')[:1]
            if primary and rec.invoice_id != primary:
                rec.invoice_id = primary.id
            elif not primary and rec.invoice_id:
                rec.invoice_id = False
            # Backfill appointment_id on legacy invoices
            for inv in invoices:
                if not inv.appointment_id:
                    inv.appointment_id = rec.id

    def _prepare_sale_order_lines(self):
        """Build sale.order.line values mirroring the billable services.
        Every line carries a product (dedicated when available, else generic).
        Extra lines include appointment_service_line_id in a transient key
        consumed by _ensure_sale_order / _resync_draft_sale_order.
        """
        self.ensure_one()
        generic = self._get_generic_service_product()
        lines = []

        def add(name, price, product=None, qty=1.0, discount=0.0, service_line=None, visit_line=None):
            vals = {
                'product_id': (product.id if product else generic.id),
                'name': name,
                'product_uom_qty': qty or 1.0,
                'price_unit': price,
                'discount': discount or 0.0,
                'tax_ids': [(6, 0, [])],
            }
            if service_line:
                vals['_appointment_service_line_id'] = service_line.id
            if visit_line:
                vals['_medical_visit_line_id'] = visit_line.id
            lines.append(vals)

        if self.medical_visit_id:
            visit = self.medical_visit_id
            visit_lines = visit.line_ids.filtered(lambda line: line.price_subtotal > 0)
            if visit_lines:
                for line in visit_lines:
                    add(line.name, line.price_unit,
                        product=line.product_id or None,
                        qty=line.quantity or 1.0,
                        discount=line.discount or 0.0,
                        visit_line=line)
                if visit.status == 'completed' and visit.discount_amount:
                    add(_('Visit discount'), -abs(visit.discount_amount))
            elif visit.status == 'completed' and visit.cost:
                add(f"Medical Visit - {visit.reason or 'Consultation'}", visit.cost)

        if self.vaccination_id and self.vaccination_id.cost and self.vaccination_id.state == 'administered':
            add(f"Vaccination - {self.vaccination_id.vaccine_id.name if self.vaccination_id.vaccine_id else 'Vaccine'}",
                self.vaccination_id.cost)

        if self.vaccine_id and self.vaccine_id.cost:
            add(f"Vaccine - {self.vaccine_id.name}", self.vaccine_id.cost)

        if self.grooming_session_id and self.grooming_session_id.total_cost and self.grooming_session_id.state == 'completed':
            add(f"Grooming - {self.grooming_session_id.service_id.name if self.grooming_session_id.service_id else 'Grooming Service'}",
                self.grooming_session_id.total_cost)
        elif self.service_id and self.service_id.base_price and self.grooming_session_id and self.grooming_session_id.state == 'completed':
            add(f"Grooming Service - {self.service_id.name}", self.service_id.base_price)

        if self.training_session_id and self.training_session_id.session_cost and self.training_session_id.state == 'completed':
            add(f"Training - {self.training_session_id.program_id.name if self.training_session_id.program_id else 'Training Program'}",
                self.training_session_id.session_cost)
        elif self.program_id and self.program_id.base_price and self.training_session_id and self.training_session_id.state == 'completed':
            add(f"Training Program - {self.program_id.name}", self.program_id.base_price)

        if self.boarding_stay_id and self.boarding_stay_id.total_cost and self.boarding_stay_id.state == 'checked_out':
            add(f"Boarding - {self.boarding_stay_id.kennel_id.name if self.boarding_stay_id.kennel_id else 'Boarding Stay'}",
                self.boarding_stay_id.total_cost)

        for line in self.extra_service_line_ids:
            if line.invoice_synced:
                continue
            if line.medical_visit_line_id:
                # Already billed via medical visit explosion
                continue
            if line.price_subtotal:
                add(line.name or (line.product_id.display_name if line.product_id else _('Service')),
                    line.price_unit,
                    product=line.product_id or None,
                    qty=line.quantity or 1.0,
                    discount=line.discount or 0.0,
                    service_line=line)

        if not lines and self.cost > 0:
            add(f"Appointment - {self.title or 'Pet Care Services'}", self.cost)

        return lines

    def _link_sale_lines_to_sources(self, order, line_vals):
        """Persist sale_line_id on appointment service lines after SO write."""
        self.ensure_one()
        for so_line, lv in zip(order.order_line.filtered(lambda l: not l.display_type), line_vals):
            svc_id = lv.pop('_appointment_service_line_id', None) if isinstance(lv, dict) else None
            # line_vals may already have been stripped; read from so_line name match fallback skipped
            if svc_id:
                svc = self.env['pet.appointment.service.line'].browse(svc_id)
                if svc.exists():
                    svc.with_context(skip_appointment_so_resync=True).sale_line_id = so_line.id

    def _resync_draft_sale_order(self):
        """Rebuild the sale order lines from current services when the order is
        still an editable quotation (not confirmed/invoiced)."""
        if self.env.context.get('skip_appointment_so_resync'):
            return
        for rec in self:
            order = rec.sale_order_id
            if not order or rec.has_active_invoice:
                continue
            if order.state not in ('draft', 'sent'):
                raise UserError(_(
                    'Cannot rebuild sale order %(order)s because it is already confirmed. '
                    'Edit the quotation before confirming, or set line quantities to 0 on a '
                    'confirmed order instead of deleting lines.\n'
                    'لا يمكن تعديل أمر البيع المؤكد؛ اضبط الكمية إلى 0 بدلاً من الحذف.',
                    order=order.name,
                ))
            raw_vals = rec._prepare_sale_order_lines()
            clean_vals = []
            source_map = []
            for lv in raw_vals:
                lv = dict(lv)
                svc_id = lv.pop('_appointment_service_line_id', None)
                lv.pop('_medical_visit_line_id', None)
                clean_vals.append(lv)
                source_map.append(svc_id)
            commands = [(5, 0, 0)] + [(0, 0, lv) for lv in clean_vals]
            order.sudo().write({'order_line': commands})
            for so_line, lv, svc_id in zip(order.order_line, clean_vals, source_map):
                so_line.write({'price_unit': lv['price_unit'], 'tax_ids': [(6, 0, [])]})
                if svc_id:
                    self.env['pet.appointment.service.line'].browse(svc_id).with_context(
                        skip_appointment_so_resync=True
                    ).write({'sale_line_id': so_line.id})

    def _ensure_sale_order(self):
        """Create (once) the sale order/quotation for this appointment (locked)."""
        self.ensure_one()
        self._lock_appointment_row()
        if self.sale_order_id:
            if not self.sale_order_id.appointment_id:
                self.sale_order_id.appointment_id = self.id
            return self.sale_order_id
        if not self.owner_id:
            raise ValidationError(_('Cannot create a sale order without a customer/owner on the pet.'))
        raw_vals = self._prepare_sale_order_lines()
        if not raw_vals:
            generic = self._get_generic_service_product()
            raw_vals = [{
                'product_id': generic.id,
                'name': self.title or self.name or _('Pet Care Service'),
                'product_uom_qty': 1.0,
                'price_unit': self.cost or 0.0,
                'discount': 0.0,
                'tax_ids': [(6, 0, [])],
            }]
        clean_vals = []
        source_map = []
        for lv in raw_vals:
            lv = dict(lv)
            svc_id = lv.pop('_appointment_service_line_id', None)
            lv.pop('_medical_visit_line_id', None)
            clean_vals.append(lv)
            source_map.append(svc_id)
        order = self.env['sale.order'].sudo().create({
            'partner_id': self.owner_id.id,
            'origin': self.name,
            'client_order_ref': self.name,
            'company_id': self.company_id.id,
            'appointment_id': self.id,
            'order_line': [(0, 0, lv) for lv in clean_vals],
        })
        for so_line, lv, svc_id in zip(order.order_line, clean_vals, source_map):
            so_line.write({'price_unit': lv['price_unit'], 'tax_ids': [(6, 0, [])]})
            if svc_id:
                self.env['pet.appointment.service.line'].browse(svc_id).with_context(
                    skip_appointment_so_resync=True
                ).write({'sale_line_id': so_line.id})
        self.sale_order_id = order.id
        return order

    def _sync_services_from_invoice(self):
        """Sync invoice-sourced extras by stable identity; never duplicate visit lines."""
        ServiceLine = self.env['pet.appointment.service.line'].with_context(
            skip_appointment_so_resync=True,
        )
        for rec in self:
            posted = rec._get_linked_invoices().filtered(
                lambda m: m.move_type == 'out_invoice' and m.state == 'posted'
            )
            if not posted and not rec.sale_order_id:
                continue
            source_lines = posted.mapped('invoice_line_ids').filtered(
                lambda l: l.display_type == 'product' and (l.product_id or (l.name and l.price_subtotal))
            )
            visit_product_ids = set()
            if rec.medical_visit_id:
                visit_product_ids = set(rec.medical_visit_id.line_ids.mapped('product_id').ids)

            existing_by_inv_line = {
                line.id: svc
                for svc in rec.extra_service_line_ids
                for line in svc.invoice_line_ids
            }
            existing_by_sale = {
                svc.sale_line_id.id: svc
                for svc in rec.extra_service_line_ids
                if svc.sale_line_id
            }
            existing_keys = {
                (svc.product_id.id or 0, (svc.name or '').strip(), round(svc.price_unit or 0.0, 2), round(svc.quantity or 0.0, 2))
                for svc in rec.extra_service_line_ids
            }

            for aml in source_lines:
                if aml.product_id and aml.product_id.id in visit_product_ids and not aml.appointment_service_line_id:
                    if aml.sale_line_ids:
                        continue
                if aml.appointment_service_line_id:
                    continue
                sale_lines = aml.sale_line_ids
                if sale_lines and sale_lines[0].id in existing_by_sale:
                    svc = existing_by_sale[sale_lines[0].id]
                    aml.appointment_service_line_id = svc.id
                    continue
                if aml.id in existing_by_inv_line:
                    continue
                key = (
                    aml.product_id.id if aml.product_id else 0,
                    (aml.name or '').strip(),
                    round(aml.price_unit or 0.0, 2),
                    round(aml.quantity or 0.0, 2),
                )
                if key in existing_keys:
                    continue
                qty = aml.quantity or 1.0
                product = aml.product_id or rec._get_generic_service_product()
                svc = ServiceLine.create({
                    'appointment_id': rec.id,
                    'product_id': product.id,
                    'name': aml.name or product.display_name,
                    'quantity': qty,
                    'price_unit': aml.price_unit or 0.0,
                    'discount': aml.discount or 0.0,
                    'invoice_synced': True,
                    'sale_line_id': sale_lines[:1].id if sale_lines else False,
                })
                aml.appointment_service_line_id = svc.id
                existing_keys.add(key)

    def action_open_billing_repair_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Repair Billing Metadata'),
            'res_model': 'pet.appointment.billing.repair.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_appointment_id': self.id},
        }

    def _align_sale_order_metadata_from_invoices(self):
        """Add missing SO lines for posted invoice lines; never change invoice amounts."""
        self.ensure_one()
        order = self.sale_order_id
        if not order:
            raise UserError(_('No sale order to align.'))
        posted = self._get_linked_invoices().filtered(
            lambda m: m.move_type == 'out_invoice' and m.state == 'posted'
        )
        if not posted:
            raise UserError(_('No posted invoice to align from.'))
        if order.state in ('draft', 'sent'):
            self._sync_services_from_invoice()
            self.with_context(skip_appointment_so_resync=False)._resync_draft_sale_order()
            return True

        generic = self._get_generic_service_product()
        linked_aml_ids = set()
        for sol in order.order_line:
            linked_aml_ids.update(sol.invoice_lines.ids)

        created = self.env['sale.order.line']
        for aml in posted.mapped('invoice_line_ids').filtered(
            lambda l: l.display_type == 'product' and (l.price_subtotal or l.product_id)
        ):
            if aml.id in linked_aml_ids or aml.sale_line_ids:
                continue
            product = aml.product_id or generic
            sol = self.env['sale.order.line'].sudo().create({
                'order_id': order.id,
                'product_id': product.id,
                'name': aml.name or product.display_name,
                'product_uom_qty': aml.quantity or 1.0,
                'price_unit': aml.price_unit or 0.0,
                'discount': aml.discount or 0.0,
                'tax_ids': [(6, 0, [])],
            })
            aml.sudo().write({'sale_line_ids': [(4, sol.id)]})
            created |= sol
            linked_aml_ids.add(aml.id)
        if created:
            self.message_post(body=_(
                'Metadata repair: added %(n)s sale order line(s) linked to existing posted invoice lines. '
                'Posted invoice amounts were not modified.',
                n=len(created),
            ))
        return True

    def action_create_or_open_sale_order(self):
        """Idempotent: lock, return existing SO or create one draft SO, open it."""
        self.ensure_one()
        self._check_pet_required_for_operation()
        self._lock_appointment_row()
        active = self._get_linked_invoices().filtered(lambda m: m.state != 'cancel')
        if active and not self.sale_order_id:
            self._recompute_primary_invoice()
            return self.action_view_invoice()
        order = self._ensure_sale_order()
        if order.state in ('draft', 'sent') and not active:
            self._resync_draft_sale_order()
        return self.action_view_sale_order()

    def action_create_invoice(self):
        """Backward-compatible wrapper: create/open Sale Order only (no invoice)."""
        return self.action_create_or_open_sale_order()

    def action_confirm_and_create_invoice(self):
        """Confirm SO and create exactly one primary invoice (idempotent + locked)."""
        self.ensure_one()
        self._check_pet_required_for_operation()
        self._lock_appointment_row()
        existing = self._get_linked_invoices().filtered(
            lambda m: m.move_type == 'out_invoice' and m.state != 'cancel'
        )
        if existing:
            self._recompute_primary_invoice()
            return self.action_view_invoice()
        order = self._ensure_sale_order()
        if order.state in ('draft', 'sent'):
            order.action_confirm()
        elif order.state == 'cancel':
            raise UserError(_(
                'Sale order %(order)s is cancelled and cannot be invoiced.',
                order=order.name,
            ))
        # Re-check after confirm (another worker may have invoiced)
        self.invalidate_recordset()
        existing = self._get_linked_invoices().filtered(
            lambda m: m.move_type == 'out_invoice' and m.state != 'cancel'
        )
        if existing:
            self._recompute_primary_invoice()
            return self.action_view_invoice()
        invoices = order._create_invoices()
        if not invoices:
            raise UserError(_(
                'No invoice was created from sale order %(order)s. '
                'Check that the order has billable lines.',
                order=order.name,
            ))
        invoices.write({'appointment_id': self.id, 'is_additional_invoice': False})
        invoices.action_post()
        # Link payment moves created later via register wizard inherit appointment_id on invoice
        self.invoice_id = invoices[0].id
        self._sync_services_from_invoice()
        self._recompute_primary_invoice()
        return self.action_view_invoice()

    def action_open_additional_invoice_wizard(self):
        self.ensure_one()
        self._check_pet_required_for_operation()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Create Additional Invoice'),
            'res_model': 'pet.appointment.additional.invoice.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_appointment_id': self.id},
        }

    def action_view_sale_order(self):
        """Open the sale order for this appointment."""
        self.ensure_one()
        if not self.sale_order_id:
            return self.action_create_or_open_sale_order()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sale Order'),
            'res_model': 'sale.order',
            'view_mode': 'form',
            'res_id': self.sale_order_id.id,
            'target': 'current',
        }

    def action_view_invoices(self):
        self.ensure_one()
        invoices = self._get_linked_invoices()
        if len(invoices) == 1:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Invoice'),
                'res_model': 'account.move',
                'view_mode': 'form',
                'res_id': invoices.id,
                'target': 'current',
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Invoices'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', invoices.ids)],
            'target': 'current',
        }

    def action_register_appointment_payment(self):
        """Open payment register on posted appointment invoices with residual."""
        self.ensure_one()
        self._check_pet_required_for_operation()
        invoices = self._get_linked_invoices().filtered(
            lambda m: m.state == 'posted' and m.move_type == 'out_invoice' and m.amount_residual > 0
        )
        if not invoices:
            raise UserError(_('No posted appointment invoice with residual to pay.'))
        return invoices.action_register_payment()

    def _collect_billing_integrity_findings(self):
        """Return list of issue dicts for appointments in self (no DB writes)."""
        findings = []
        for appt in self:
            invoices = appt._get_linked_invoices().filtered(lambda m: m.state != 'cancel')
            primaries = invoices.filtered(
                lambda m: m.move_type == 'out_invoice' and not m.is_additional_invoice
            )
            if len(primaries) > 1:
                findings.append({
                    'appointment_id': appt.id,
                    'issue_type': 'multi_primary_invoice',
                    'severity': 'critical',
                    'name': _('%s: multiple primary invoices') % appt.name,
                    'details': ', '.join(primaries.mapped('name')),
                    'classification': 'confirmed_duplicate_invoice',
                })
            if invoices.filtered(lambda m: m.state == 'draft') and appt.total_customer_credit:
                findings.append({
                    'appointment_id': appt.id,
                    'issue_type': 'draft_with_payment',
                    'severity': 'high',
                    'name': _('%s: draft invoice with payment credit') % appt.name,
                    'details': 'credit=%s' % appt.total_customer_credit,
                })
            if appt.payment_status == 'overpaid':
                findings.append({
                    'appointment_id': appt.id,
                    'issue_type': 'overpayment',
                    'severity': 'high',
                    'name': _('%s: overpaid') % appt.name,
                    'details': 'paid=%s invoiced=%s credit=%s' % (
                        appt.total_paid, appt.total_invoiced, appt.total_customer_credit),
                })
            if appt.state == 'done' and appt.payment_status in ('pending', 'not_invoiced') \
                    and appt.total_paid and not appt.is_complimentary:
                findings.append({
                    'appointment_id': appt.id,
                    'issue_type': 'status_mismatch',
                    'severity': 'medium',
                    'name': _('%s: status mismatch') % appt.name,
                    'details': 'payment_status=%s total_paid=%s' % (
                        appt.payment_status, appt.total_paid),
                })
            if appt.sale_order_id and appt.total_invoiced and abs(
                    (appt.sale_order_id.amount_total or 0.0) - appt.total_invoiced) > 0.05 \
                    and not appt.is_complimentary:
                so_total = appt.sale_order_id.amount_total or 0.0
                findings.append({
                    'appointment_id': appt.id,
                    'issue_type': 'so_invoice_mismatch',
                    'severity': 'medium',
                    'name': _('%s: SO/invoice mismatch') % appt.name,
                    'details': 'so=%s inv=%s classification=incomplete_so_sync' % (
                        so_total, appt.total_invoiced),
                    'classification': 'incomplete_so_sync',
                })
            if appt.invoice_id and appt.invoice_id not in invoices and invoices:
                findings.append({
                    'appointment_id': appt.id,
                    'issue_type': 'pointer_mismatch',
                    'severity': 'medium',
                    'name': _('%s: invoice pointer mismatch') % appt.name,
                    'details': 'pointer=%s linked=%s' % (
                        appt.invoice_id.name, ', '.join(invoices.mapped('name'))),
                })
            if appt.state == 'done' and not invoices and not appt.is_complimentary \
                    and (appt.service_total or appt.cost):
                findings.append({
                    'appointment_id': appt.id,
                    'issue_type': 'confirmed_uninvoiced',
                    'severity': 'medium',
                    'name': _('%s: done without invoice') % appt.name,
                    'details': 'service_total=%s' % (appt.service_total or appt.cost),
                })
        return findings

    def _scan_billing_integrity_issues(self):
        """Idempotent anomaly scan: upsert by (appointment, issue_type), auto-resolve stale opens."""
        Issue = self.env['pet.billing.integrity.issue'].sudo()
        appointments = self if self.ids else (
            self.search([('sale_order_id', '!=', False)])
            | self.search([('invoice_id', '!=', False)])
            | self.search([('state', '=', 'done')])
        )
        findings = appointments._collect_billing_integrity_findings()
        found_keys = set()
        created_or_updated = 0
        now = fields.Datetime.now()
        for finding in findings:
            key = (finding['appointment_id'], finding['issue_type'])
            found_keys.add(key)
            vals = {
                'name': finding['name'],
                'appointment_id': finding['appointment_id'],
                'issue_type': finding['issue_type'],
                'severity': finding['severity'],
                'details': finding.get('details'),
                'classification': finding.get('classification') or False,
                'detected_at': now,
            }
            existing = Issue.search([
                ('appointment_id', '=', finding['appointment_id']),
                ('issue_type', '=', finding['issue_type']),
            ], order='id desc', limit=1)
            if existing:
                write_vals = {
                    k: vals[k] for k in ('name', 'severity', 'details', 'classification', 'detected_at')
                }
                if existing.state == 'resolved':
                    write_vals['state'] = 'open'
                existing.write(write_vals)
            else:
                vals['state'] = 'open'
                Issue.create(vals)
            created_or_updated += 1

        open_issues = Issue.search([('state', '=', 'open')])
        resolved = 0
        for issue in open_issues:
            if (issue.appointment_id.id, issue.issue_type) not in found_keys:
                issue.write({'state': 'resolved'})
                resolved += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Billing Integrity Scan'),
                'message': _(
                    'Upserted %(n)s finding(s); auto-resolved %(r)s stale open issue(s).',
                    n=created_or_updated, r=resolved,
                ),
                'type': 'warning' if created_or_updated else 'success',
                'sticky': False,
            },
        }

    def _cron_scan_billing_integrity(self):
        self._scan_billing_integrity_issues()

    def _prepare_invoice_lines(self):
        """Prepare invoice lines based on appointment facilities and services (legacy refresh)."""
        lines = []
        account_id = self._get_default_account_id()

        if self.medical_visit_id and self.medical_visit_id.status == 'completed':
            visit = self.medical_visit_id
            visit_lines = visit.line_ids.filtered(lambda line: line.price_subtotal > 0)
            if visit_lines:
                for line in visit_lines:
                    line_vals = {
                        'name': line.name,
                        'quantity': line.quantity or 1.0,
                        'price_unit': line.price_unit,
                        'account_id': account_id,
                    }
                    if line.product_id:
                        line_vals['product_id'] = line.product_id.id
                    if line.discount:
                        line_vals['discount'] = line.discount
                    lines.append(line_vals)
                if visit.discount_amount:
                    lines.append({
                        'name': _('Visit discount'),
                        'quantity': 1,
                        'price_unit': -abs(visit.discount_amount),
                        'account_id': account_id,
                    })
            elif visit.cost:
                lines.append({
                    'name': f"Medical Visit - {visit.reason or 'Consultation'}",
                    'quantity': 1,
                    'price_unit': visit.cost,
                    'account_id': account_id,
                })

        if self.vaccination_id and self.vaccination_id.cost and self.vaccination_id.state == 'administered':
            lines.append({
                'name': f"Vaccination - {self.vaccination_id.vaccine_id.name if self.vaccination_id.vaccine_id else 'Vaccine'}",
                'quantity': 1,
                'price_unit': self.vaccination_id.cost,
                'account_id': self._get_default_account_id(),
            })

        if self.vaccine_id and self.vaccine_id.cost:
            lines.append({
                'name': f"Vaccine - {self.vaccine_id.name}",
                'quantity': 1,
                'price_unit': self.vaccine_id.cost,
                'account_id': self._get_default_account_id(),
            })

        if self.grooming_session_id and self.grooming_session_id.total_cost and self.grooming_session_id.state == 'completed':
            lines.append({
                'name': f"Grooming - {self.grooming_session_id.service_id.name if self.grooming_session_id.service_id else 'Grooming Service'}",
                'quantity': 1,
                'price_unit': self.grooming_session_id.total_cost,
                'account_id': self._get_default_account_id(),
            })
        elif self.service_id and self.service_id.base_price and self.grooming_session_id and self.grooming_session_id.state == 'completed':
            lines.append({
                'name': f"Grooming Service - {self.service_id.name}",
                'quantity': 1,
                'price_unit': self.service_id.base_price,
                'account_id': self._get_default_account_id(),
            })

        if self.training_session_id and self.training_session_id.session_cost and self.training_session_id.state == 'completed':
            lines.append({
                'name': f"Training - {self.training_session_id.program_id.name if self.training_session_id.program_id else 'Training Program'}",
                'quantity': 1,
                'price_unit': self.training_session_id.session_cost,
                'account_id': self._get_default_account_id(),
            })
        elif self.program_id and self.program_id.base_price and self.training_session_id and self.training_session_id.state == 'completed':
            lines.append({
                'name': f"Training Program - {self.program_id.name}",
                'quantity': 1,
                'price_unit': self.program_id.base_price,
                'account_id': self._get_default_account_id(),
            })

        if self.boarding_stay_id and self.boarding_stay_id.total_cost and self.boarding_stay_id.state == 'checked_out':
            lines.append({
                'name': f"Boarding - {self.boarding_stay_id.kennel_id.name if self.boarding_stay_id.kennel_id else 'Boarding Stay'}",
                'quantity': 1,
                'price_unit': self.boarding_stay_id.total_cost,
                'account_id': self._get_default_account_id(),
            })

        if not lines and self.cost > 0:
            lines.append({
                'name': f"Appointment - {self.title or 'Pet Care Services'}",
                'quantity': 1,
                'price_unit': self.cost,
                'account_id': self._get_default_account_id(),
            })

        return lines

    def _get_default_account_id(self):
        """Get default account for invoice lines"""
        # account.account is multi-company in Odoo 19 (company_ids m2m)
        account = self.env['account.account'].search([
            ('account_type', '=', 'income_other'),
            ('company_ids', 'in', self.company_id.id)
        ], limit=1)

        if not account:
            account = self.env['account.account'].search([
                ('account_type', 'in', ('income', 'income_other')),
                ('company_ids', 'in', self.company_id.id)
            ], limit=1)
        if not account:
            account = self.env['account.account'].search([
                ('company_ids', 'in', self.company_id.id)
            ], limit=1)

        return account.id if account else False

    def action_view_invoice(self):
        """View the primary or all invoices."""
        self.ensure_one()
        self._recompute_primary_invoice()
        invoices = self._get_linked_invoices().filtered(lambda m: m.state != 'cancel')
        if len(invoices) > 1:
            return self.action_view_invoices()
        if self.invoice_id:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Invoice',
                'res_model': 'account.move',
                'view_mode': 'form',
                'res_id': self.invoice_id.id,
                'target': 'current',
            }
        if self.sale_order_id:
            return self.action_view_sale_order()
        return self.action_create_or_open_sale_order()

    def action_cancel_invoice(self):
        """Cancel the primary invoice (draft/posted unpaid preferred)."""
        for rec in self:
            if rec.invoice_id and rec.invoice_state in ['draft', 'posted']:
                rec.invoice_id.button_cancel()
                rec._recompute_primary_invoice()

    def action_refresh_invoice(self):
        """Refresh/update the draft primary invoice with current appointment data."""
        for rec in self:
            if not rec.invoice_id:
                if rec.sale_order_id:
                    return rec.action_view_sale_order()
                return rec.action_create_or_open_sale_order()

            if rec.invoice_state not in ['draft']:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Warning',
                        'message': 'Invoice can only be refreshed when in draft state.',
                        'type': 'warning',
                        'sticky': False,
                    }
                }

            rec._refresh_invoice_sync()

            return {
                'type': 'ir.actions.act_window',
                'name': 'Invoice Refreshed',
                'res_model': 'account.move',
                'view_mode': 'form',
                'res_id': rec.invoice_id.id,
                'target': 'current',
            }
    
    def action_assign_current_user_as_resource(self):
        """Assign current user's employee record as veterinarian on this appointment."""
        self.ensure_one()
        employee = self.env.user.employee_id
        if not employee:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': _('Current user is not linked to an employee record.'),
                    'type': 'error',
                    'sticky': True,
                }
            }
        self.vet_employee_id = employee.id
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': _('Assigned %s as veterinarian to this appointment') % employee.name,
                'type': 'success',
                'sticky': True,
            }
        }

    # Integration Methods
    def _is_calendar_module_installed(self):
        """Check if calendar module is installed and active"""
        try:
            return self.env['ir.module.module'].search([
                ('name', '=', 'calendar'),
                ('state', '=', 'installed')
            ]).exists() and 'calendar.event' in self.env
        except:
            return False

    def _is_stock_module_installed(self):
        """Check if stock module is installed and active"""
        try:
            return self.env['ir.module.module'].search([
                ('name', '=', 'stock'),
                ('state', '=', 'installed')
            ]).exists() and 'stock.move' in self.env
        except:
            return False

    def _calendar_attendee_partner_ids(self):
        """Partners to invite on the calendar event (never include False)."""
        self.ensure_one()
        partner = self.intake_owner_id or self.owner_id
        return [partner.id] if partner else []

    def _calendar_event_description(self):
        self.ensure_one()
        owner = self.intake_owner_id or self.owner_id
        pet_name = self.pet_id.sudo().name if self.pet_id else _('(no pet yet)')
        owner_name = owner.sudo().name if owner else _('(no owner)')
        return _(
            "Pet: %(pet)s\nOwner: %(owner)s\nNotes: %(notes)s",
            pet=pet_name,
            owner=owner_name,
            notes=self.notes or '',
        )

    def action_sync_to_calendar(self):
        """Sync appointment to calendar if calendar module is installed and enabled"""
        self.ensure_one()
        if not self._is_calendar_module_installed():
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Warning',
                    'message': 'Calendar module is not installed. Please install the Calendar module to use this feature.',
                    'type': 'warning',
                    'sticky': True,
                }
            }
        
        if not self.sync_to_calendar:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Info',
                    'message': 'Calendar sync is disabled for this appointment.',
                    'type': 'info',
                    'sticky': False,
                }
            }
        
        # Check if calendar integration is enabled in settings
        icp = self.env['ir.config_parameter'].sudo()
        enable_calendar = icp.get_param('pet_management.enable_calendar_integration') in (True, 'True', '1', 1)
        
        if not enable_calendar:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Info',
                    'message': 'Calendar integration is disabled in Pet Management settings.',
                    'type': 'info',
                    'sticky': False,
                }
            }
        
        # Create or update calendar event.
        # Never pass partner_id=False — calendar.attendee requires Attendee (partner_id).
        # Prefer intake_owner_id so owner-first drafts (no pet yet) still sync safely.
        partner_ids = self._calendar_attendee_partner_ids()
        event_vals = {
            'name': f"Pet Appointment: {self.title}",
            'start': self.start_datetime,
            'stop': self.end_datetime,
            'description': self._calendar_event_description(),
            'user_id': self.vet_employee_id.user_id.id if self.vet_employee_id and self.vet_employee_id.user_id else self.env.user.id,
        }
        if partner_ids:
            event_vals['partner_ids'] = [(6, 0, partner_ids)]

        if not self.calendar_event_id:
            event = self.env['calendar.event'].sudo().create(event_vals)
            self.calendar_event_id = event.id
        else:
            # Do not wipe attendees with [False] when owner is missing.
            write_vals = {
                'name': event_vals['name'],
                'start': event_vals['start'],
                'stop': event_vals['stop'],
                'description': event_vals['description'],
            }
            if partner_ids:
                write_vals['partner_ids'] = [(6, 0, partner_ids)]
            self.calendar_event_id.sudo().write(write_vals)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': 'Appointment synced to calendar successfully.',
                'type': 'success',
                'sticky': True,
            }
        }

    def action_view_calendar_event(self):
        """Open the linked calendar event"""
        if not self.calendar_event_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Warning',
                    'message': 'No calendar event linked to this appointment or calendar module not installed.',
                    'type': 'warning',
                    'sticky': True,
                }
            }

        return {
            'type': 'ir.actions.act_window',
            'name': 'Calendar Event',
            'res_model': 'calendar.event',
            'res_id': self.calendar_event_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_manage_inventory(self):
        """Open inventory management for this appointment if stock module is installed"""
        if not self._is_stock_module_installed():
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Warning',
                    'message': 'Stock module is not installed. Please install the Stock module to use this feature.',
                    'type': 'warning',
                    'sticky': True,
                }
            }
        
        # Check if inventory integration is enabled in settings
        icp = self.env['ir.config_parameter'].sudo()
        enable_inventory = icp.get_param('pet_management.enable_inventory_integration') in (True, 'True', '1', 1)
        
        if not enable_inventory:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Info',
                    'message': 'Inventory integration is disabled in Pet Management settings.',
                    'type': 'info',
                    'sticky': False,
                }
            }
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Appointment Inventory Items',
            'res_model': 'pet.appointment.inventory',
            'view_mode': 'list,form',
            'domain': [('appointment_id', '=', self.id)],
            'context': {'default_appointment_id': self.id},
            'target': 'current',
        }
