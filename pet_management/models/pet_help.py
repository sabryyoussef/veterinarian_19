from odoo import models, fields # type: ignore

class PetHelp(models.TransientModel):
    _name = 'pet.help'
    _description = 'Pet Management Help Guide'
    
    name = fields.Char(string='Help Guide', default='Pet Management - Complete Help Guide')

