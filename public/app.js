const evtSource = new EventSource('/api/sse');
const trades = [];
let priceChart = null, tradeChart = null, priceData = [];
const MAX_PRICE_POINTS = 200;

const formatUSD = v => `$${parseFloat(v || 0).toLocaleString('en', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

document.addEventListener('DOMContentLoaded', async () => {
  const [cfgRes, candlesRes] = await Promise.all([
    fetch('/api/config'),
    fetch('/api/candles/recent')
  ]);
  const cfg = await cfgRes.json();
  const candlesJson = await candlesRes.json();
  if (candlesJson.candles) {
    candlesJson.candles.forEach(c => priceData.push({ t: c.ts, p: c.c }));
  }
  const list = document.getElementById('stratList');
  cfg.strategies.forEach(s => {
    const div = document.createElement('div');
    div.className = 'strat-item';
    div.id = `strat-${s.id}`;
    div.innerHTML = `
      <div class="strat-header">
        <span class="strat-name">${s.name}</span>
        <span class="strat-badge ${s.direction}">${s.direction}</span>
        <span class="strat-status" id="status-${s.id}">⏳ aguardando</span>
      </div>
      <div class="strat-details">${s.timeframe} | ${s.leverage}x | TP ${s.tp_pct}% | SL ${s.sl_pct}%</div>
      <div class="strat-pos">
        <span class="label">Entry:</span> <span id="entry-${s.id}">-</span>
        <span class="label">PNL:</span> <span id="pnl-${s.id}">-</span>
      </div>`;
    list.appendChild(div);
  });
  updatePriceChart();
});

async function startBot() {
  const body = {
    apiKey: document.getElementById('apiKey').value.trim(),
    secretKey: document.getElementById('secretKey').value.trim(),
    passphrase: document.getElementById('passphrase').value.trim(),
    amount: parseFloat(document.getElementById('amount').value)
  };
  if (!body.apiKey || !body.secretKey || !body.passphrase || !body.amount)
    return addLog('Preencha todos os campos');

  const res = await fetch('/api/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const json = await res.json();
  if (json.success) {
    document.getElementById('btnStart').style.display = 'none';
    document.getElementById('btnStop').style.display = 'inline-block';
    document.getElementById('status-indicator').textContent = 'RODANDO';
    document.getElementById('status-indicator').className = 'running';
    fetchBalance();
  } else {
    addLog(`Erro: ${json.error}`);
  }
}

async function stopBot() {
  const res = await fetch('/api/stop', { method: 'POST' });
  const json = await res.json();
  if (json.success) {
    document.getElementById('btnStart').style.display = 'inline-block';
    document.getElementById('btnStop').style.display = 'none';
    document.getElementById('status-indicator').textContent = 'PARADO';
    document.getElementById('status-indicator').className = 'stopped';
  }
}

async function fetchBalance() {
  try {
    const res = await fetch('/api/balance');
    const json = await res.json();
    if (json.balance != null) updateBalanceUI(json.balance);
  } catch (_) {}
}

function addLog(msg) {
  const container = document.getElementById('logContainer');
  const d = new Date();
  const el = document.createElement('div');
  el.className = 'log-entry';
  el.innerHTML = `<span class="log-time">[${d.toLocaleTimeString()}]</span> ${msg}`;
  container.appendChild(el);
  container.scrollTop = container.scrollHeight;
}

function updatePriceChart() {
  if (!priceData.length) return;
  const ctx = document.getElementById('priceChart').getContext('2d');
  if (!priceChart) {
    priceChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: [],
        datasets: [{
          label: 'BTC/USDT',
          data: [],
          borderColor: '#f7931a',
          borderWidth: 2,
          pointRadius: 0,
          fill: true,
          backgroundColor: 'rgba(247,147,26,0.1)'
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        animation: { duration: 300 },
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => `$${ctx.parsed.y.toFixed(1)}` } } },
        scales: {
          x: { ticks: { color: '#8b949e', maxTicksLimit: 10, maxRotation: 0 } },
          y: { ticks: { color: '#8b949e', callback: v => '$' + v.toLocaleString() } }
        }
      }
    });
  }
  const slice = priceData.slice(-MAX_PRICE_POINTS);
  priceChart.data.labels = slice.map(d => { const t = new Date(d.t); return `${t.getHours()}:${String(t.getMinutes()).padStart(2,'0')}`; });
  priceChart.data.datasets[0].data = slice.map(d => d.p);
  priceChart.update('none');
}

function updateBalanceUI(bal) {
  let el = document.getElementById('balanceDisplay');
  if (!el) {
    el = document.createElement('div');
    el.id = 'balanceDisplay';
    el.className = 'balance-display';
    document.querySelector('.config-card').insertBefore(el, document.getElementById('btnStart'));
  }
  el.innerHTML = `<strong>Saldo Total:</strong> ${formatUSD(bal)}`;
}

evtSource.onmessage = (e) => {
  try {
    const data = JSON.parse(e.data);
    switch (data.type) {
      case 'log':
        addLog(data.msg);
        break;
      case 'balance':
        updateBalanceUI(data.balance);
        break;
      case 'price':
        priceData.push({ t: data.ts, p: data.price });
        updatePriceChart();
        break;
      case 'signal':
        document.getElementById(`status-${data.strategy}`).textContent = data.signal ? '🔵 SINAL' : '⏳ aguardando';
        break;
      case 'position':
        document.getElementById(`status-${data.strategy}`).textContent = '📌 EM POSIÇÃO';
        document.getElementById(`entry-${data.strategy}`).textContent = formatUSD(data.entryPx);
        const pnlEl = document.getElementById(`pnl-${data.strategy}`);
        pnlEl.textContent = `${data.pnlPct ? data.pnlPct.toFixed(2) : '0.00'}%`;
        pnlEl.className = data.pnlPct >= 0 ? 'value positive' : 'value negative';
        break;
      case 'trade':
        trades.push(data);
        updateTradeChart();
        addLog(`[${data.strategy}] Trade ${data.side.toUpperCase()} | Entry: ${formatUSD(data.entryPx)}`);
        break;
    }
  } catch (e) { /* ignore */ }
};

function updateTradeChart() {
  const colors = { 'MACD 12/26/9 Long': '#2979ff', 'EMA 9/21 + MACD Long': '#00c853', 'EMA 9/21 + MACD Short': '#ff1744' };
  if (!tradeChart) {
    tradeChart = new Chart(document.getElementById('tradeChart').getContext('2d'), {
      type: 'scatter',
      data: { datasets: Object.keys(colors).map(name => ({ label: name, data: [], backgroundColor: colors[name], pointRadius: 6 })) },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: 'top', labels: { color: '#aaa' } }, tooltip: { callbacks: { label: ctx => `$${ctx.raw.y.toFixed(2)}` } } },
        scales: { x: { type: 'time', time: { unit: 'day' }, ticks: { color: '#8b949e' } }, y: { ticks: { color: '#8b949e' } } }
      }
    });
  }
  trades.forEach(t => {
    const dsIdx = Object.keys(colors).indexOf(t.strategy);
    if (dsIdx >= 0 && !tradeChart.data.datasets[dsIdx].data.some(d => d.x === t.ts))
      tradeChart.data.datasets[dsIdx].data.push({ x: t.ts, y: t.entryPx });
  });
  tradeChart.update('none');
}
