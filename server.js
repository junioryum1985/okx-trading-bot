const express = require('express');
const path = require('path');
const STRATEGIES = require('./strategies');
const okx = require('./okx');
okx.setDemo(true); // true = demo (simulated trading), false = live

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const PORT = process.env.PORT || 3000;
const INSTRUMENT = 'BTC-USDT-SWAP';

let bot = null;
let sseClients = [];

function broadcast(data) {
  sseClients.forEach(res => res.write(`data: ${JSON.stringify(data)}\n\n`));
}

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
    const posSide = strat.direction;

    broadcast({ type: 'log', msg: `[${strat.name}] Sinal ${strat.direction.toUpperCase()}! Entry: $${price}, Size: ${sz}` });

    const order = await okx.placeOrder(apiKey, secretKey, passphrase, INSTRUMENT, side, posSide, sz);
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

app.listen(PORT, () => console.log(`Server rodando na porta ${PORT}`));
