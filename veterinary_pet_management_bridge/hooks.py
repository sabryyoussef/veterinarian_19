"""Post-install: map species, grant PM groups to admins, sync existing clinic pets."""


def post_init_hook(env):
    env['pet.pet'].sync_from_clinic_pets()
