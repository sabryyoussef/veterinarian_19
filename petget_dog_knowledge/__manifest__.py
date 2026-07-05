{
    'name': 'Petget: Dog Knowledge Base',
    'version': '19.0.1.0.0',
    'category': 'Industries/Pet & Animal',
    'summary': 'Breed knowledge, life stages, feeding and reproduction guidance',
    'description': """
Petget Dog Knowledge Base
=========================
Turns the dog breed catalog into a knowledge base: per-breed profile
(origin, temperament, size, lifespan, grooming/exercise/trainability,
common health issues, reproduction timing), a breed photo, and a shared
set of canine life stages with feeding and care guidance. Every dog shows
its current life stage and the matching feeding guidance.

Helps breeders and their buyers understand the breed — building the
knowledge and the customer relationship that drive sales and referrals.
""",
    'author': 'BSD',
    'website': 'https://thepetget.com',
    'support': 'hello@thepetget.com',
    'license': 'AGPL-3',
    'images': ['static/description/banner.png'],
    'depends': [
        'petget_dog',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/petget_dog_life_stage_data.xml',
        'data/petget_dog_color_data.xml',
        'data/petget_dog_breed_data.xml',
        'data/petget_breed_origin_data.xml',
        'data/petget_breed_growth_data.xml',
        'views/petget_dog_life_stage_views.xml',
        'views/petget_dog_color_views.xml',
        'views/petget_dog_breed_views.xml',
        'views/petget_animal_views.xml',
        'views/petget_menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
