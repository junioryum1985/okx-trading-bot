const express = require('express');
const path = require('path');
const fs = require('fs');
const STRATEGIES = require('./strategies');
const okx = require('./okx');
okx.setDemo(true); // true = demo (simulated trading), false = live

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const PORT = process.env.PORT || 3000;
const INSTRUMENT = 'BTC-USDT-SWAP';
const CONFIG_FILE = path.join(__dirname, 'saved_config.json');

let bot = null;
let sseClients = [];

function loadSavedConfig() {
  try {
    if (fs.existsSync(CONFIG_FILE)) {
      return JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf-8'));
    }
  } catch (e) { /* ignore */ }
  return null;
}

function saveConfig(data) {
  try {
    fs.writeFileSync(CONFIG_FILE, JSON.stringify(data, null, 2));
  } catch (e) { /* ignore */ }
}

function broadcast(data) {
  sseClients.forEach(res => res.write(`data: ${JSON.stringify(data)}\n\n`));
}

const origLog = console.log;
console.log = function (...args) {
  origLog.apply(console, args);
  const msg = args.map(a => typeof a === 'object' ? JSON.stringify(a) : String(a)).join(' ');
  broadcast({ type: 'log', msg: `[SERVER] ${msg}` });
};

async function broadcastBalance(apiKey, secretKey, passphrase) {
  try {
    const bal = await okx.getBalance(apiKey, secretKey, passphrase);
    broadcast({ type: 'balance', balance: bal });
  } catch (e) {
    broadcast({ type: 'log', msg: `Erro ao consultar saldo: ${e.message}` });
  }
}

async function processStrategy(apiKey, secretKey, passphrase, strat, state, amount) {
  const candles = await okx.getCandles(INSTRUMENT, strat.timeframe, 100);
  const price = candles[candles.length - 1].c;
  const allPositions = await okx.getPositions(apiKey, secretKey, passphrase, INSTRUMENT);
  const openPos = allPositions.find(p =>
    parseFloat(p.pos) !== 0 && p.posSide === strat.direction.toUpperCase()
  );

  state.price = price;
  broadcast({ type: 'price', price, ts: Date.now() });

  if (openPos) {
    state.hasPosition = true;
    state.entryPx = parseFloat(openPos.avgPx);
    state.pnl = parseFloat(openPos.upl);
    state.pnlPct = ((price - state.entryPx) / state.entryPx) * strat.leverage * 100 * (strat.direction === 'long' ? 1 : -1);
    broadcast({ type: 'position', strategy: strat.id, side: strat.direction, entryPx: state.entryPx, pnl: state.pnl, pnlPct: state.pnlPct, price, ts: Date.now() });
    return;
  }

  state.hasPosition = false;
  const signal = strat.check(candles);
  broadcast({ type: 'signal', strategy: strat.id, signal, price, ts: Date.now() });

  if (signal) {
    const minSz = await okx.getMinSize(INSTRUMENT);
    const sz = Math.max(minSz, parseFloat((amount / price).toFixed(3)));
    const side = strat.direction === 'long' ? 'buy' : 'sell';

    broadcast({ type: 'log', msg: `[${strat.name}] Sinal ${strat.direction.toUpperCase()}! Entry: $${price}, Size: ${sz}` });

    const order = await okx.placeOrder(apiKey, secretKey, passphrase, INSTRUMENT, side, sz);
    if (order.code === '0') {
      broadcast({ type: 'log', msg: `[${strat.name}] Ordem OK: ${order.data[0].ordId}` });
      await new Promise(r => setTimeout(r, 1000));
      await okx.setTPSL(apiKey, secretKey, passphrase, INSTRUMENT, strat.tp_pct, strat.sl_pct, strat.direction, price);
      broadcast({ type: 'log', msg: `[${strat.name}] TP ${strat.tp_pct}% / SL ${strat.sl_pct}% configurado` });
      broadcast({
        type: 'trade', strategy: strat.id, side: strat.direction, entryPx: price, sz,
        tpPx: strat.direction === 'long' ? price * (1 + strat.tp_pct / 100) : price * (1 - strat.tp_pct / 100),
        slPx: strat.direction === 'long' ? price * (1 - strat.sl_pct / 100) : price * (1 + strat.sl_pct / 100),
        ts: Date.now()
      });
    } else {
      broadcast({ type: 'log', msg: `[${strat.name}] Erro ordem: ${order.msg || order.code}` });
    }
  }
}

