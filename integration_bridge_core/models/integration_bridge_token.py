# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError
import secrets
import logging

_logger = logging.getLogger(__name__)


class IntegrationBridgeToken(models.Model):
    _name = 'integration.bridge.token'
    _description = 'Integration Bridge Authentication Tokens'
    _order = 'platform, name'
    _rec_name = 'name'

    name = fields.Char(
        string='Token Name',
        required=True,
        help='Descriptive name for this token (e.g., "n8n Production", "Chatwoot Dev")'
    )

    token = fields.Char(
        string='API Token',
        required=True,
        copy=False,
        help='Secret authentication token'
    )

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
       help='Platform this token is for')

    active = fields.Boolean(
        string='Active',
        default=True,
        help='Only active tokens are validated'
    )

    allowed_ips = fields.Char(
        string='Allowed IP Addresses',
        help='Comma-separated list of allowed IP addresses (e.g., 192.168.1.100,10.0.0.50). Leave empty to allow all IPs.'
    )

    description = fields.Text(
        string='Description',
        help='Notes about this token: purpose, owner, environment, etc.'
    )

    last_used = fields.Datetime(
        string='Last Used',
        readonly=True,
        help='Last time this token was successfully used'
    )

    usage_count = fields.Integer(
        string='Usage Count',
        default=0,
        readonly=True,
        help='Number of times this token has been used'
    )

    created_by = fields.Many2one(
        'res.users',
        string='Created By',
        default=lambda self: self.env.user,
        readonly=True
    )

    expires_at = fields.Datetime(
        string='Expires At',
        help='Token expiration date (optional)'
    )

    @api.constrains('token')
    def _check_unique_token(self):
        for record in self:
            if record.token and self.search_count([('token', '=', record.token), ('id', '!=', record.id)]) > 0:
                raise ValidationError('Token must be unique!')

    @api.model
    def generate_token(self):
        """Generate a secure random token"""
        return secrets.token_urlsafe(32)

    def action_generate_token(self):
        """Action button to generate new token"""
        for record in self:
            record.token = self.generate_token()
        return True

    def action_regenerate_token(self):
        """Action button to regenerate token (with confirmation)"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Regenerate Token',
            'res_model': 'integration.bridge.token',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': {'regenerate_token': True}
        }

    @api.model
    def validate_token(self, token, platform=None, remote_ip=None):
        """
        Validate token and return token record if valid.
        
        Args:
            token (str): Token to validate
            platform (str): Expected platform (optional)
            remote_ip (str): Remote IP address for IP whitelisting (optional)
        
        Returns:
            integration.bridge.token record if valid, False otherwise
        """
        if not token:
            return False

        domain = [('token', '=', token), ('active', '=', True)]
        
        if platform:
            domain.append(('platform', '=', platform))
        
        token_record = self.search(domain, limit=1)
        
        if not token_record:
            _logger.warning(f"[Bridge Auth] Invalid token attempt from IP: {remote_ip}")
            return False
        
        # Check expiration
        if token_record.expires_at and token_record.expires_at < fields.Datetime.now():
            _logger.warning(f"[Bridge Auth] Expired token used: {token_record.name}")
            return False
        
        # Check IP whitelist
        if token_record.allowed_ips and remote_ip:
            allowed_ips = [ip.strip() for ip in token_record.allowed_ips.split(',')]
            if remote_ip not in allowed_ips:
                _logger.warning(f"[Bridge Auth] IP {remote_ip} not in whitelist for token: {token_record.name}")
                return False
        
        # Update usage statistics
        token_record.sudo().write({
            'last_used': fields.Datetime.now(),
            'usage_count': token_record.usage_count + 1
        })
        
        _logger.info(f"[Bridge Auth] Valid token used: {token_record.name} ({token_record.platform})")
        return token_record

    @api.constrains('expires_at')
    def _check_expiration_date(self):
        for record in self:
            if record.expires_at and record.expires_at < fields.Datetime.now():
                raise ValidationError('Expiration date cannot be in the past!')
