{
    'name': 'Petget: Dog',
    'version': '19.0.1.0.0',
    'category': 'Industries/Pet & Animal',
    'summary': 'Dog species extension for the Petget platform',
    'description': """
Petget Dog
==========
Adds dog-specific data to the Petget animal profile: breed catalog
(AKC breeds pre-loaded), coat type, AKC registration, and puppy-stage
fields (temporary ID, collar colour). Dog fields appear only when the
animal's species is "Dog".
""",
    'author': 'BSD',
    'website': 'https://thepetget.com',
    'support': 'hello@thepetget.com',
    'license': 'AGPL-3',
    'images': ['static/description/banner.png', 'static/description/screenshot1.png', 'static/description/screenshot2.png'],
    'depends': [
        'petget_core',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/petget.dog.breed.csv',
        'views/petget_dog_breed_views.xml',
        'views/petget_animal_views.xml',
        'views/petget_menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