async function botLoop() {
  if (!bot || !bot.running) return;
  const { apiKey, secretKey, passphrase, states, amount } = bot;
  const perStrategy = amount / STRATEGIES.length;

  await broadcastBalance(apiKey, secretKey, passphrase);

  await Promise.all(STRATEGIES.map(s =>
    processStrategy(apiKey, secretKey, passphrase, s, states[s.id], perStrategy).catch(e =>
      broadcast({ type: 'log', msg: `[${s.name}] Erro: ${e.message}` })
    )
  ));

  setTimeout(botLoop, 60000);
}

app.get('/api/saved-config', (req, res) => {
  const saved = loadSavedConfig();
  if (saved && saved.apiKey) {
    res.json({ hasConfig: true, apiKey: saved.apiKey, secretKey: saved.secretKey, passphrase: saved.passphrase, amount: saved.amount });
  } else {
    res.json({ hasConfig: false });
  }
});

app.post('/api/save-config', (req, res) => {
  const { apiKey, secretKey, passphrase, amount } = req.body;
  saveConfig({ apiKey, secretKey, passphrase, amount: parseFloat(amount) });
  res.json({ success: true });
});

app.get('/api/config', (req, res) => {
  res.json({ instrument: INSTRUMENT, strategies: STRATEGIES.map(s => ({
    id: s.id, name: s.name, timeframe: s.timeframe,
    direction: s.direction, leverage: s.leverage,
    tp_pct: s.tp_pct, sl_pct: s.sl_pct
  })) });
});

app.post('/api/start', async (req, res) => {
  const { apiKey, secretKey, passphrase, amount } = req.body;
  if (!apiKey || !secretKey || !passphrase || !amount) {
    return res.json({ success: false, error: 'Preencha todos os campos' });
  }
  if (bot && bot.running) {
    return res.json({ success: false, error: 'Bot já está rodando' });
  }

  saveConfig({ apiKey, secretKey, passphrase, amount: parseFloat(amount) });

  const states = {};
  STRATEGIES.forEach(s => { states[s.id] = { hasPosition: false, entryPx: 0, pnl: 0, pnlPct: 0, price: 0 }; });

  bot = { apiKey, secretKey, passphrase, amount: parseFloat(amount), running: true, states };
  const names = STRATEGIES.map(s => `${s.name} (${s.timeframe})`).join(', ');
  broadcast({ type: 'log', msg: `Bot iniciado - ${STRATEGIES.length} estratégias: ${names}` });
  broadcast({ type: 'log', msg: `Valor total: $${amount} ($${(amount / STRATEGIES.length).toFixed(2)} por estratégia)` });
  await broadcastBalance(apiKey, secretKey, passphrase);
  setTimeout(botLoop, 1000);
  res.json({ success: true });
});

app.post('/api/stop', (req, res) => {
  if (bot) bot.running = false;
  broadcast({ type: 'log', msg: 'Bot parado' });
  res.json({ success: true });
});

app.get('/api/balance', async (req, res) => {
  if (!bot) return res.json({ balance: null });
  try {
    const bal = await okx.getBalance(bot.apiKey, bot.secretKey, bot.passphrase);
    res.json({ balance: bal });
  } catch (e) {
    res.json({ balance: null, error: e.message });
  }
});

app.get('/api/candles/recent', async (req, res) => {
  try {
    const candles = await okx.getCandles('BTC-USDT-SWAP', '15m', 100);
    res.json({ candles });
  } catch (e) {
    res.json({ candles: [], error: e.message });
  }
});

