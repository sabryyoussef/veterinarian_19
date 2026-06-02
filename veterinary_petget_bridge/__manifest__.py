{
    'name': 'Veterinary Clinic - Petget Bridge',
    'version': '19.0.2.1.0',
    'category': 'Industries/Pet & Animal',
    'summary': 'Link clinic pets (x_pets) with Petget dog knowledge — no duplicate animals',
    'description': """
Integrates the veterinary clinic pet registry with Petget dog knowledge:

* **x_pets** remains the single pet record for consultations, appointments, and billing
* **petget.dog.breed** knowledge (temperament, care, health, growth) on the pet form
* **Documents, reminders, and activity timeline** linked to clinic pets
* Hides the standalone Petget Animals app to avoid duplicate pet entry
* Dog configuration under Pets > Configuration
    """,
    'author': 'Demo',
    'license': 'LGPL-3',
    'depends': [
        'veterinary_clinic',
        'petget_dog_knowledge',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_model_fields.xml',
        'data/ir_actions_server.xml',
        'data/base_automation.xml',
        'data/ir_actions_act_window.xml',
        'views/x_pets_views.xml',
        'views/menus.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
}
