{
    'name': 'Veterinary Clinic - Pet Management Bridge',
    'version': '19.0.1.0.0',
    'category': 'Industries/Pet & Animal',
    'summary': 'Link clinic pets (x_pets) with Pet Management (pet.pet)',
    'description': """
Bridges the Odoo Industry veterinary clinic (x_pets) with WebbyCrown Pet Management:

* 1:1 link x_pets <-> pet.pet
* Species mapping (x_species <-> pet.species)
* Field sync (name, owner, breed, DOB, gender, microchip, photo)
* Smart buttons on both forms
* Bulk sync server action for existing clinic pets
    """,
    'author': 'Demo',
    'license': 'LGPL-3',
    'depends': [
        'veterinary_clinic',
        'pet_management',
        'veterinary_petget_bridge',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/pet_clinic_species_map.xml',
        'data/ir_actions_server.xml',
        'views/pet_pet_views.xml',
        'views/x_pets_views.xml',
        'views/menus.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
}
