# -*- coding: utf-8 -*-


def post_init_hook(env):
    """Idempotent per-company clinic finance accounting + source/category setup."""
    env['pet.clinic.finance.setup'].setup_all_companies()
