# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request


class SabryDeveloperWebsite(http.Controller):

    def _sabry_website(self):
        Website = request.env['website'].sudo()
        return Website.search([('name', 'ilike', 'Sabry')], limit=1) or request.website

    @http.route(['/sabry', '/sabry/home'], type='http', auth='public', website=True)
    def sabry_home(self, **kwargs):
        return request.render('sabry_developer_website.page_home', {
            'website': self._sabry_website(),
        })

    @http.route('/sabry/cv', type='http', auth='public', website=True)
    def sabry_cv(self, **kwargs):
        return request.render('sabry_developer_website.page_cv', {
            'website': self._sabry_website(),
        })

    @http.route('/sabry/contact', type='http', auth='public', website=True)
    def sabry_contact(self, **kwargs):
        return request.render('sabry_developer_website.page_contact', {
            'website': self._sabry_website(),
        })
