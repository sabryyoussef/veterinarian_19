from odoo import api, fields, models


class PetgetAnimal(models.Model):
    _inherit = 'petget.animal'

    color_id = fields.Many2one('petget.dog.color', string='Color / Markings')
    life_stage_id = fields.Many2one(
        'petget.dog.life.stage', string='Current Life Stage',
        compute='_compute_life_stage',
    )
    life_stage_feeding = fields.Text(
        string='Feeding Guidance', related='life_stage_id.feeding_guidance',
    )
    life_stage_care = fields.Text(
        string='Care Focus', related='life_stage_id.care_focus',
    )

    @api.depends('date_of_birth', 'species')
    def _compute_life_stage(self):
        today = fields.Date.context_today(self)
        stages = self.env['petget.dog.life.stage'].search([])
        for rec in self:
            stage = self.env['petget.dog.life.stage']
            if rec.species == 'dog' and rec.date_of_birth and rec.date_of_birth <= today:
                weeks = (today - rec.date_of_birth).days // 7
                for s in stages:
                    lo = s.age_from_weeks or 0
                    hi = s.age_to_weeks or 0
                    if weeks >= lo and (hi == 0 or weeks < hi):
                        stage = s
                        break
            rec.life_stage_id = stage.id