app.post('/api/test-trade', async (req, res) => {
  if (!bot) return res.json({ success: false, error: 'Bot não iniciado' });
  const { apiKey, secretKey, passphrase } = bot;
  const results = [];
  try {
    const priceReq = await fetch('https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT-SWAP');
    const priceJson = await priceReq.json();
    const price = parseFloat(priceJson.data[0].last);
    const minSz = await okx.getMinSize('BTC-USDT-SWAP');
    const sz = Math.max(minSz, 0.001);

    const long = await okx.placeOrder(apiKey, secretKey, passphrase, 'BTC-USDT-SWAP', 'buy', sz);
    results.push({ side: 'long', order: long });
    broadcast({ type: 'log', msg: `[TESTE] Long order: ${long.code === '0' ? 'OK ' + long.data[0].ordId : 'FALHA ' + (long.msg || long.code)}` });

    await new Promise(r => setTimeout(r, 2000));

    const short = await okx.placeOrder(apiKey, secretKey, passphrase, 'BTC-USDT-SWAP', 'sell', sz);
    results.push({ side: 'short', order: short });
    broadcast({ type: 'log', msg: `[TESTE] Short order: ${short.code === '0' ? 'OK ' + short.data[0].ordId : 'FALHA ' + (short.msg || short.code)}` });

    await new Promise(r => setTimeout(r, 2000));

    if (long.code === '0') {
      await okx.setTPSL(apiKey, secretKey, passphrase, 'BTC-USDT-SWAP', 0.5, 1, 'long', price);
      broadcast({ type: 'log', msg: '[TESTE] TP/SL Long configurado' });
    }
    if (short.code === '0') {
      await okx.setTPSL(apiKey, secretKey, passphrase, 'BTC-USDT-SWAP', 0.5, 1, 'short', price);
      broadcast({ type: 'log', msg: '[TESTE] TP/SL Short configurado' });
    }

    broadcast({ type: 'log', msg: '[TESTE] Teste concluído' });
    res.json({ success: true, results });
  } catch (e) {
    res.json({ success: false, error: e.message });
  }
});

app.post('/api/cleanup', async (req, res) => {
  if (!bot) return res.json({ success: false, error: 'Bot não iniciado' });
  const { apiKey, secretKey, passphrase } = bot;
  try {
    const positions = await okx.getPositions(apiKey, secretKey, passphrase, 'BTC-USDT-SWAP');
    const results = [];
    for (const p of positions) {
      if (parseFloat(p.pos) !== 0) {
        const dir = p.posSide === 'long' ? 'long' : 'short';
        const side = dir === 'long' ? 'sell' : 'buy';
        await okx.closePosition(apiKey, secretKey, passphrase, 'BTC-USDT-SWAP', dir);
        results.push({ side: dir, pos: p.pos });
        broadcast({ type: 'log', msg: `[CLEANUP] Posição ${dir} de ${p.pos} fechada` });
      }
    }
    broadcast({ type: 'log', msg: `[CLEANUP] ${results.length} posição(ões) fechada(s)` });
    res.json({ success: true, closed: results });
  } catch (e) {
    broadcast({ type: 'log', msg: `[CLEANUP] Erro: ${e.message}` });
    res.json({ success: false, error: e.message });
  }
});

app.get('/api/status', (req, res) => {
  res.json({ running: bot ? bot.running : false, states: bot ? bot.states : {} });
});

app.get('/api/sse', (req, res) => {
  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    Connection: 'keep-alive'
  });
  sseClients.push(res);
  req.on('close', () => {
    sseClients = sseClients.filter(c => c !== res);
  });
});

app.listen(PORT, () => {
  console.log(`Server rodando na porta ${PORT}`);
  const saved = loadSavedConfig();
  if (saved && saved.apiKey) {
    console.log('Config salva encontrada — iniciando bot automaticamente...');
    const states = {};
    STRATEGIES.forEach(s => { states[s.id] = { hasPosition: false, entryPx: 0, pnl: 0, pnlPct: 0, price: 0 }; });
    bot = { apiKey: saved.apiKey, secretKey: saved.secretKey, passphrase: saved.passphrase, amount: saved.amount, running: true, states };
    broadcast({ type: 'log', msg: `Bot iniciado automaticamente - ${STRATEGIES.length} estratégias` });
    setTimeout(botLoop, 1000);
  }
});
