# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request


class PetspotCampaignController(http.Controller):

    @http.route("/campaign/<string:campaign_code>", type="http", auth="public", website=True, sitemap=True)
    def campaign_landing(self, campaign_code, **kwargs):
        campaign = (
            request.env["petspot.campaign"]
            .sudo()
            .search([("code", "=", campaign_code), ("state", "=", "active")], limit=1)
        )
        if not campaign:
            campaign = (
                request.env["petspot.campaign"]
                .sudo()
                .search([("code", "=", campaign_code)], limit=1)
            )
        if not campaign:
            return request.not_found()
        steps = campaign.step_ids.sorted("sequence")
        return request.render(
            "petspot_campaign_rewards.campaign_landing_page",
            {
                "campaign": campaign,
                "steps": steps,
            },
        )

    @http.route(
        "/campaign/<string:campaign_code>/step/<int:step_sequence>",
        type="http",
        auth="public",
        website=True,
    )
    def campaign_step_redirect(self, campaign_code, step_sequence, **kwargs):
        campaign = (
            request.env["petspot.campaign"]
            .sudo()
            .search([("code", "=", campaign_code)], limit=1)
        )
        if not campaign:
            return request.not_found()
        step = campaign.step_ids.filtered(lambda s: s.sequence == step_sequence)[:1]
        if not step:
            return request.not_found()
        return request.render(
            "petspot_campaign_rewards.campaign_step_page",
            {
                "campaign": campaign,
                "step": step,
            },
        )

    @http.route(
        "/campaign/reward/<string:answer_token>",
        type="http",
        auth="public",
        website=True,
    )
    def campaign_reward(self, answer_token, **kwargs):
        user_input = (
            request.env["survey.user_input"]
            .sudo()
            .search([("access_token", "=", answer_token)], limit=1)
        )
        if not user_input:
            return request.not_found()
        step = user_input.petspot_campaign_step_id
        campaign = user_input.petspot_campaign_id
        card = user_input.loyalty_card_id
        book_url = ""
        if card:
            token = user_input.portal_booking_token_id
            if not token:
                token = (
                    request.env["petspot.portal.token"]
                    .sudo()
                    .search(
                        [("loyalty_card_id", "=", card.id), ("state", "=", "open")],
                        limit=1,
                        order="id desc",
                    )
                )
            if token:
                book_url = token.access_url
        return request.render(
            "petspot_campaign_rewards.campaign_reward_page",
            {
                "user_input": user_input,
                "campaign": campaign,
                "step": step,
                "card": card,
                "passed": user_input.scoring_success,
                "book_url": book_url,
            },
        )
