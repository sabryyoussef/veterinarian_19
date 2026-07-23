# -*- coding: utf-8 -*-
"""Skip irrelevant inbox mail when fetchmail pulls from Gmail (CRM noise)."""
import email
import email.policy
import logging
from xmlrpc import client as xmlrpclib

from odoo import api, models

_logger = logging.getLogger(__name__)

# Keys added by our custom message_parse for business analytics on CRM leads.
# They are consumed in CrmLeadGmail.message_new / message_update, but must
# NOT reach message_post / _notify_thread, which in Odoo 19 use a strict
# whitelist and raise ValueError for any unrecognised kwarg.
_GMAIL_GATEWAY_KEYS = frozenset({
    "gmail_labels",
    "gateway_mail_to",
    "gateway_mail_cc",
    "mail_list_id",
})


class MailThreadGmailFetchmail(models.AbstractModel):
    _inherit = "mail.thread"

    @api.model
    def message_parse(self, message, save_original=False):
        """Add Gmail / gateway metadata from headers for CRM search/filter."""
        msg_dict = super().message_parse(message, save_original=save_original)
        # Gmail IMAP: label list (may be missing on some fetches)
        for header in ("X-Gmail-Labels", "X-GM-Labels"):
            raw = message.get(header)
            if raw:
                break
        if raw:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", "replace")
            s = str(raw).strip()
            if s:
                msg_dict["gmail_labels"] = s
        # Recipients snapshot (helps filter “mail to me / alias”)
        to_hdr = msg_dict.get("to") or ""
        if to_hdr:
            msg_dict["gateway_mail_to"] = to_hdr[:8000]
        cc_hdr = msg_dict.get("cc") or ""
        if cc_hdr:
            msg_dict["gateway_mail_cc"] = cc_hdr[:4000]
        # Mailing lists
        lid = message.get("List-Id") or message.get("List-ID")
        if lid:
            if isinstance(lid, bytes):
                lid = lid.decode("utf-8", "replace")
            msg_dict["mail_list_id"] = str(lid).strip()[:500]
        return msg_dict

    def _gmail_fetchmail_should_skip(self, msg_dict):
        """Return True if this message should not create CRM / thread records."""
        fid = self.env.context.get("default_fetchmail_server_id")
        if not fid:
            return False
        server = self.env["fetchmail.server"].sudo().browse(fid)
        if not server.exists() or server.server_type != "gmail":
            return False
        email_from = (msg_dict.get("email_from") or "").lower()
        subject = (msg_dict.get("subject") or "").lower()
        exclude = (server.gmail_inbound_exclude_domains or "").strip()
        if exclude:
            for part in exclude.split(","):
                domain = part.strip().lower()
                if domain and domain in email_from:
                    _logger.info(
                        "Gmail fetchmail: skipped (sender matched exclude %r) from=%s",
                        domain,
                        msg_dict.get("email_from"),
                    )
                    return True
        keywords = (server.gmail_inbound_subject_keywords or "").strip()
        if keywords:
            found = False
            for part in keywords.replace("\n", ",").split(","):
                kw = part.strip().lower()
                if kw and kw in subject:
                    found = True
                    break
            if not found:
                _logger.info(
                    "Gmail fetchmail: skipped (subject keywords not matched) subject=%s",
                    msg_dict.get("subject"),
                )
                return True
        return False

    @api.model
    def message_process(
        self,
        model,
        message,
        custom_values=None,
        save_original=False,
        strip_attachments=False,
        thread_id=None,
    ):
        if isinstance(message, xmlrpclib.Binary):
            raw_bytes = bytes(message.data)
        elif isinstance(message, str):
            raw_bytes = message.encode("utf-8")
        else:
            raw_bytes = message

        msg_parsed = email.message_from_bytes(raw_bytes, policy=email.policy.SMTP)
        msg_dict = self.message_parse(msg_parsed, save_original=save_original)
        if strip_attachments:
            msg_dict.pop("attachments", None)

        if self._gmail_fetchmail_should_skip(msg_dict):
            return False

        return super().message_process(
            model,
            raw_bytes,
            custom_values=custom_values,
            save_original=save_original,
            strip_attachments=strip_attachments,
            thread_id=thread_id,
        )

    def message_post(self, **kwargs):
        """Strip Gmail gateway metadata before entering the Odoo 19 mail pipeline.

        message_parse injects gateway_mail_to / gateway_mail_cc / gmail_labels /
        mail_list_id into msg_dict so that CrmLeadGmail.message_new can store them
        on the lead.  _message_route_process spreads the full msg_dict into
        post_params via **message_dict, so those keys reach message_post.
        They are NOT mail.message fields, so message_post routes them into
        notif_kwargs and passes them to _notify_thread, which in Odoo 19 performs
        a strict whitelist check (_get_notify_valid_parameters) and raises
        ValueError for any unrecognised key.

        By the time message_post is called the values have already been consumed
        by message_new, so stripping them here is safe and lossless.
        """
        for key in _GMAIL_GATEWAY_KEYS:
            kwargs.pop(key, None)
        return super().message_post(**kwargs)

    def message_notify(self, **kwargs):
        """Same sanitization for the message_notify path.

        _message_route_process calls message_notify (instead of message_post)
        when thread_root._name == 'mail.thread' -- an edge case, but the same
        kwargs pollution applies.
        """
        for key in _GMAIL_GATEWAY_KEYS:
            kwargs.pop(key, None)
        return super().message_notify(**kwargs)
