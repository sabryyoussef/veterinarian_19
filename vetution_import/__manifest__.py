# -*- coding: utf-8 -*-
{
    "name": "Vetution Import",
    "summary": "Import the Vetution veterinary catalog into Odoo (schema + sync)",
    "version": "19.0.1.5.0",
    "category": "Inventory/Inventory",
    "author": "Sabry Youssef",
    "author_email": "vendorah2@gmail.com, abhorya@gmail.com",
    "website": "https://github.com/sabryyoussef",
    "license": "LGPL-3",
    "depends": [
        "product",
        "stock",
        "sale_management",
        "website_sale",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/product_attribute_data.xml",
        "data/product_category_data.xml",
        "views/vetution_brand_views.xml",
        "views/vetution_species_views.xml",
        "views/vetution_ingredient_views.xml",
        "views/product_template_views.xml",
        "views/product_product_views.xml",
        "views/product_public_category_views.xml",
        "wizard/vetution_sync_wizard_views.xml",
        "views/website_sale_templates.xml",
        "views/menuitem.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "vetution_import/static/src/scss/vetution_shop.scss",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
}
