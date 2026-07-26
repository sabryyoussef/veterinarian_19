# -*- coding: utf-8 -*-
{
    "name": "Dev Hub Infrastructure",
    "version": "19.0.9.1.1",
    "category": "Productivity",
    "summary": "Tailscale/SSH machine destination verification",
    "author": "Sabry Youssef",
    "license": "LGPL-3",
    "depends": ["devhub_core"],
    "data": [
        "security/ir.model.access.csv",
        "views/dev_machine_verification_views.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
