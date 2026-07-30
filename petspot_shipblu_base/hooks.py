# -*- coding: utf-8 -*-
def post_init_hook(env):
    backends = env["shipblu.backend"].search([])
    if backends:
        backends._ensure_reference_config()
