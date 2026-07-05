# -*- coding: utf-8 -*-
from odoo import models, fields, api
import logging
import json
import requests
from datetime import timedelta

_logger = logging.getLogger(__name__)


class IntegrationOutboundQueue(models.Model):
    _name = 'integration.outbound.queue'
    _description = 'Outbound Integration Message Queue'
    _order = 'priority desc, create_date asc, id asc'
    _rec_name = 'name'

    name = fields.Char(
        string='Message Title',
        required=True,
        help='Brief description of the outbound message'
    )

    platform = fields.Selection([
        ('chatwoot', 'Chatwoot'),
        ('typebot', 'Typebot'),
        ('evolution', 'Evolution API'),
        ('n8n', 'n8n'),
        ('ai', 'AI Agent'),
        ('other', 'Other'),
    ], string='Target Platform', required=True, index=True,
       help='Destination platform for this message')

    endpoint_url = fields.Char(
        string='Endpoint URL',
        required=True,
        help='Full URL to send the message to'
    )

    payload = fields.Text(
        string='Payload (JSON)',
        required=True,
        help='Message payload in JSON format'
    )

    status = fields.Selection([
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    ], string='Status', required=True, default='pending', index=True,
       help='Current status of the outbound message')

    priority = fields.Integer(
        string='Priority',
        default=5,
        help='Priority for sending (10=highest, 1=lowest)'
    )

    related_model = fields.Char(
        string='Related Model',
        help='Odoo model this message relates to (e.g., error.report)'
    )

    related_res_id = fields.Integer(
        string='Related Record ID',
        help='ID of the related Odoo record'
    )

    retry_count = fields.Integer(
        string='Retry Count',
        default=0,
        readonly=True,
        help='Number of retry attempts'
    )

    max_retries = fields.Integer(
        string='Max Retries',
        default=3,
        help='Maximum number of retry attempts'
    )

    error_message = fields.Text(
        string='Error Message',
        readonly=True,
        help='Last error message if sending failed'
    )

    sent_at = fields.Datetime(
        string='Sent At',
        readonly=True,
        help='When the message was successfully sent'
    )

    next_retry_at = fields.Datetime(
        string='Next Retry At',
        help='Scheduled time for next retry attempt'
    )

    http_method = fields.Selection([
        ('GET', 'GET'),
        ('POST', 'POST'),
        ('PUT', 'PUT'),
        ('PATCH', 'PATCH'),
        ('DELETE', 'DELETE'),
    ], string='HTTP Method', default='POST',
       help='HTTP method to use for the request')

    headers = fields.Text(
        string='HTTP Headers (JSON)',
        default='{}',
        help='Additional HTTP headers as JSON object'
    )

    response_data = fields.Text(
        string='Response Data',
        readonly=True,
        help='Response received from the endpoint'
    )

    http_status_code = fields.Integer(
        string='HTTP Status Code',
        readonly=True,
        help='HTTP status code from the response'
    )

    log_id = fields.Many2one(
        'integration.bridge.log',
        string='Integration Log',
        readonly=True,
        help='Link to the integration log entry'
    )

    @api.model
    def create_outbound_message(self, name, platform, endpoint_url, payload,
                                related_model='', related_res_id=0, priority=5,
                                http_method='POST', headers=None,
                                scheduled_at=None):
        """
        Helper method to queue an outbound message.
        
        Args:
            name: Message title
            platform: Target platform
            endpoint_url: Full URL to send to
            payload: Message payload (dict or JSON string)
            related_model: Odoo model name (optional)
            related_res_id: Odoo record ID (optional)
            priority: Priority (10=highest, 1=lowest)
            http_method: HTTP method (default POST)
            headers: Additional headers as dict (optional)
        
        Returns:
            Created integration.outbound.queue record
        """
        if isinstance(payload, dict):
            payload = json.dumps(payload, ensure_ascii=False)
        
        if headers and isinstance(headers, dict):
            headers = json.dumps(headers, ensure_ascii=False)
        elif not headers:
            headers = '{}'
        
        vals = {
            'name': name,
            'platform': platform,
            'endpoint_url': endpoint_url,
            'payload': payload,
            'status': 'pending',
            'priority': priority,
            'related_model': related_model,
            'related_res_id': related_res_id,
            'http_method': http_method,
            'headers': headers,
        }
        if scheduled_at:
            vals['next_retry_at'] = scheduled_at
        
        message = self.create(vals)
        _logger.info(f"[Outbound Queue] Message queued #{message.id}: {name} → {platform}")
        return message

    def send_message(self):
        """
        Send the outbound message.
        Called by cron job or manually.
        """
        self.ensure_one()
        
        if self.status == 'sent':
            _logger.info(f"[Outbound Queue] Message #{self.id} already sent")
            return True
        
        if self.retry_count >= self.max_retries:
            _logger.error(f"[Outbound Queue] Message #{self.id} exceeded max retries ({self.max_retries})")
            self.write({'status': 'failed', 'error_message': 'Max retries exceeded'})
            return False
        
        _logger.info(f"[Outbound Queue] Sending message #{self.id} to {self.platform}")
        
        import time
        start_time = time.time()
        
        try:
            # Parse headers
            headers_dict = json.loads(self.headers) if self.headers else {}
            headers_dict['Content-Type'] = 'application/json'

            # Parse payload — send as JSON body (not form-encoded string)
            try:
                payload_dict = json.loads(self.payload) if self.payload else {}
            except (ValueError, TypeError):
                payload_dict = {}

            # Send request
            response = requests.request(
                method=self.http_method,
                url=self.endpoint_url,
                json=payload_dict,
                headers=headers_dict,
                timeout=30
            )
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Log the request
            IntegrationLog = self.env['integration.bridge.log']
            log = IntegrationLog.create({
                'name': self.name,
                'direction': 'outbound',
                'platform': self.platform,
                'endpoint': self.endpoint_url,
                'status': 'success' if response.ok else 'failed',
                'request_payload': self.payload,
                'response_payload': response.text[:10000],
                'http_status': response.status_code,
                'error_message': '' if response.ok else f"HTTP {response.status_code}",
                'related_model': self.related_model,
                'related_res_id': self.related_res_id,
                'retry_count': self.retry_count,
                'duration_ms': duration_ms,
            })
            
            # Update queue record
            if response.ok:
                self.write({
                    'status': 'sent',
                    'sent_at': fields.Datetime.now(),
                    'response_data': response.text[:10000],
                    'http_status_code': response.status_code,
                    'log_id': log.id,
                })
                _logger.info(f"[Outbound Queue] Message #{self.id} sent successfully")
                return True
            else:
                self.write({
                    'status': 'failed',
                    'error_message': f"HTTP {response.status_code}: {response.text[:500]}",
                    'retry_count': self.retry_count + 1,
                    'next_retry_at': fields.Datetime.now() + timedelta(minutes=5 * (self.retry_count + 1)),
                    'response_data': response.text[:10000],
                    'http_status_code': response.status_code,
                    'log_id': log.id,
                })
                _logger.error(f"[Outbound Queue] Message #{self.id} failed with status {response.status_code}")
                return False
                
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Log the failure
            IntegrationLog = self.env['integration.bridge.log']
            log = IntegrationLog.create({
                'name': self.name,
                'direction': 'outbound',
                'platform': self.platform,
                'endpoint': self.endpoint_url,
                'status': 'failed',
                'request_payload': self.payload,
                'error_message': str(e),
                'related_model': self.related_model,
                'related_res_id': self.related_res_id,
                'retry_count': self.retry_count,
                'duration_ms': duration_ms,
            })
            
            self.write({
                'status': 'failed',
                'error_message': str(e),
                'retry_count': self.retry_count + 1,
                'next_retry_at': fields.Datetime.now() + timedelta(minutes=5 * (self.retry_count + 1)),
                'log_id': log.id,
            })
            
            _logger.error(f"[Outbound Queue] Message #{self.id} failed with exception: {e}")
            return False

    @api.model
    def process_pending_messages(self, limit=50):
        """
        Process pending outbound messages.
        Called by scheduled action (cron).
        
        Args:
            limit: Maximum number of messages to process in one batch
        
        Returns:
            dict with statistics
        """
        now = fields.Datetime.now()
        
        # Get pending messages that are ready to send
        messages = self.search([
            ('status', '=', 'pending'),
            '|',
            ('next_retry_at', '=', False),
            ('next_retry_at', '<=', now),
            ('retry_count', '<', 3),
        ], limit=limit)
        
        if not messages:
            _logger.info("[Outbound Queue] No pending messages to process")
            return {'processed': 0, 'sent': 0, 'failed': 0}
        
        _logger.info(f"[Outbound Queue] Processing {len(messages)} pending messages")
        
        sent_count = 0
        failed_count = 0
        
        for message in messages:
            try:
                if message.send_message():
                    sent_count += 1
                else:
                    failed_count += 1
            except Exception as e:
                _logger.error(f"[Outbound Queue] Error processing message #{message.id}: {e}")
                failed_count += 1
        
        _logger.info(f"[Outbound Queue] Processed {len(messages)} messages: {sent_count} sent, {failed_count} failed")
        
        return {
            'processed': len(messages),
            'sent': sent_count,
            'failed': failed_count
        }

    def action_send_now(self):
        """Action button to send message immediately"""
        for record in self:
            record.send_message()
        return True

    def action_view_log(self):
        """Action button to view integration log"""
        self.ensure_one()
        if not self.log_id:
            return False
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Integration Log',
            'res_model': 'integration.bridge.log',
            'res_id': self.log_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
