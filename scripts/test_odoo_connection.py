#!/usr/bin/env python3
"""Test Odoo JSON-RPC connection using .env credentials."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parents[1] / '.env'


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        env[key.strip()] = value.strip()
    return env


def jsonrpc(url: str, service: str, method: str, args: list) -> object:
    payload = {
        'jsonrpc': '2.0',
        'method': 'call',
        'params': {'service': service, 'method': method, 'args': args},
        'id': 1,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = json.loads(resp.read().decode('utf-8'))
    if body.get('error'):
        raise RuntimeError(body['error'])
    return body.get('result')


def try_auth(base_jsonrpc: str, db: str, user: str, secret: str, label: str) -> dict:
    result = {
        'label': label,
        'url': base_jsonrpc,
        'auth': secret[:4] + '...' if len(secret) > 4 else '***',
        'ok': False,
        'uid': None,
        'company': None,
        'error': None,
    }
    try:
        uid = jsonrpc(base_jsonrpc, 'common', 'authenticate', [db, user, secret, {}])
        if not uid:
            result['error'] = 'authenticate returned false/empty'
            return result
        result['uid'] = uid
        version = jsonrpc(base_jsonrpc, 'common', 'version', [])
        result['version'] = version.get('server_version') if isinstance(version, dict) else version
        # read company name via execute_kw
        company = jsonrpc(
            base_jsonrpc,
            'object',
            'execute_kw',
            [db, uid, secret, 'res.company', 'search_read', [[], ['name']], {'limit': 1}],
        )
        if company:
            result['company'] = company[0].get('name')
        result['ok'] = True
    except (urllib.error.URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
        result['error'] = str(exc)
    return result


def main() -> int:
    env = load_env(ENV_PATH)
    db = env.get('ODOO_DB', 'pet_spot_elsahel')
    user = env.get('ODOO_USERNAME', 'admin')
    api_key = env.get('ODOO_API_KEY', '')
    password = env.get('ODOO_PASSWORD', 'admin')

    targets = [
        ('remote', env.get('ODOO_JSONRPC_URL', '')),
        ('local', env.get('ODOO_LOCAL_JSONRPC_URL', '')),
    ]

    print(f'Loaded .env from: {ENV_PATH}')
    print(f'Database: {db}  User: {user}')
    print()

    any_ok = False
    for name, url in targets:
        if not url:
            continue
        print(f'--- {name.upper()} ({url}) ---')
        for secret_label, secret in [('API key', api_key), ('password', password)]:
            if not secret:
                continue
            res = try_auth(url, db, user, secret, secret_label)
            status = 'OK' if res['ok'] else 'FAIL'
            print(f'  [{status}] auth via {secret_label}: uid={res["uid"]} company={res.get("company")!r} version={res.get("version")}')
            if res['error']:
                print(f'         error: {res["error"]}')
            if res['ok']:
                any_ok = True
        print()

    if any_ok:
        print('Connection test: PASS (at least one endpoint authenticated)')
        return 0
    print('Connection test: FAIL (no endpoint reachable/authenticated)')
    print('Note: remote IP may need port 8027 opened; local fallback uses 127.0.0.1:8027')
    return 1


if __name__ == '__main__':
    sys.exit(main())
