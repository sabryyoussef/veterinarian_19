{
    'name': 'Petget: Core',
    'version': '19.0.1.0.0',
    'category': 'Industries/Pet & Animal',
    'summary': 'Foundation models for the Petget breeding platform',
    'description': """
Petget Core
===========
Species-agnostic foundation for the Petget breeding management platform:
animal profile, documents, reminders, and audit timeline.

This is the skeleton module — models and views are added incrementally.
""",
    'author': 'BSD',
    'website': 'https://thepetget.com',
    'support': 'hello@thepetget.com',
    'license': 'AGPL-3',
    'images': ['static/description/banner.png', 'static/description/screenshot1.png', 'static/description/screenshot2.png'],
    'depends': [
        'base',
        'mail',
        'contacts',
    ],
    'data': [
        'security/petget_security.xml',
        'security/ir.model.access.csv',
        'data/petget_sequence.xml',
        'views/petget_animal_views.xml',
        'views/petget_document_views.xml',
        'views/petget_reminder_views.xml',
        'views/petget_note_views.xml',
        'views/petget_menus.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
