#!/usr/bin/env node
/**
 * Backend entry for petspot.drpaws.ai
 * - GET /  /web  /odoo  /odoo/  → 302 /odoo/action-741 (Appointments)
 * - /websocket* → Odoo gevent :8072
 * - everything else → Odoo HTTP workers :8027
 */
const http = require('http');
const httpProxy = require('/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/.https-proxy/node_modules/http-proxy');

const LISTEN_HOST = process.env.PETSPOT_BACKEND_HOST || '127.0.0.1';
const LISTEN_PORT = Number(process.env.PETSPOT_BACKEND_PORT || 8026);
const TARGET_HTTP = process.env.PETSPOT_ODOO_HTTP || 'http://127.0.0.1:8027';
const TARGET_WS = process.env.PETSPOT_ODOO_WS || 'http://127.0.0.1:8072';
const HOME_PATH = process.env.PETSPOT_HOME_PATH || '/odoo/action-741';
const PUBLIC_HOST = process.env.PETSPOT_PUBLIC_HOST || 'petspot.drpaws.ai';

const proxyHttp = httpProxy.createProxyServer({
  target: TARGET_HTTP,
  ws: false,
  xfwd: true,
  changeOrigin: true,
});
const proxyWs = httpProxy.createProxyServer({
  target: TARGET_WS,
  ws: true,
  xfwd: true,
  changeOrigin: true,
});

function setForwardHeaders(proxyReq, req) {
  proxyReq.setHeader('X-Forwarded-Proto', 'https');
  proxyReq.setHeader('X-Forwarded-Host', req.headers.host || PUBLIC_HOST);
}

proxyHttp.on('proxyReq', setForwardHeaders);
proxyWs.on('proxyReq', setForwardHeaders);
proxyWs.on('proxyReqWs', setForwardHeaders);

function onError(err, req, res) {
  console.error('[petspot-backend]', err.message);
  if (res && !res.headersSent && typeof res.writeHead === 'function') {
    res.writeHead(502, { 'Content-Type': 'text/plain' });
    res.end('Bad gateway');
  }
}
proxyHttp.on('error', onError);
proxyWs.on('error', onError);

function pathname(url) {
  return (url || '/').split('?')[0];
}

function shouldGoHome(path) {
  return path === '/' || path === '/web' || path === '/web/' || path === '/odoo' || path === '/odoo/';
}

function isWebsocketPath(path) {
  return path === '/websocket' || path.startsWith('/websocket/') || path.startsWith('/longpolling');
}

const server = http.createServer((req, res) => {
  const path = pathname(req.url);
  if ((req.method === 'GET' || req.method === 'HEAD') && shouldGoHome(path)) {
    const dest = HOME_PATH;
    res.writeHead(302, {
      Location: dest,
      'Cache-Control': 'no-store',
    });
    res.end();
    return;
  }
  if (isWebsocketPath(path)) {
    proxyWs.web(req, res);
    return;
  }
  proxyHttp.web(req, res);
});

server.on('upgrade', (req, socket, head) => {
  proxyWs.ws(req, socket, head);
});

server.listen(LISTEN_PORT, LISTEN_HOST, () => {
  console.log(
    `[petspot-backend] http://${LISTEN_HOST}:${LISTEN_PORT} → home ${HOME_PATH}, HTTP ${TARGET_HTTP}, WS ${TARGET_WS}`
  );
});
