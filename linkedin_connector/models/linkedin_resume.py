import base64
import logging

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

_LI_API = "https://api.linkedin.com/rest"
_LI_VERSION = "202410"


class LinkedinResume(models.Model):
    _name = "linkedin.resume"
    _description = "LinkedIn Resume / Document"
    _order = "upload_date desc, id desc"
    _rec_name = "name"

    account_id = fields.Many2one(
        "linkedin.account", string="Account", required=True, ondelete="cascade", index=True
    )
    name = fields.Char(string="Name", required=True, default="Resume")
    attachment_id = fields.Many2one(
        "ir.attachment",
        string="PDF File",
        domain=[("mimetype", "=", "application/pdf")],
        required=True,
    )
    attachment_name = fields.Char(related="attachment_id.name", string="File Name", readonly=True)
    linkedin_document_urn = fields.Char(
        string="LinkedIn Document URN", copy=False, readonly=True
    )
    upload_date = fields.Datetime(string="Uploaded At", copy=False, readonly=True)
    state = fields.Selection(
        [("draft", "Draft"), ("uploaded", "Uploaded"), ("failed", "Failed")],
        default="draft",
        required=True,
    )
    failure_reason = fields.Text(string="Failure Reason", copy=False, readonly=True)

    def _li_headers(self):
        self.ensure_one()
        if not self.account_id.access_token:
            raise UserError(_("Account is not connected."))
        return {
            "Authorization": "Bearer %s" % self.account_id.access_token,
            "Content-Type": "application/json",
            "LinkedIn-Version": _LI_VERSION,
            "X-Restli-Protocol-Version": "2.0.0",
        }

    def action_upload(self):
        self.ensure_one()
        if not self.attachment_id:
            raise UserError(_("Attach a PDF file before uploading."))
        account = self.account_id
        headers = self._li_headers()
        author_urn = account.linkedin_member_urn
        if not author_urn:
            raise UserError(_("Account has no LinkedIn member URN. Reconnect the account."))

        # Step 1 — initialize upload
        init_resp = requests.post(
            "%s/documents?action=initializeUpload" % _LI_API,
            headers=headers,
            json={
                "initializeUploadRequest": {
                    "owner": author_urn,
                }
            },
            timeout=20,
        )
        if init_resp.status_code != 200:
            self.write({"state": "failed", "failure_reason": init_resp.text})
            raise UserError(_("LinkedIn document init failed: %s") % init_resp.text)

        init_data = init_resp.json().get("value", {})
        upload_url = init_data.get("uploadUrl")
        doc_urn = init_data.get("document")
        if not upload_url or not doc_urn:
            msg = "Unexpected init response: %s" % init_data
            self.write({"state": "failed", "failure_reason": msg})
            raise UserError(_("LinkedIn document init error: %s") % msg)

        # Step 2 — upload binary
        pdf_data = base64.b64decode(self.attachment_id.datas or b"")
        put_resp = requests.put(
            upload_url,
            data=pdf_data,
            headers={
                "Authorization": "Bearer %s" % account.access_token,
                "Content-Type": "application/octet-stream",
            },
            timeout=120,
        )
        if put_resp.status_code not in (200, 201):
            msg = "HTTP %s: %s" % (put_resp.status_code, put_resp.text)
            self.write({"state": "failed", "failure_reason": msg})
            raise UserError(_("LinkedIn document upload failed: %s") % msg)

        self.write({
            "state": "uploaded",
            "linkedin_document_urn": doc_urn,
            "upload_date": fields.Datetime.now(),
            "failure_reason": False,
        })
        _logger.info("linkedin.resume %s uploaded urn=%s", self.id, doc_urn)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("LinkedIn"),
                "message": _("Document uploaded: %s") % doc_urn,
                "type": "success",
            },
        }

    def action_post_as_document(self):
        """Create a linkedin.post pre-filled to share this document."""
        self.ensure_one()
        if self.state != "uploaded" or not self.linkedin_document_urn:
            raise UserError(_("Upload the document to LinkedIn first."))
        post = self.env["linkedin.post"].create({
            "account_id": self.account_id.id,
            "message": _("Check out my resume: %s") % self.name,
        })
        return {
            "type": "ir.actions.act_window",
            "res_model": "linkedin.post",
            "res_id": post.id,
            "view_mode": "form",
            "target": "current",
        }
