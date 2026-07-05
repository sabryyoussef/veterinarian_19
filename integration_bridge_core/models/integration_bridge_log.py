# -*- coding: utf-8 -*-
from odoo import models, fields, api
from datetime import timedelta
import logging

_logger = logging.getLogger(__name__)


class IntegrationBridgeLog(models.Model):
    _name = 'integration.bridge.log'
    _description = 'Integration Bridge Request/Response Log'
    _order = 'create_date desc, id desc'
    _rec_name = 'name'

    name = fields.Char(
        string='Log Entry',
        required=True,
        help='Brief description of the integration event'
    )

    direction = fields.Selection([
        ('inbound', 'Inbound'),
        ('outbound', 'Outbound'),
    ], string='Direction', required=True, default='inbound',
       help='Direction of the integration call')

    platform = fields.Selection([
        ('chatwoot', 'Chatwoot'),
        ('typebot', 'Typebot'),
        ('evolution', 'Evolution API'),
        ('n8n', 'n8n'),
        ('dify', 'Dify AI'),
        ('flowise', 'Flowise'),
        ('ai', 'AI Agent'),
        ('other', 'Other'),
    ], string='Platform', required=True, index=True,
       help='External platform involved in the integration')

    endpoint = fields.Char(
        string='Endpoint/URL',
        help='API endpoint that was called'
    )

    external_id = fields.Char(
        string='External ID',
        index=True,
        help='External reference ID (conversation_id, form_id, etc.)'
    )

    status = fields.Selection([
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('pending', 'Pending'),
    ], string='Status', required=True, default='pending', index=True,
       help='Status of the integration call')

    request_payload = fields.Text(
        string='Request Payload',
        help='Full request data (JSON format)'
    )

    response_payload = fields.Text(
        string='Response Payload',
        help='Full response data (JSON format)'
    )

    http_status = fields.Integer(
        string='HTTP Status Code',
        help='HTTP status code of the response (200, 401, 500, etc.)'
    )

    error_message = fields.Text(
        string='Error Message',
        help='Error message if the call failed'
    )

    related_model = fields.Char(
        string='Related Model',
        help='Odoo model related to this integration (e.g., error.report)'
    )

    related_res_id = fields.Integer(
        string='Related Record ID',
        help='ID of the related record in Odoo'
    )

    retry_count = fields.Integer(
        string='Retry Count',
        default=0,
        help='Number of retry attempts'
    )

    duration_ms = fields.Integer(
        string='Duration (ms)',
        help='Time taken for the request in milliseconds'
    )

    user_agent = fields.Char(
        string='User Agent',
        help='User agent string from request headers'
    )

    remote_ip = fields.Char(
        string='Remote IP',
        help='IP address of the caller'
    )

    @api.model
    def log_integration(self, name, direction, platform, endpoint='', external_id='', 
                       status='pending', request_payload='', response_payload='',
                       http_status=0, error_message='', related_model='', 
                       related_res_id=0, retry_count=0, duration_ms=0,
                       user_agent='', remote_ip=''):
        """
        Helper method to create integration log entry.
        Returns the created log record.
        """
        vals = {
            'name': name,
            'direction': direction,
            'platform': platform,
            'endpoint': endpoint,
            'external_id': external_id,
            'status': status,
            'request_payload': request_payload,
            'response_payload': response_payload,
            'http_status': http_status,
            'error_message': error_message,
            'related_model': related_model,
            'related_res_id': related_res_id,
            'retry_count': retry_count,
            'duration_ms': duration_ms,
            'user_agent': user_agent,
            'remote_ip': remote_ip,
        }
        
        try:
            log = self.create(vals)
            _logger.info(f"[Integration Log] {direction.upper()} {platform} - {name} - Status: {status}")
            return log
        except Exception as e:
            _logger.error(f"[Integration Log] Failed to create log entry: {e}")
            return False

    def action_retry(self):
        """Action button to retry failed integrations"""
        self.ensure_one()
        if self.direction == 'outbound' and self.status == 'failed':
            self.write({'status': 'pending', 'retry_count': self.retry_count + 1})
            _logger.info(f"[Integration Log] Retry queued for log #{self.id}")
        return True

    @api.model
    def cleanup_old_logs(self, days=90):
        """
        Clean up old log entries.
        Called by scheduled action.
        """
        cutoff_date = fields.Datetime.now() - timedelta(days=days)
        old_logs = self.search([('create_date', '<', cutoff_date)])
        count = len(old_logs)
        old_logs.unlink()
        _logger.info(f"[Integration Log] Cleaned up {count} old log entries (>{days} days)")
        return count
