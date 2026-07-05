# -*- coding: utf-8 -*-

from odoo import models, fields, api


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # General Settings
    auto_generate_microchip = fields.Boolean(
        string="Auto-generate Microchip Numbers",
        config_parameter='pet_management.auto_generate_microchip',
        default=True,
        help="Automatically generate microchip numbers for new pets"
    )
    
    microchip_prefix = fields.Char(
        string="Microchip Prefix",
        config_parameter='pet_management.microchip_prefix',
        default="MC",
        help="Prefix for auto-generated microchip numbers"
    )
    
    microchip_padding = fields.Integer(
        string="Microchip Number Padding",
        config_parameter='pet_management.microchip_padding',
        default=8,
        help="Number of digits for microchip numbers"
    )
    
    # Notification Settings
    enable_email_notifications = fields.Boolean(
        string="Enable Email Notifications",
        config_parameter='pet_management.enable_email_notifications',
        default=True,
        help="Send email notifications for pet events"
    )
    
    enable_sms_notifications = fields.Boolean(
        string="Enable SMS Notifications",
        config_parameter='pet_management.enable_sms_notifications',
        default=False,
        help="Send SMS notifications for pet events"
    )
    
    # Appointment Settings
    appointment_duration_default = fields.Float(
        string="Default Appointment Duration (hours)",
        config_parameter='pet_management.appointment_duration_default',
        default=1.0,
        help="Default duration for new appointments"
    )
    
    # Vaccination Settings
    auto_schedule_boosters = fields.Boolean(
        string="Auto-schedule Booster Vaccinations",
        config_parameter='pet_management.auto_schedule_boosters',
        default=True,
        help="Automatically schedule booster vaccinations"
    )
    
    # Boarding Settings
    boarding_check_out_advance = fields.Integer(
        string="Check-out Advance (hours)",
        config_parameter='pet_management.boarding_check_out_advance',
        default=2,
        help="Hours before boarding check-out time"
    )
    
    # Grooming Settings
    grooming_session_duration = fields.Float(
        string="Default Grooming Session Duration (hours)",
        config_parameter='pet_management.grooming_session_duration',
        default=2.0,
        help="Default duration for grooming sessions"
    )
    
    # Training Settings
    training_session_duration = fields.Float(
        string="Default Training Session Duration (hours)",
        config_parameter='pet_management.training_session_duration',
        default=1.0,
        help="Default duration for training sessions"
    )
    
    # Diet Settings
    diet_plan_duration_days = fields.Integer(
        string="Default Diet Plan Duration (days)",
        config_parameter='pet_management.diet_plan_duration_days',
        default=30,
        help="Default duration for diet plans"
    )
    
    # Integration Settings
    enable_calendar_integration = fields.Boolean(
        string="Enable Calendar Integration",
        config_parameter='pet_management.enable_calendar_integration',
        default=True,
        help="Integrate with Odoo calendar for appointments"
    )
    
    enable_inventory_integration = fields.Boolean(
        string="Enable Inventory Integration",
        config_parameter='pet_management.enable_inventory_integration',
        default=True,
        help="Integrate with Odoo inventory for supplies"
    )
    

