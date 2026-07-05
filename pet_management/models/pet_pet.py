from datetime import date
from odoo import models, fields, api, _ # type: ignore
from odoo.exceptions import ValidationError, AccessError # type: ignore

class Pet(models.Model):
    _name = 'pet.pet'
    _description = 'Pet'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'

    name = fields.Char(string="Name", required=True, tracking=True, help="The pet's name")
    code = fields.Char(string="Code", readonly=True, copy=False, index=True, default=lambda s: _('New'), help="Unique identifier for the pet")

    species_id = fields.Many2one('pet.species', string="Species", required=True, tracking=True, help="The species of the pet (e.g., Dog, Cat, Bird)")
    breed_id = fields.Many2one('pet.breed', string="Breed", domain=lambda self: self._get_breed_domain(), help="The specific breed of the pet")
    
    def name_get(self):
        """Override name_get to handle breed access with sudo()"""
        result = []
        for record in self:
            name = record.name
            if record.breed_id:
                try:
                    breed_name = record.breed_id.sudo().name
                    name = f"{name} ({breed_name})"
                except:
                    pass
            result.append((record.id, name))
        return result
    
    # Custom breed field for Own Data users
    breed_name = fields.Char(string="Breed Name", compute='_compute_breed_name', store=False, help="Breed name for display")
    gender = fields.Selection([('male','Male'),('female','Female'),('unknown','Unknown')], string="Gender", tracking=True, help="The pet's gender")
    color_markings = fields.Char(string="Color & Markings", help="Description of the pet's color and markings")
    microchip_no = fields.Char(string="Microchip No.", index=True, default=lambda self: _('New'), help="Microchip identification number")
    tag_id = fields.Char(string="Tag ID", help="Tag or collar identification number")

    dob = fields.Date(string="Date of Birth", help="Date of birth of the pet")
    dod = fields.Date(string="Date of Death", help="Date of death of the pet (if applicable)")
    age_years = fields.Float(string="Age (Years)", compute='_compute_age', store=True, help="Pet's age in years (computed from date of birth)")
    age_display = fields.Char(string="Age Display", compute='_compute_age', store=True, help="Pet's age in a readable format")
    neutered = fields.Boolean(string="Neutered", help="Whether the pet has been neutered or spayed")
    status = fields.Selection([
        ('active','Active'), ('adopted','Adopted'), ('deceased','Deceased'), ('lost','Lost'), ('inactive','Inactive')
    ], string="Status", default='active', index=True, help="Current status of the pet")
    color = fields.Integer(string="Color Index", help="Color index for kanban view display")  # For Odoo kanban color reference

    owner_id = fields.Many2one('res.partner', string="Owner", required=True, ondelete='restrict', 
                               default=lambda self: self.env.user.partner_id.id if self.env.user.has_group('pet_management.group_pet_core_user_own') and not self.env.user.has_group('pet_management.group_pet_core_user_all') and not self.env.user.has_group('pet_management.group_pet_core_admin') else False,
                               domain=lambda self: [('id', '=', self.env.user.partner_id.id)] if self.env.user.has_group('pet_management.group_pet_core_user_own') and not self.env.user.has_group('pet_management.group_pet_core_user_all') and not self.env.user.has_group('pet_management.group_pet_core_admin') else [],
                               help="Primary owner of the pet")
    co_owner_ids = fields.Many2many('res.partner', string='Co-Owners', 
                                    domain=lambda self: [('id', '=', False)] if self.env.user.has_group('pet_management.group_pet_core_user_own') and not self.env.user.has_group('pet_management.group_pet_core_user_all') and not self.env.user.has_group('pet_management.group_pet_core_admin') else [],
                                    help="Additional owners or family members")
    
    emergency_contact_id = fields.Many2one('res.partner', string="Emergency Contact", 
                                           domain=lambda self: [('id', '=', False)] if self.env.user.has_group('pet_management.group_pet_core_user_own') and not self.env.user.has_group('pet_management.group_pet_core_user_all') and not self.env.user.has_group('pet_management.group_pet_core_admin') else [],
                                           help="Emergency contact person for the pet")
    preferred_vet_id = fields.Many2one('res.partner', string="Preferred Vet", help="Preferred veterinarian for the pet")

    allergies = fields.Text(string="Allergies", help="List of known allergies and reactions")
    chronic_conditions = fields.Text(string="Chronic Conditions", help="Chronic health conditions or ongoing medical issues")
    behavior_notes = fields.Text(string="Behavior Notes", help="Behavioral observations and notes")
    dietary_restrictions = fields.Text(string="Dietary Restrictions", help="Special dietary requirements or restrictions")

    image_1920 = fields.Image(string="Photo", help="Pet's photograph")

    weight_history_ids = fields.One2many('pet.weight.history', 'pet_id', string="Weight History")
    vaccination_ids = fields.One2many('pet.vaccination', 'pet_id', string="Vaccinations")
    medical_visit_ids = fields.One2many('pet.medical.visit', 'pet_id', string="Medical Visits")
    boarding_stay_ids = fields.One2many('pet.boarding.stay', 'pet_id', string="Boarding Stays")
    grooming_session_ids = fields.One2many('pet.grooming.session', 'pet_id', string="Grooming Sessions")
    training_session_ids = fields.One2many('pet.training.session', 'pet_id', string="Training Sessions")
    diet_plan_ids = fields.One2many('pet.diet.plan', 'pet_id', string="Diet Plans")
    appointment_ids = fields.One2many('pet.appointment', 'pet_id', string="Appointments")

    company_id = fields.Many2one('res.company', string="Company", required=True, default=lambda s: s.env.company)

    _sql_constraints = [
        ('uniq_microchip_company', 'unique(microchip_no, company_id)', 'Microchip must be unique per company.'),
        ('uniq_tag_company', 'unique(tag_id, company_id)', 'Tag ID must be unique per company.'),
    ]

    @api.constrains('owner_id', 'co_owner_ids', 'emergency_contact_id')
    def _check_owner_permissions(self):
        """Ensure Own Data users cannot set invalid owners, co-owners, or emergency contacts"""
        for record in self:
            # Check if user is "Own Data" only (not All Data or Admin)
            if (self.env.user.has_group('pet_management.group_pet_core_user_own') and 
                not self.env.user.has_group('pet_management.group_pet_core_user_all') and 
                not self.env.user.has_group('pet_management.group_pet_core_admin')):
                
                # Owner must be current user
                if record.owner_id and record.owner_id.id != self.env.user.partner_id.id:
                    raise ValidationError("You can only set yourself as the pet owner.")
                
                # No co-owners allowed
                if record.co_owner_ids:
                    raise ValidationError("You cannot set co-owners. Only administrators can manage co-owners.")
                
                # No emergency contacts allowed
                if record.emergency_contact_id:
                    raise ValidationError("You cannot set emergency contacts. Only administrators can manage emergency contacts.")

    species_color = fields.Integer(string="Species Color", compute="_compute_related_colors", store=False)
    breed_color = fields.Integer(string="Breed Color", compute="_compute_related_colors", store=False)

    vaccination_count = fields.Integer(string="Vaccination Count", compute="_compute_counts", store=True)
    medical_visit_count = fields.Integer(string="Medical Visit Count", compute="_compute_counts", store=True)
    boarding_count = fields.Integer(string="Boarding", compute="_compute_counts", store=True)
    appointment_count = fields.Integer(string="Appointment Count", compute="_compute_counts", store=True)
    grooming_count = fields.Integer(string="Grooming", compute="_compute_counts", store=True)
    training_count = fields.Integer(string="Training", compute="_compute_counts", store=True)

    latest_weight_kg = fields.Float(string="Latest Weight (kg)", compute="_compute_latest_weight", store=False)
    has_vaccination_today = fields.Boolean(
        string="Has Vaccination Today",
        compute="_compute_has_vaccination_today",
        search="_search_has_vaccination_today",
        store=False,
    )
    has_training_today = fields.Boolean(
        string="Has Training Today",
        compute="_compute_has_training_today",
        search="_search_has_training_today",
        store=False,
    )
    has_appointment_today = fields.Boolean(
        string="Has Appointment Today",
        compute="_compute_has_appointment_today",
        search="_search_has_appointment_today",
        store=False,
    )
    has_grooming_today = fields.Boolean(
        string="Has Grooming Today",
        compute="_compute_has_grooming_today",
        search="_search_has_grooming_today",
        store=False,
    )
    has_boarding_today = fields.Boolean(
        string="Has Boarding Today",
        compute="_compute_has_boarding_today",
        search="_search_has_boarding_today",
        store=False,
    )
    has_medical_today = fields.Boolean(
        string="Has Medical Visit Today",
        compute="_compute_has_medical_today",
        search="_search_has_medical_today",
        store=False,
    )

    @api.depends('vaccination_ids', 'medical_visit_ids', 'boarding_stay_ids', 'appointment_ids', 'grooming_session_ids', 'training_session_ids')
    def _compute_counts(self):
        for rec in self:
            rec.vaccination_count = len(rec.vaccination_ids)
            rec.medical_visit_count = len(rec.medical_visit_ids)
            rec.boarding_count = len(rec.boarding_stay_ids)
            rec.appointment_count = len(rec.appointment_ids)
            rec.grooming_count = len(rec.grooming_session_ids)
            rec.training_count = len(rec.training_session_ids)

    def _get_breed_domain(self):
        """Get domain for breed field with sudo() access for Own Data users"""
        if self.species_id:
            # Use sudo() to allow access to breed data for Own Data users
            return [('species_id', '=', self.species_id.id)]
        return []

    @api.model
    def _search_breed_id(self, args, operator, value):
        """Custom search method for breed_id field with sudo() access"""
        # Use sudo() to search breed records for Own Data users
        breed_model = self.env['pet.breed'].sudo()
        if operator == '=' and value:
            breeds = breed_model.search([('id', '=', value)])
            return [('id', 'in', breeds.ids)]
        elif operator == 'in' and value:
            breeds = breed_model.search([('id', 'in', value)])
            return [('id', 'in', breeds.ids)]
        elif operator == 'ilike' and value:
            breeds = breed_model.search([('name', 'ilike', value)])
            return [('id', 'in', breeds.ids)]
        return []

    @api.onchange('species_id')
    def _onchange_species_id(self):
        """Clear breed when species changes"""
        if self.species_id:
            # Clear breed when species changes
            self.breed_id = False

    @api.depends('breed_id')
    def _compute_breed_name(self):
        """Compute breed name with sudo() access for Own Data users"""
        for rec in self:
            if rec.breed_id:
                rec.breed_name = rec.breed_id.sudo().name
            else:
                rec.breed_name = False

    @api.depends('species_id.color', 'breed_id.color')
    def _compute_related_colors(self):
        for rec in self:
            # Use sudo() to allow access to species and breed data for display purposes
            rec.species_color = rec.species_id.sudo().color if rec.species_id else 0
            rec.breed_color = rec.breed_id.sudo().color if rec.breed_id else 0

    @api.constrains('dob', 'dod')
    def _check_dates(self):
        today = date.today()
        for rec in self:
            if rec.dob and rec.dob > today:
                raise ValidationError(_('Date of Birth cannot be in the future.'))
            if rec.dob and rec.dod and rec.dod < rec.dob:
                raise ValidationError(_('Date of Death cannot be before Date of Birth.'))

    @api.depends('dob')
    def _compute_age(self):
        today = date.today()
        for rec in self:
            if rec.dob:
                days = (today - rec.dob).days
                years = days / 365.25
                rec.age_years = years
                y = int(years)
                m = int(round((years - y) * 12))
                rec.age_display = _('%s y %s m') % (y, m)
            else:
                rec.age_years = 0.0
                rec.age_display = _('N/A')


    def _compute_has_vaccination_today(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.has_vaccination_today = any(v.date_administered == today for v in rec.vaccination_ids)

    def _compute_has_training_today(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.has_training_today = any(
                t.date and fields.Date.to_date(t.date) == today for t in rec.training_session_ids
            )

    def _compute_has_appointment_today(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.has_appointment_today = any(
                a.start_datetime and fields.Date.to_date(a.start_datetime) == today for a in rec.appointment_ids
            )

    def _compute_has_grooming_today(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.has_grooming_today = any(
                g.date and fields.Date.to_date(g.date) == today for g in rec.grooming_session_ids
            )

    def _compute_has_boarding_today(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.has_boarding_today = any(
                b.check_in and fields.Date.to_date(b.check_in) == today for b in rec.boarding_stay_ids
            )

    def _compute_has_medical_today(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.has_medical_today = any(
                m.date and fields.Date.to_date(m.date) == today for m in rec.medical_visit_ids
            )

    @api.model
    def _search_has_vaccination_today(self, operator, value):
        today = fields.Date.context_today(self)
        pet_ids = self.env['pet.vaccination'].search([('date_administered', '=', today)]).mapped('pet_id').ids
        if value:
            return [('id', 'in', pet_ids)]
        else:
            return [('id', 'not in', pet_ids)]

    @api.model
    def _search_has_training_today(self, operator, value):
        today = fields.Date.context_today(self)
        pet_ids = self.env['pet.training.session'].search([]).filtered(lambda s: s.date and fields.Date.to_date(s.date) == today).mapped('pet_id').ids
        if value:
            return [('id', 'in', pet_ids)]
        else:
            return [('id', 'not in', pet_ids)]

    @api.model
    def _search_has_appointment_today(self, operator, value):
        today = fields.Date.context_today(self)
        pet_ids = self.env['pet.appointment'].search([]).filtered(lambda a: a.start_datetime and fields.Date.to_date(a.start_datetime) == today).mapped('pet_id').ids
        if value:
            return [('id', 'in', pet_ids)]
        else:
            return [('id', 'not in', pet_ids)]

    @api.model
    def _search_has_grooming_today(self, operator, value):
        today = fields.Date.context_today(self)
        pet_ids = self.env['pet.grooming.session'].search([]).filtered(lambda g: g.date and fields.Date.to_date(g.date) == today).mapped('pet_id').ids
        if value:
            return [('id', 'in', pet_ids)]
        else:
            return [('id', 'not in', pet_ids)]

    @api.model
    def _search_has_boarding_today(self, operator, value):
        today = fields.Date.context_today(self)
        pet_ids = self.env['pet.boarding.stay'].search([]).filtered(lambda b: b.check_in and fields.Date.to_date(b.check_in) == today).mapped('pet_id').ids
        if value:
            return [('id', 'in', pet_ids)]
        else:
            return [('id', 'not in', pet_ids)]

    @api.model
    def _search_has_medical_today(self, operator, value):
        today = fields.Date.context_today(self)
        pet_ids = self.env['pet.medical.visit'].search([]).filtered(lambda m: m.date and fields.Date.to_date(m.date) == today).mapped('pet_id').ids
        if value:
            return [('id', 'in', pet_ids)]
        else:
            return [('id', 'not in', pet_ids)]

    @api.model_create_multi
    def create(self, vals_list):
        # Read settings once for batch create
        icp = self.env['ir.config_parameter'].sudo()
        auto_gen = icp.get_param('pet_management.auto_generate_microchip') in (True, 'True', '1', 1)
        mc_prefix = icp.get_param('pet_management.microchip_prefix') or 'MC'
        try:
            mc_padding = int(icp.get_param('pet_management.microchip_padding') or 8)
        except Exception:
            mc_padding = 8

        # Ensure sequence prefix/padding reflect settings before generation
        if auto_gen:
            seq = self.env['ir.sequence'].sudo().search([('code', '=', 'pet.microchip')], limit=1)
            if seq:
                updates = {}
                if seq.prefix != mc_prefix:
                    updates['prefix'] = mc_prefix
                if seq.padding != mc_padding:
                    updates['padding'] = mc_padding
                if updates:
                    seq.write(updates)

        for vals in vals_list:
            if vals.get('code', _('New')) == _('New'):
                vals['code'] = self.env['ir.sequence'].next_by_code('pet.pet') or _('New')

            # Auto-generate microchip number based on settings
            if vals.get('microchip_no', _('New')) == _('New'):
                if auto_gen:
                    vals['microchip_no'] = self.env['ir.sequence'].next_by_code('pet.microchip') or _('New')
                else:
                    # Leave empty to avoid unique constraint collision and allow manual fill if view permits
                    vals['microchip_no'] = False

            # Auto-set owner for "Own Data" users
            if (self.env.user.has_group('pet_management.group_pet_core_user_own') and 
                not self.env.user.has_group('pet_management.group_pet_core_user_all') and 
                not self.env.user.has_group('pet_management.group_pet_core_admin')):
                # Force set owner to current user's partner
                vals['owner_id'] = self.env.user.partner_id.id
                # Clear co-owners to prevent setting different users
                vals['co_owner_ids'] = [(5, 0, 0)]  # Remove all co-owners
                # Clear emergency contact to prevent setting different users
                vals['emergency_contact_id'] = False
                
        return super().create(vals_list)

    @api.model
    def fields_view_get(self, view_id=None, view_type='form', toolbar=False, submenu=False):
        """Override to set context for owner field restrictions"""
        result = super().fields_view_get(view_id, view_type, toolbar, submenu)
        
        # Check if user is "Own Data" only (not All Data or Admin)
        if (self.env.user.has_group('pet_management.group_pet_core_user_own') and 
            not self.env.user.has_group('pet_management.group_pet_core_user_all') and 
            not self.env.user.has_group('pet_management.group_pet_core_admin')):
            # Set context to make owner fields readonly
            if 'context' not in result:
                result['context'] = {}
            result['context']['can_edit_owner'] = False
            
        return result

    def write(self, vals):
        """Override to prevent "Own Data" users from changing owner"""
        # Check if user is "Own Data" only (not All Data or Admin)
        if (self.env.user.has_group('pet_management.group_pet_core_user_own') and 
            not self.env.user.has_group('pet_management.group_pet_core_user_all') and 
            not self.env.user.has_group('pet_management.group_pet_core_admin')):
            
            # Prevent changing owner
            if 'owner_id' in vals and vals['owner_id'] != self.env.user.partner_id.id:
                raise AccessError("You cannot change the pet owner. You can only manage pets you own.")
            
            # Prevent setting co-owners
            if 'co_owner_ids' in vals:
                # Only allow clearing co-owners, not adding them
                if vals['co_owner_ids'] and vals['co_owner_ids'] != [(5, 0, 0)]:
                    raise AccessError("You cannot set co-owners. Only administrators can manage co-owners.")
            
            # Prevent setting emergency contacts
            if 'emergency_contact_id' in vals and vals['emergency_contact_id']:
                raise AccessError("You cannot set emergency contacts. Only administrators can manage emergency contacts.")
        
        return super().write(vals)

    @api.model
    def _check_partner_creation_access(self):
        """Check if user can create new partners for owner/co-owner fields"""
        # Check if user is "Own Data" only (not All Data or Admin)
        if (self.env.user.has_group('pet_management.group_pet_core_user_own') and 
            not self.env.user.has_group('pet_management.group_pet_core_user_all') and 
            not self.env.user.has_group('pet_management.group_pet_core_admin')):
            return False
        return True

    def action_open_vaccinations(self):
        # Check if user has health permissions
        if not self.env.user.has_group('pet_management.group_pet_health_user_own') and \
           not self.env.user.has_group('pet_management.group_pet_health_user_all') and \
           not self.env.user.has_group('pet_management.group_pet_health_admin'):
            raise AccessError("You don't have permission to access vaccinations. Please contact your administrator to request Health permissions.")
        
        return {
            "type": "ir.actions.act_window",
            "name": "Vaccinations",
            "res_model": "pet.vaccination",
            "view_mode": "list,form",
            "domain": [("pet_id", "=", self.id)],
            "context": {"default_pet_id": self.id},
        }

    def action_open_medical_visits(self):
        # Check if user has health permissions
        if not self.env.user.has_group('pet_management.group_pet_health_user_own') and \
           not self.env.user.has_group('pet_management.group_pet_health_user_all') and \
           not self.env.user.has_group('pet_management.group_pet_health_admin'):
            raise AccessError("You don't have permission to access medical visits. Please contact your administrator to request Health permissions.")
        
        return {
            "type": "ir.actions.act_window",
            "name": "Medical Visits",
            "res_model": "pet.medical.visit",
            "view_mode": "list,form",
            "domain": [("pet_id", "=", self.id)],
            "context": {"default_pet_id": self.id},
        }

    def action_open_boarding(self):
        # Check if user has boarding permissions
        if not self.env.user.has_group('pet_management.group_pet_boarding_user_own') and \
           not self.env.user.has_group('pet_management.group_pet_boarding_user_all') and \
           not self.env.user.has_group('pet_management.group_pet_boarding_admin'):
            raise AccessError("You don't have permission to access boarding. Please contact your administrator to request Boarding permissions.")
        
        return {
            "type": "ir.actions.act_window",
            "name": "Boarding Stays",
            "res_model": "pet.boarding.stay",
            "view_mode": "list,form",
            "domain": [("pet_id", "=", self.id)],
            "context": {"default_pet_id": self.id},
        }

    def action_open_appointments(self):
        # Check if user has appointment permissions
        if not self.env.user.has_group('pet_management.group_pet_appointments_user_own') and \
           not self.env.user.has_group('pet_management.group_pet_appointments_user_all') and \
           not self.env.user.has_group('pet_management.group_pet_appointments_admin'):
            raise AccessError("You don't have permission to access appointments. Please contact your administrator to request Appointments permissions.")
        
        return {
            "type": "ir.actions.act_window",
            "name": "Appointments",
            "res_model": "pet.appointment",
            "view_mode": "list,form",
            "domain": [("pet_id", "=", self.id)],
            "context": {"default_pet_id": self.id},
        }

    def action_open_grooming(self):
        # Check if user has grooming permissions
        if not self.env.user.has_group('pet_management.group_pet_grooming_user_own') and \
           not self.env.user.has_group('pet_management.group_pet_grooming_user_all') and \
           not self.env.user.has_group('pet_management.group_pet_grooming_admin'):
            raise AccessError("You don't have permission to access grooming. Please contact your administrator to request Grooming permissions.")
        
        return {
            "type": "ir.actions.act_window",
            "name": "Grooming Sessions",
            "res_model": "pet.grooming.session",
            "view_mode": "list,form",
            "domain": [("pet_id", "=", self.id)],
            "context": {"default_pet_id": self.id},
        }

    def action_open_training(self):
        # Check if user has training permissions
        if not self.env.user.has_group('pet_management.group_pet_training_user_own') and \
           not self.env.user.has_group('pet_management.group_pet_training_user_all') and \
           not self.env.user.has_group('pet_management.group_pet_training_admin'):
            raise AccessError("You don't have permission to access training. Please contact your administrator to request Training permissions.")
        
        return {
            "type": "ir.actions.act_window",
            "name": "Training Sessions",
            "res_model": "pet.training.session",
            "view_mode": "list,form",
            "domain": [("pet_id", "=", self.id)],
            "context": {"default_pet_id": self.id},
        }

    def action_open_weight_history(self):
        # Check if user has health permissions
        if not self.env.user.has_group('pet_management.group_pet_health_user_own') and \
           not self.env.user.has_group('pet_management.group_pet_health_user_all') and \
           not self.env.user.has_group('pet_management.group_pet_health_admin'):
            
            # Debug: Show current user groups
            user_groups = self.env.user.groups_id.mapped('name')
            debug_message = f"Current user groups: {', '.join(user_groups)}"
            
            raise AccessError(f"You don't have permission to access weight history. Please contact your administrator to request Health permissions.\n\nDebug info: {debug_message}")
        
        return {
            "type": "ir.actions.act_window",
            "name": "Weight History",
            "res_model": "pet.weight.history",
            "view_mode": "kanban,list,form,graph",
            "domain": [("pet_id", "=", self.id)],
            "context": {"default_pet_id": self.id},
        }

    @api.depends('weight_history_ids')
    def _compute_latest_weight(self):
        """Compute the latest weight for the pet"""
        for pet in self:
            latest_weight = self.env['pet.weight.history'].sudo().search([
                ('pet_id', '=', pet.id)
            ], limit=1, order='date desc')
            pet.latest_weight_kg = latest_weight.weight_kg if latest_weight else 0.0