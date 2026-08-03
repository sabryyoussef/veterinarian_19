# -*- coding: utf-8 -*-
{
    'name': 'PetSpot Vet Feedback & Rewards',
    'version': '19.0.1.1.0',
    'category': 'Services',
    'summary': 'Post-visit vet review survey, WhatsApp delivery, and second-visit discount',
    'description': """
PetSpot Vet Feedback
====================
After a medical visit is completed:
- Sends a short vet-review survey link to the pet owner via WhatsApp (Evolution DM)
- On survey submission, generates a 10% loyalty coupon valid 60 days
- WhatsApps the discount code to the owner
- Feeds owner ratings into veterinarian performance reports
- Optional unticked WhatsApp marketing consent checkbox → pending_review for Sabry
    """,
    'author': 'Sabry Youssef',
    'license': 'LGPL-3',
    'depends': [
        'petspot_clinic_portal',
        'survey',
        'sale_loyalty',
        'base_automation',
        'petspot_wa_marketing_consent',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/survey_data.xml',
        'data/survey_consent_question.xml',
        'data/loyalty_program_data.xml',
        'data/automation.xml',
        'views/pet_medical_visit_views.xml',
        'views/hr_employee_views.xml',
        'views/pet_vet_performance_report_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
