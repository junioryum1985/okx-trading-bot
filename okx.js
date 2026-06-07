const crypto = require('crypto');

let DEMO = false;
function setDemo(v) { DEMO = v; }

function signRequest(apiKey, secretKey, passphrase, method, path, body = '') {
  const ts = new Date().toISOString();
  const msg = ts + method + path + body;
  const sig = crypto.createHmac('sha256', secretKey).update(msg).digest('base64');
  const headers = {
    'OK-ACCESS-KEY': apiKey,
    'OK-ACCESS-SIGN': sig,
    'OK-ACCESS-TIMESTAMP': ts,
    'OK-ACCESS-PASSPHRASE': passphrase,
    'Content-Type': 'application/json'
  };
  if (DEMO) headers['x-simulated-trading'] = '1';
  return headers;
}

async function apiCall(apiKey, secretKey, passphrase, method, path, body = undefined) {
  const base = 'https://www.okx.com';
  const url = base + path;
  const headers = signRequest(apiKey, secretKey, passphrase, method, path, body || '');
  const opts = { method, headers };
  if (body) opts.body = body;
  const res = await fetch(url, opts);
  return res.json();
}

async function getCandles(instId, bar, limit = 100) {
  const url = `https://www.okx.com/api/v5/market/history-candles?instId=${instId}&bar=${bar}&limit=${limit}`;
  const res = await fetch(url);
  const json = await res.json();
  if (json.code !== '0') throw new Error(json.msg);
  return json.data.map(c => ({
    ts: parseInt(c[0]), o: parseFloat(c[1]), h: parseFloat(c[2]),
    l: parseFloat(c[3]), c: parseFloat(c[4]), vol: parseFloat(c[5])
  })).sort((a, b) => a.ts - b.ts);
}

async function getBalance(apiKey, secretKey, passphrase) {
  const json = await apiCall(apiKey, secretKey, passphrase, 'GET', '/api/v5/account/balance');
  if (json.code !== '0') throw new Error(json.msg);
  const details = json.data[0].details || [];
  const usdt = details.find(d => d.ccy === 'USDT');
  return usdt ? parseFloat(usdt.eq) : 0;
}

async function placeOrder(apiKey, secretKey, passphrase, instId, side, posSide, sz, tdMode = 'cross') {
  const body = JSON.stringify({ instId, tdMode, side, posSide, ordType: 'market', sz: String(sz) });
  return apiCall(apiKey, secretKey, passphrase, 'POST', '/api/v5/trade/order', body);
}

async function setTPSL(apiKey, secretKey, passphrase, instId, tpPct, slPct, direction, entryPx) {
  const tpPx = direction === 'long'
    ? (entryPx * (1 + tpPct / 100)).toFixed(1)
    : (entryPx * (1 - tpPct / 100)).toFixed(1);
  const slPx = direction === 'long'
    ? (entryPx * (1 - slPct / 100)).toFixed(1)
    : (entryPx * (1 + slPct / 100)).toFixed(1);
  const body = JSON.stringify({
    instId, tdMode: 'cross',
    side: direction === 'long' ? 'sell' : 'buy',
    posSide: direction === 'long' ? 'long' : 'short',
    sz: '0',
    tpTriggerPx: tpPx, tpOrdPx: '-1', tpTriggerPxType: 'last',
    slTriggerPx: slPx, slOrdPx: '-1', slTriggerPxType: 'last'
  });
  return apiCall(apiKey, secretKey, passphrase, 'POST', '/api/v5/trade/order-algo', body);
}

async function closePosition(apiKey, secretKey, passphrase, instId, direction) {
  const side = direction === 'long' ? 'sell' : 'buy';
  const posSide = direction === 'long' ? 'long' : 'short';
  const body = JSON.stringify({ instId, tdMode: 'cross', side, posSide, ordType: 'market', sz: '0' });
  return apiCall(apiKey, secretKey, passphrase, 'POST', '/api/v5/trade/close-position', body);
}

async function getPositions(apiKey, secretKey, passphrase, instId) {
  const json = await apiCall(apiKey, secretKey, passphrase, 'GET', `/api/v5/account/positions?instId=${instId}`);
  if (json.code !== '0') return [];
  return json.data || [];
}

async function getMinSize(instId) {
  const res = await fetch(`https://www.okx.com/api/v5/public/instruments?instType=SWAP&instId=${instId}`);
  const json = await res.json();
  if (json.code !== '0') return 0.001;
  const inst = json.data[0];
  return parseFloat(inst.minSz) || 0.001;
}

module.exports = { getCandles, getBalance, placeOrder, setTPSL, closePosition, getPositions, getMinSize, setDemo };
