# -*- coding: utf-8 -*-


def post_init_hook(env):
    """Migrate legacy singleton Evolution ICP into evolution.instance rows."""
    env['evolution.instance'].migrate_from_icp()
