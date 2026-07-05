# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import json
import logging
import time
from functools import wraps

_logger = logging.getLogger(__name__)


class BridgeControllerBase(http.Controller):
    """
    Base controller class for all bridge integrations.
    Provides common functionality: token validation, request logging, CORS, etc.
    
    All bridge controllers should inherit from this class.
    """

    def _validate_token(self, expected_platform=None):
        """
        Validate X-Bridge-Token header.
        Accepts either: (1) Master token from Settings, or (2) valid Bridge Token from integration.bridge.token.
        
        Returns:
            True if valid, False otherwise, or 'IP_BLOCKED' if IP not whitelisted
        """
        token_header = request.httprequest.headers.get('X-Bridge-Token', '')
        remote_ip = request.httprequest.remote_addr
        
        if not token_header:
            _logger.warning(f"[Bridge Auth] Missing token from IP: {remote_ip}")
            return False
        
        IrConfigParameter = request.env['ir.config_parameter'].sudo()
        master_token = IrConfigParameter.get_param('integration_bridge.master_token', default='')
        
        # 1) Check master token
        if master_token and token_header == master_token:
            _logger.info(f"[Bridge Auth] Valid master token from IP: {remote_ip}")
            return self._check_ip_whitelist(IrConfigParameter, remote_ip)
        
        # 2) Check Bridge Tokens (platform-specific)
        TokenModel = request.env['integration.bridge.token'].sudo()
        token_record = TokenModel.validate_token(token_header, platform=expected_platform, remote_ip=remote_ip)
        if token_record:
            return True
        
        if master_token:
            _logger.warning(f"[Bridge Auth] Invalid token from IP: {remote_ip}")
        else:
            _logger.error("[Bridge Auth] Master token not configured and no valid Bridge Token")
        return False
    
    def _check_ip_whitelist(self, IrConfigParameter, remote_ip):
        
        ip_whitelist = IrConfigParameter.get_param('integration_bridge.ip_whitelist', default='')
        if ip_whitelist:
            allowed_ips = [ip.strip() for ip in ip_whitelist.split(',') if ip.strip()]
            if allowed_ips:
                ip_allowed = False
                for allowed_ip in allowed_ips:
                    if '/' in allowed_ip:
                        if self._ip_in_cidr(remote_ip, allowed_ip):
                            ip_allowed = True
                            break
                    elif remote_ip == allowed_ip:
                        ip_allowed = True
                        break
                if not ip_allowed:
                    _logger.warning(f"[Bridge Auth] IP {remote_ip} not in whitelist")
                    return 'IP_BLOCKED'
        return True
    
    def _ip_in_cidr(self, ip, cidr):
        """
        Check if IP is in CIDR range (basic implementation).
        For production, consider using ipaddress library.
        """
        try:
            import ipaddress
            return ipaddress.ip_address(ip) in ipaddress.ip_network(cidr, strict=False)
        except:
            # Fallback: exact match only
            return ip == cidr.split('/')[0]
    
    def _check_auth(self, json_route=False):
        """
        Check authentication and return appropriate error response if needed.

        Args:
            json_route: If True, return dict instead of Response (for type='json' routes)

        Returns:
            None if authenticated, error dict or Response otherwise
        """
        validation_result = self._validate_token()

        if validation_result == False:
            err = self._error_dict(
                'Unauthorized',
                'Invalid or missing X-Bridge-Token header',
                log_error=False
            ) if json_route else self._error_response(
                'Unauthorized',
                'Invalid or missing X-Bridge-Token header',
                status=401,
                log_error=False
            )
            return err
        elif validation_result == 'IP_BLOCKED':
            err = self._error_dict(
                'Forbidden',
                'Your IP address is not authorized to access this endpoint',
                log_error=False
            ) if json_route else self._error_response(
                'Forbidden',
                'Your IP address is not authorized to access this endpoint',
                status=403,
                log_error=False
            )
            return err

        return None  # Authenticated successfully

    def _get_cors_headers(self):
        """
        Get CORS headers.
        Can be overridden by specific implementations.
        """
        return [
            ('Access-Control-Allow-Origin', '*'),
            ('Access-Control-Allow-Methods', 'POST, GET, OPTIONS'),
            ('Access-Control-Allow-Headers', 'Content-Type, X-Bridge-Token'),
            ('Content-Type', 'application/json'),
        ]

    def _log_request(self, name, direction, platform, endpoint='', external_id='',
                    status='pending', request_payload='', response_payload='',
                    http_status=0, error_message='', related_model='',
                    related_res_id=0, retry_count=0, duration_ms=0):
        """
        Log integration request/response.
        
        Args:
            name: Log entry name
            direction: 'inbound' or 'outbound'
            platform: Platform identifier
            endpoint: API endpoint
            external_id: External reference ID
            status: 'success', 'failed', or 'pending'
            request_payload: Request data (dict or JSON string)
            response_payload: Response data (dict or JSON string)
            http_status: HTTP status code
            error_message: Error message if failed
            related_model: Related Odoo model
            related_res_id: Related record ID
            retry_count: Number of retries
            duration_ms: Request duration in milliseconds
        
        Returns:
            integration.bridge.log record
        """
        if isinstance(request_payload, dict):
            request_payload = json.dumps(request_payload, ensure_ascii=False)
        
        if isinstance(response_payload, dict):
            response_payload = json.dumps(response_payload, ensure_ascii=False)
        
        user_agent = request.httprequest.headers.get('User-Agent', '')
        remote_ip = request.httprequest.remote_addr
        
        IntegrationLog = request.env['integration.bridge.log'].sudo()
        return IntegrationLog.log_integration(
            name=name,
            direction=direction,
            platform=platform,
            endpoint=endpoint,
            external_id=external_id,
            status=status,
            request_payload=request_payload,
            response_payload=response_payload,
            http_status=http_status,
            error_message=error_message,
            related_model=related_model,
            related_res_id=related_res_id,
            retry_count=retry_count,
            duration_ms=duration_ms,
            user_agent=user_agent,
            remote_ip=remote_ip
        )

    def _make_json_response(self, data, status=200, cors=True):
        """
        Create JSON response with optional CORS headers.
        
        Args:
            data: Response data (dict)
            status: HTTP status code
            cors: Include CORS headers (default True)
        
        Returns:
            HTTP response
        """
        if cors:
            return request.make_response(
                json.dumps(data, ensure_ascii=False),
                headers=self._get_cors_headers(),
                status=status
            )
        else:
            return request.make_json_response(data, status=status)

    def _error_response(self, error_msg, details='', status=500, log_error=True):
        """
        Create standardized error response.
        
        Args:
            error_msg: Error message
            details: Additional error details
            status: HTTP status code
            log_error: Whether to log the error
        
        Returns:
            JSON error response
        """
        if log_error:
            _logger.error(f"[Bridge API] Error: {error_msg} - {details}")
        
        return self._make_json_response({
            'success': False,
            'error': error_msg,
            'message': details or error_msg
        }, status=status)

    def _error_dict(self, error_msg, details='', log_error=True):
        """
        Return error as dict (for type='json' routes - must return dict, not Response).
        """
        if log_error:
            _logger.error(f"[Bridge API] Error: {error_msg} - {details}")
        return {
            'success': False,
            'error': error_msg,
            'message': details or error_msg
        }

    def _success_response(self, data, message='Success'):
        """
        Create standardized success response.
        
        Args:
            data: Response data (dict)
            message: Success message
        
        Returns:
            JSON success response
        """
        response = {
            'success': True,
            'message': message
        }
        response.update(data)
        return self._make_json_response(response, status=200)

    def _sanitize_phone(self, phone):
        """
        Sanitize phone number: remove + and @s.whatsapp.net
        
        Args:
            phone: Raw phone number string
        
        Returns:
            Sanitized phone number
        """
        if not phone:
            return ''
        return str(phone).replace('+', '').replace('@s.whatsapp.net', '').strip()

    def _json_response(self, data, status=200):
        """Return a proper HTTP JSON Response (for type='http' routes)."""
        return request.make_response(
            json.dumps(data, ensure_ascii=False, default=str),
            headers=[
                ('Content-Type', 'application/json'),
                ('Access-Control-Allow-Origin', '*'),
            ],
            status=status,
        )

    def _get_json_payload(self, **kwargs):
        """
        Get JSON payload from request.
        Handles:
        - type='http' route: parse raw body as JSON (Evolution, Chatwoot webhooks)
        - type='jsonrpc' route: use request.jsonrequest (Odoo native calls)
        - kwargs fallback (form-encoded or query params)

        Returns:
            dict: Parsed request payload
        """
        # 1) type='http' — raw JSON body (Evolution / Chatwoot webhooks)
        try:
            raw = request.httprequest.get_data(as_text=True)
            if raw:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
        except Exception:
            pass

        # 2) type='jsonrpc' (legacy / Odoo native callers)
        try:
            if hasattr(request, 'jsonrequest') and request.jsonrequest:
                data = request.jsonrequest
                params = data.get('params') if isinstance(data.get('params'), dict) else {}
                if params.get('platform'):
                    return params
                return data
        except Exception:
            pass

        # 3) kwargs fallback
        return kwargs
