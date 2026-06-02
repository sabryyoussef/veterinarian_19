"""Post-install: link dogs, hide Petget app, seed sample clinic pet data."""
import base64

_DEMO_FILE = base64.b64encode(b'VET-DEMO-PDF-PLACEHOLDER').decode('ascii')


def _seed_clinic_petget_demo(env):
    """Add sample documents, reminders, and notes on first dogs (once)."""
    Document = env['petget.document']
    if Document.search_count([('x_pet_id', '!=', False)]) > 0:
        return

    dog_species = env.ref('veterinary_clinic.x_species_2', raise_if_not_found=False)
    if not dog_species:
        return

    dogs = env['x_pets'].search([('x_species', '=', dog_species.id)], limit=5, order='id')
    today = env.context.get('date') or __import__('datetime').date.today()

    for idx, pet in enumerate(dogs):
        if not Document.search_count([('x_pet_id', '=', pet.id)]):
            Document.create({
                'name': 'Vaccination Record',
                'x_pet_id': pet.id,
                'category': 'vaccination',
                'file': _DEMO_FILE,
                'file_name': f'{pet.x_name}_vaccination.pdf',
                'issue_date': today,
            })
            Document.create({
                'name': 'Health Check Report',
                'x_pet_id': pet.id,
                'category': 'health_check',
                'file': _DEMO_FILE,
                'file_name': f'{pet.x_name}_health.pdf',
                'issue_date': today,
            })
        env['petget.reminder'].create({
            'name': 'Annual vaccination booster',
            'x_pet_id': pet.id,
            'reminder_type': 'vaccination',
            'due_date': today,
        })
        env['petget.note'].create({
            'x_pet_id': pet.id,
            'note_type': 'health',
            'body': f'Initial clinic intake completed for {pet.x_name}.',
        })


def post_init_hook(env):
    dog_species = env.ref('veterinary_clinic.x_species_2', raise_if_not_found=False)
    if not dog_species:
        dog_species = env['x_species'].search([('x_name', '=', 'Dog')], limit=1)
    if dog_species:
        dogs = env['x_pets'].search([('x_species', '=', dog_species.id)])
        if dogs:
            ctx = {'active_model': 'x_pets', 'active_ids': dogs.ids}
            env.ref('veterinary_petget_bridge.action_sync_x_breed_to_petget').with_context(**ctx).run()
            env.ref('veterinary_petget_bridge.action_sync_petget_breed_to_x_breed').with_context(**ctx).run()

    if env['petget.animal'].search_count([]) == 0:
        root = env.ref('petget_core.petget_core_menu_root', raise_if_not_found=False)
        if root:
            root.active = False

    _seed_clinic_petget_demo(env)
