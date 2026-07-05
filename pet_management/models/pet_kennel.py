from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class PetKennelEquipment(models.Model):
    _name = 'pet.kennel.equipment'
    _description = 'Kennel Equipment & Amenities'
    _order = 'name'

    name = fields.Char(string="Name", required=True, help="Equipment or amenity name")
    description = fields.Text(string="Description", help="Description of the equipment or amenity")
    category = fields.Selection([
        ('comfort', 'Comfort'), ('safety', 'Safety'), ('monitoring', 'Monitoring'),
        ('feeding', 'Feeding'), ('exercise', 'Exercise'), ('medical', 'Medical')
    ], string="Category", help="Equipment category")
    active = fields.Boolean(string="Active", default=True, help="Is this equipment available?")

class PetKennel(models.Model):
    _name = 'pet.kennel'
    _description = 'Kennel / Cage'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string="Name", required=True, tracking=True, help="Kennel name or identifier")
    code = fields.Char(string="Code", required=True, tracking=True, help="Unique kennel code")
    location = fields.Char(string="Location", tracking=True, help="Physical location of the kennel")
    size = fields.Selection([
        ('small', 'Small (1-15 lbs)'), ('medium', 'Medium (16-50 lbs)'), 
        ('large', 'Large (51-100 lbs)'), ('xl', 'Extra Large (100+ lbs)')
    ], string="Size", required=True, tracking=True, help="Kennel size category")
    
    # Enhanced Fields
    capacity = fields.Integer(string="Capacity", default=1, help="Maximum number of pets this kennel can accommodate")
    dimensions = fields.Char(string="Dimensions", help="Physical dimensions (e.g., '4ft x 3ft x 3ft')")
    daily_rate = fields.Float(string="Daily Rate", help="Daily boarding rate for this kennel")
    
    # Equipment & Amenities
    equipment_ids = fields.Many2many('pet.kennel.equipment', string='Equipment & Amenities', help="Available equipment and amenities")
    has_outdoor_access = fields.Boolean(string="Has Outdoor Access", help="Does this kennel have outdoor access?")
    has_heating = fields.Boolean(string="Has Heating", help="Does this kennel have heating?")
    has_cooling = fields.Boolean(string="Has Cooling", help="Does this kennel have cooling/AC?")
    has_webcam = fields.Boolean(string="Has Webcam", help="Does this kennel have webcam monitoring?")
    
    # Status & Maintenance
    status = fields.Selection([
        ('available', 'Available'), ('occupied', 'Occupied'), ('maintenance', 'Under Maintenance'),
        ('cleaning', 'Being Cleaned'), ('reserved', 'Reserved')
    ], string="Status", default='available', tracking=True, help="Current status of the kennel")
    
    last_cleaned = fields.Datetime(string="Last Cleaned", help="Last cleaning date and time")
    next_maintenance = fields.Date(string="Next Maintenance", help="Next scheduled maintenance date")
    maintenance_notes = fields.Text(string="Maintenance Notes", help="Maintenance notes and history")
    
    # Additional Information
    notes = fields.Text(string="Notes", help="Additional notes about this kennel")
    active = fields.Boolean(string="Active", default=True, tracking=True, help="Is this kennel active?")
    company_id = fields.Many2one('res.company', string="Company", required=True, default=lambda s: s.env.company, help="Company this kennel belongs to")

    # Computed Fields
    current_occupancy = fields.Integer(string="Current Occupancy", compute='_compute_occupancy', store=False, search='_search_current_occupancy', help="Current number of pets in this kennel")
    occupancy_rate = fields.Float(string="Occupancy Rate", compute='_compute_occupancy', store=False, help="Current occupancy rate percentage")
    is_available = fields.Boolean(string="Is Available", compute='_compute_availability', store=False, search='_search_is_available', help="Is this kennel currently available?")
    days_since_cleaning = fields.Integer(string="Days Since Cleaning", compute='_compute_days_since_cleaning', store=False, help="Days since last cleaning")
    maintenance_due = fields.Boolean(string="Maintenance Due", compute='_compute_maintenance_due', store=False, search='_search_maintenance_due', help="Is maintenance due?")
    status_color = fields.Integer(string="Status Color", compute='_compute_status_color', store=True, help="Color index for status display")

    @api.depends('status', 'capacity', 'active')
    def _compute_occupancy(self):
        for kennel in self:
            # Count current boarding stays for this kennel
            now = fields.Datetime.now()
            current_stays = self.env['pet.boarding.stay'].search([
                ('kennel_id', '=', kennel.id),
                ('state', '=', 'checked_in'),
                ('check_in', '<=', now),
                ('check_out', '>=', now)
            ])
            kennel.current_occupancy = len(current_stays)
            if kennel.capacity > 0:
                kennel.occupancy_rate = (kennel.current_occupancy / kennel.capacity) * 100
            else:
                kennel.occupancy_rate = 0.0

    @api.depends('status', 'current_occupancy', 'capacity', 'active')
    def _compute_availability(self):
        for kennel in self:
            kennel.is_available = (
                kennel.status == 'available' and 
                kennel.current_occupancy < kennel.capacity and
                kennel.active
            )

    @api.depends('last_cleaned')
    def _compute_days_since_cleaning(self):
        today = fields.Datetime.now()
        for kennel in self:
            if kennel.last_cleaned:
                delta = today - kennel.last_cleaned
                kennel.days_since_cleaning = delta.days
            else:
                kennel.days_since_cleaning = 999  # Never cleaned

    @api.depends('next_maintenance')
    def _compute_maintenance_due(self):
        today = fields.Date.today()
        for kennel in self:
            kennel.maintenance_due = kennel.next_maintenance and kennel.next_maintenance <= today

    @api.depends('status')
    def _compute_status_color(self):
        color_map = {
            'available': 4,      # green
            'occupied': 2,       # orange
            'maintenance': 1,    # red
            'cleaning': 3,       # yellow
            'reserved': 5,       # purple
        }
        for kennel in self:
            kennel.status_color = color_map.get(kennel.status, 4)

    @api.constrains('capacity')
    def _check_capacity(self):
        for kennel in self:
            if kennel.capacity < 1:
                raise ValidationError(_('Kennel capacity must be at least 1.'))

    @api.constrains('code')
    def _check_code_unique(self):
        for kennel in self:
            if kennel.code:
                existing = self.search([('code', '=', kennel.code), ('id', '!=', kennel.id)])
                if existing:
                    raise ValidationError(_('Kennel code must be unique.'))

    def action_mark_cleaned(self):
        """Mark kennel as cleaned"""
        for kennel in self:
            kennel.last_cleaned = fields.Datetime.now()
            if kennel.status == 'cleaning':
                kennel.status = 'available'

    def action_mark_maintenance(self):
        """Mark kennel for maintenance"""
        for kennel in self:
            kennel.status = 'maintenance'

    def action_mark_available(self):
        """Mark kennel as available"""
        for kennel in self:
            kennel.status = 'available'

    def action_refresh_occupancy(self):
        """Manually refresh occupancy data"""
        for kennel in self:
            kennel._compute_occupancy()
            kennel._compute_availability()
            kennel._compute_days_since_cleaning()
            kennel._compute_maintenance_due()

    @api.model
    def refresh_all_occupancy(self):
        """Refresh occupancy data for all kennels"""
        all_kennels = self.search([])
        for kennel in all_kennels:
            kennel._compute_occupancy()
            kennel._compute_availability()
            kennel._compute_days_since_cleaning()
            kennel._compute_maintenance_due()
        return True

    def action_view_boarding_stays(self):
        """Action to view boarding stays for this kennel"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Boarding Stays',
            'res_model': 'pet.boarding.stay',
            'view_mode': 'kanban,list,form',
            'domain': [('kennel_id', '=', self.id)],
            'target': 'current',
        }

    @api.model
    def _search_is_available(self, operator, value):
        """Search method for is_available computed field"""
        if operator == '=' and value is True:
            return [('status', '=', 'available')]
        elif operator == '=' and value is False:
            return [('status', '!=', 'available')]
        return []

    @api.model
    def _search_maintenance_due(self, operator, value):
        """Search method for maintenance_due computed field"""
        if operator == '=' and value is True:
            return [('next_maintenance', '<=', fields.Date.today())]
        elif operator == '=' and value is False:
            return [('next_maintenance', '>', fields.Date.today())]
        return []

    @api.model
    def _search_current_occupancy(self, operator, value):
        """Search method for current_occupancy computed field"""
        # This is complex to implement properly, so we'll use status as a proxy
        if operator in ('=', '>=') and value == 0:
            return [('status', '=', 'available')]
        elif operator in ('>', '>=') and value > 0:
            return [('status', '=', 'occupied')]
        return []
