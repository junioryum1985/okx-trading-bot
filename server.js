const express = require('express');
const path = require('path');
const STRATEGIES = require('./strategies');
const okx = require('./okx');

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

async function botLoop() {
  if (!bot || !bot.running) return;
  const { apiKey, secretKey, passphrase, strategy, amount } = bot;

  try {
    const candles = await okx.getCandles(INSTRUMENT, strategy.timeframe, 100);
    const price = candles[candles.length - 1].c;

    const positions = await okx.getPositions(apiKey, secretKey, passphrase, INSTRUMENT);
    const openPos = positions.find(p => parseFloat(p.pos) !== 0);

    if (openPos && openPos.posSide === strategy.direction.toUpperCase()) {
      const entryPx = parseFloat(openPos.avgPx);
      const pnl = parseFloat(openPos.upl);
      const pnlPct = ((price - entryPx) / entryPx) * strategy.leverage * 100 * (strategy.direction === 'long' ? 1 : -1);
      broadcast({ type: 'position', side: strategy.direction, entryPx, pnl, pnlPct, price, ts: Date.now() });
      bot.lastPrice = price;
      setTimeout(botLoop, 60000);
      return;
    }

    if (openPos && openPos.posSide !== strategy.direction.toUpperCase()) {
      await okx.closePosition(apiKey, secretKey, passphrase, INSTRUMENT, openPos.posSide.toLowerCase());
      broadcast({ type: 'log', msg: `Posição ${openPos.posSide} fechada para inverter` });
      await new Promise(r => setTimeout(r, 2000));
    }

    if (!openPos || parseFloat(openPos.pos) === 0) {
      const signal = strategy.check(candles);
      broadcast({ type: 'signal', signal, price, ts: Date.now() });

      if (signal) {
        const minSz = await okx.getMinSize(INSTRUMENT);
        const sz = Math.max(minSz, parseFloat((amount / price).toFixed(3)));
        const side = strategy.direction === 'long' ? 'buy' : 'sell';
        const posSide = strategy.direction;

        broadcast({ type: 'log', msg: `Sinal ${strategy.direction.toUpperCase()} detectado! Entry: $${price}, Size: ${sz}` });

        const order = await okx.placeOrder(apiKey, secretKey, passphrase, INSTRUMENT, side, posSide, sz);
        if (order.code === '0') {
          broadcast({ type: 'log', msg: `Ordem executada: ${order.data[0].ordId}` });
          await new Promise(r => setTimeout(r, 1000));
          const tpSl = await okx.setTPSL(apiKey, secretKey, passphrase, INSTRUMENT, strategy.tp_pct, strategy.sl_pct, strategy.direction, price);
          broadcast({ type: 'log', msg: `TP ${strategy.tp_pct}% / SL ${strategy.sl_pct}% configurados` });
          broadcast({
            type: 'trade', side: strategy.direction, entryPx: price, sz,
            tpPx: strategy.direction === 'long' ? price * (1 + strategy.tp_pct / 100) : price * (1 - strategy.tp_pct / 100),
            slPx: strategy.direction === 'long' ? price * (1 - strategy.sl_pct / 100) : price * (1 + strategy.sl_pct / 100),
            ts: Date.now()
          });
        } else {
          broadcast({ type: 'log', msg: `Erro ordem: ${order.msg || order.code}` });
        }
      }
    }
  } catch (e) {
    broadcast({ type: 'log', msg: `Erro: ${e.message}` });
  }

  bot.lastPrice = bot.lastPrice || 0;
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
  const { apiKey, secretKey, passphrase, strategyId, amount } = req.body;
  if (!apiKey || !secretKey || !passphrase || !strategyId || !amount) {
    return res.json({ success: false, error: 'Preencha todos os campos' });
  }

  if (bot && bot.running) {
    return res.json({ success: false, error: 'Bot já está rodando' });
  }

  const strategy = STRATEGIES.find(s => s.id === strategyId);
  if (!strategy) return res.json({ success: false, error: 'Estratégia inválida' });

  bot = { apiKey, secretKey, passphrase, strategy, amount: parseFloat(amount), running: true, lastPrice: 0 };
  broadcast({ type: 'log', msg: `Bot iniciado - ${strategy.name} | ${strategy.timeframe} | ${strategy.leverage}x | TP ${strategy.tp_pct}% SL ${strategy.sl_pct}%` });
  setTimeout(botLoop, 1000);
  res.json({ success: true });
});

app.post('/api/stop', (req, res) => {
  if (bot) bot.running = false;
  broadcast({ type: 'log', msg: 'Bot parado' });
  res.json({ success: true });
});

app.get('/api/status', (req, res) => {
  res.json({ running: bot ? bot.running : false, strategy: bot ? bot.strategy?.id : null });
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
