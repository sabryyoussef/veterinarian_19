import logging

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LinkedinConversation(models.Model):
    _name = "linkedin.conversation"
    _description = "LinkedIn Conversation"
    _order = "last_activity_at desc, id desc"
    _rec_name = "display_name"

    account_id = fields.Many2one(
        "linkedin.account", string="Account", required=True, ondelete="cascade", index=True
    )
    conversation_id = fields.Char(string="Conversation ID", index=True)
    participants = fields.Text(string="Participants (JSON)")
    display_name = fields.Char(
        string="Participants", compute="_compute_display_name", store=True
    )
    last_message = fields.Text(string="Last Message")
    last_activity_at = fields.Datetime(string="Last Activity")
    unread_count = fields.Integer(string="Unread", default=0)
    message_ids = fields.One2many(
        "linkedin.message", "conversation_id", string="Messages"
    )

    @api.depends("participants")
    def _compute_display_name(self):
        import json as _json
        for rec in self:
            try:
                parts = _json.loads(rec.participants or "[]")
                names = [p.get("name") or p.get("entityUrn") or "?" for p in parts]
                rec.display_name = ", ".join(names[:3]) or "Conversation"
            except Exception:
                rec.display_name = "Conversation"

    def _li_headers(self):
        self.ensure_one()
        if not self.account_id.access_token:
            raise UserError(_("Account is not connected."))
        return {
            "Authorization": "Bearer %s" % self.account_id.access_token,
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        }

    # ------------------------------------------------------------------
    # Fetch conversations
    # ------------------------------------------------------------------
    @api.model
    def _fetch_for_account(self, account):
        if not account.access_token:
            return 0
        headers = {
            "Authorization": "Bearer %s" % account.access_token,
            "X-Restli-Protocol-Version": "2.0.0",
        }
        resp = requests.get(
            "https://api.linkedin.com/v2/conversations",
            headers=headers,
            params={"q": "viewer", "viewerId": account.linkedin_member_urn or ""},
            timeout=20,
        )
        if resp.status_code == 403:
            _logger.warning(
                "linkedin.conversation: 403 for account %s — w_messages scope not granted", account.id
            )
            return 0
        if resp.status_code != 200:
            _logger.error(
                "linkedin.conversation: fetch failed account=%s HTTP %s", account.id, resp.status_code
            )
            return 0
        items = resp.json().get("elements", [])
        import json as _json
        new_count = 0
        for item in items:
            conv_id = item.get("entityUrn") or item.get("id") or ""
            if not conv_id:
                continue
            existing = self.search([("conversation_id", "=", conv_id), ("account_id", "=", account.id)], limit=1)
            participants = _json.dumps([
                {"name": p.get("miniProfile", {}).get("firstName", "") + " " + p.get("miniProfile", {}).get("lastName", ""),
                 "entityUrn": p.get("entityUrn")}
                for p in item.get("participants", [])
            ])
            events = item.get("events", [])
            last_event = events[0] if events else {}
            last_body = (last_event.get("eventContent") or {}).get("messageEvent", {}).get("body") or ""
            last_ts = last_event.get("createdAt")
            vals = {
                "account_id": account.id,
                "conversation_id": conv_id,
                "participants": participants,
                "last_message": last_body[:200],
                "last_activity_at": fields.Datetime.to_string(
                    __import__("datetime").datetime.utcfromtimestamp(int(last_ts) / 1000)
                ) if last_ts else False,
                "unread_count": item.get("totalEventCount", 0),
            }
            if existing:
                existing.write(vals)
            else:
                self.create(vals)
                new_count += 1
        return new_count

    @api.model
    def _cron_sync_messages(self):
        accounts = self.env["linkedin.account"].search([("access_token", "!=", False)])
        for acc in accounts:
            try:
                self._fetch_for_account(acc)
                self.env.cr.commit()
            except Exception as exc:
                _logger.error("linkedin.conversation sync error acc=%s: %s", acc.id, exc)
                self.env.cr.rollback()

    def action_load_messages(self):
        self.ensure_one()
        headers = self._li_headers()
        resp = requests.get(
            "https://api.linkedin.com/v2/conversations/%s/events" % self.conversation_id,
            headers=headers,
            params={"q": "conversation", "count": 50},
            timeout=20,
        )
        if resp.status_code == 403:
            raise UserError(
                _("LinkedIn Messaging API returned 403. "
                  "The w_messages scope is required and must be approved for your app.")
            )
        if resp.status_code != 200:
            raise UserError(_("Failed to load messages: %s") % resp.text)
        Msg = self.env["linkedin.message"]
        for event in resp.json().get("elements", []):
            msg_id = event.get("entityUrn") or ""
            body = (event.get("eventContent") or {}).get("messageEvent", {}).get("body") or ""
            ts = event.get("createdAt")
            existing = Msg.search([("linkedin_msg_id", "=", msg_id)], limit=1)
            vals = {
                "conversation_id": self.id,
                "body": body,
                "linkedin_msg_id": msg_id,
                "sent_at": fields.Datetime.to_string(
                    __import__("datetime").datetime.utcfromtimestamp(int(ts) / 1000)
                ) if ts else False,
                "direction": "in",
            }
            if not existing:
                Msg.create(vals)
        self.unread_count = 0


class LinkedinMessage(models.Model):
    _name = "linkedin.message"
    _description = "LinkedIn Message"
    _order = "sent_at asc, id asc"

    conversation_id = fields.Many2one(
        "linkedin.conversation", string="Conversation", required=True, ondelete="cascade", index=True
    )
    sender_name = fields.Char(string="Sender")
    body = fields.Text(string="Message")
    sent_at = fields.Datetime(string="Sent At")
    direction = fields.Selection(
        [("in", "Received"), ("out", "Sent")], default="in", required=True
    )
    linkedin_msg_id = fields.Char(string="LinkedIn Message ID", index=True)

    def action_reply(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "linkedin.message.reply",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_conversation_id": self.conversation_id.id,
            },
        }


class LinkedinMessageReply(models.TransientModel):
    _name = "linkedin.message.reply"
    _description = "Reply to LinkedIn Message"

    conversation_id = fields.Many2one("linkedin.conversation", required=True, ondelete="cascade")
    body = fields.Text(string="Reply", required=True)

    def action_send(self):
        self.ensure_one()
        conv = self.conversation_id
        account = conv.account_id
        if not account.access_token:
            raise UserError(_("Account is not connected."))
        headers = {
            "Authorization": "Bearer %s" % account.access_token,
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        }
        payload = {
            "recipients": [],
            "subject": "",
            "body": self.body,
            "conversationId": conv.conversation_id,
        }
        resp = requests.post(
            "https://api.linkedin.com/v2/messages",
            headers=headers,
            json=payload,
            timeout=20,
        )
        if resp.status_code == 403:
            raise UserError(
                _("LinkedIn Messaging API returned 403. "
                  "The w_messages scope is required and must be approved for your app.")
            )
        if resp.status_code not in (200, 201):
            raise UserError(_("Failed to send message: %s") % resp.text)
        self.env["linkedin.message"].create({
            "conversation_id": conv.id,
            "body": self.body,
            "sent_at": fields.Datetime.now(),
            "direction": "out",
            "sender_name": account.name,
        })
        return {"type": "ir.actions.act_window_close"}
