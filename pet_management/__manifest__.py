# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
{
    'name': 'Pet Management',
    'version': '19.0.1.0.0',
    'summary': 'Manage pets, health records, services, boarding, and diet plans',
    'description': """
Pet Management
==============
Comprehensive module for managing pets, their species, breeds, owners, health records,
vaccinations, medical visits, grooming, training, boarding, appointments, and diet plans.

Key Features:
-------------
* Pet profiles with species and breeds
* Vaccination and medical visit tracking
* Boarding and kennel management
* Grooming and training sessions
* Diet plans and weight monitoring
* Appointment scheduling with calendar integration
* Invoicing integration
* Email notifications
    """,
    'category': 'Services/Clinic',
    'sequence': 150,
    'author': 'WebbyCrown Solutions',
    'website': 'https://www.webbycrown.com',
    'license': 'LGPL-3',
    'depends': ['base', 'base_setup', 'mail', 'contacts', 'hr', 'product', 'account'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'security/record_rules.xml',
        'data/ir_sequence_data.xml',
        'data/pet_seed_data.xml',
        'data/mail_data.xml',
        'data/cron_data.xml',
        'data/email_templates.xml',
        'views/menu_views.xml',
        'views/pet_species_views.xml',
        'views/pet_breed_views.xml',
        'views/pet_pet_views.xml',
        'views/pet_vaccine_views.xml',
        'views/pet_vaccination_views.xml',
        'views/pet_medical_visit_views.xml',
        'views/pet_boarding_views.xml',
        'views/pet_kennel_views.xml',
        'views/pet_appointment_views.xml',
        'views/pet_grooming_views.xml',
        'views/pet_training_views.xml',
        'views/pet_diet_views.xml',
        'views/pet_weight_views.xml',
        'views/pet_notification_views.xml',
        'views/pet_settings_views.xml',
        'views/pet_help_views.xml',
        'data/notification_seed_data_simple.xml',
    ],
    'images': [
        'static/description/main_screenshot.png',
        'static/description/formate_screenshot_1.png',
        'static/description/formate_screenshot_2.png',
        'static/description/formate_screenshot_3.png',
        'static/description/formate_screenshot_4.png',
        'static/description/formate_screenshot_5.png',
        'static/description/formate_screenshot_6.png',
        'static/description/formate_screenshot_7.png',
    ],
    'application': True,
    'installable': True,
    'auto_install': False,
    'assets': {
        'web.assets_backend': [
            'pet_management/static/src/css/pet_notification_kanban.css',
            'pet_management/static/src/css/medical_vaccination_kanban.css',
            'pet_management/static/src/css/image_widget_styling.css',
            'pet_management/static/src/js/weight_badge_styling.js',
        ],
    },
}
