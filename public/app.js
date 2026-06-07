const evtSource = new EventSource('/api/sse');
const trades = [];
let priceData = [];
let priceChart = null, tradeChart = null;

const formatUSD = v => `$${parseFloat(v || 0).toLocaleString('en', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

document.addEventListener('DOMContentLoaded', async () => {
  const res = await fetch('/api/config');
  const cfg = await res.json();
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

function addLog(msg) {
  const container = document.getElementById('logContainer');
  const d = new Date();
  const el = document.createElement('div');
  el.className = 'log-entry';
  el.innerHTML = `<span class="log-time">[${d.toLocaleTimeString()}]</span> ${msg}`;
  container.appendChild(el);
  container.scrollTop = container.scrollHeight;
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
      case 'signal':
        document.getElementById(`status-${data.strategy}`).textContent = data.signal ? '🔵 SINAL' : '⏳ aguardando';
        break;
      case 'position':
        document.getElementById(`status-${data.strategy}`).textContent = '📌 EM POSIÇÃO';
        document.getElementById(`entry-${data.strategy}`).textContent = formatUSD(data.entryPx);
        const pnlEl = document.getElementById(`pnl-${data.strategy}`);
        pnlEl.textContent = `${data.pnlPct ? data.pnlPct.toFixed(2) : '0.00'}%`;
        pnlEl.className = data.pnlPct >= 0 ? 'value positive' : 'value negative';
        priceData.push({ t: data.ts, p: data.price });
        updatePriceChart();
        break;
      case 'trade':
        trades.push(data);
        updateTradeChart();
        addLog(`[${data.strategy}] Trade ${data.side.toUpperCase()} | Entry: ${formatUSD(data.entryPx)}`);
        break;
    }
  } catch (e) { /* ignore */ }
};

function updatePriceChart() {
  if (!priceChart) {
    priceChart = new Chart(document.getElementById('priceChart').getContext('2d'), {
      type: 'line',
      data: { labels: [], datasets: [{ label: 'BTC', data: [], borderColor: '#f7931a', borderWidth: 1.5, pointRadius: 0, fill: false }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { ticks: { maxTicksLimit: 10 } } } }
    });
  }
  const slice = priceData.slice(-200);
  priceChart.data.labels = slice.map(d => new Date(d.t).toLocaleTimeString());
  priceChart.data.datasets[0].data = slice.map(d => d.p);
  priceChart.update('none');
}

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
