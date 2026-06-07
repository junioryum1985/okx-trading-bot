const evtSource = new EventSource('/api/sse');
const trades = [];
let equityData = [];
let priceData = [];

let priceChart = null, equityChart = null;

const formatUSD = v => `$${parseFloat(v || 0).toLocaleString('en', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

document.addEventListener('DOMContentLoaded', async () => {
  const res = await fetch('/api/config');
  const cfg = await res.json();
  const sel = document.getElementById('strategy');
  cfg.strategies.forEach(s => {
    const opt = document.createElement('option');
    opt.value = s.id;
    opt.textContent = `${s.name} | ${s.timeframe} | ${s.direction} | ${s.leverage}x | TP ${s.tp_pct}% SL ${s.sl_pct}%`;
    sel.appendChild(opt);
  });
  sel.onchange = updateStrategyInfo;
  updateStrategyInfo();
});

function updateStrategyInfo() {
  const sel = document.getElementById('strategy');
  const text = sel.selectedOptions[0].text;
  const parts = text.split(' | ');
  document.getElementById('leverageDisplay').value = parts[3] || '-';
  document.getElementById('tpslDisplay').value = `TP ${parts[4]} | ${parts[5]}`;
}

async function startBot() {
  const body = {
    apiKey: document.getElementById('apiKey').value.trim(),
    secretKey: document.getElementById('secretKey').value.trim(),
    passphrase: document.getElementById('passphrase').value.trim(),
    strategyId: document.getElementById('strategy').value,
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
  const time = d.toLocaleTimeString();
  const el = document.createElement('div');
  el.className = 'log-entry';
  el.innerHTML = `<span class="log-time">[${time}]</span> ${msg}`;
  container.appendChild(el);
  container.scrollTop = container.scrollHeight;
}

evtSource.onmessage = (e) => {
  try {
    const data = JSON.parse(e.data);
    switch (data.type) {
      case 'log':
        addLog(data.msg);
        break;
      case 'signal':
        document.getElementById('lastSignal').textContent = data.signal ? 'COMPRAR' : 'AGUARDANDO';
        document.getElementById('lastSignal').className = data.signal ? 'value signal-on' : 'value signal-off';
        break;
      case 'position':
        document.getElementById('posSide').textContent = data.side?.toUpperCase() || '-';
        document.getElementById('posEntry').textContent = data.entryPx ? formatUSD(data.entryPx) : '-';
        document.getElementById('posPrice').textContent = formatUSD(data.price);
        document.getElementById('posPnl').textContent = data.pnl ? formatUSD(data.pnl) : '-';
        document.getElementById('posPnlPct').textContent = data.pnlPct ? `${data.pnlPct.toFixed(2)}%` : '-';
        priceData.push({ t: data.ts, p: data.price });
        updatePriceChart();
        break;
      case 'trade':
        trades.push(data);
        updateEquityChart();
        addLog(`Trade ${data.side.toUpperCase()} | Entry: ${formatUSD(data.entryPx)} | Size: ${data.sz} | TP: ${formatUSD(data.tpPx)} | SL: ${formatUSD(data.slPx)}`);
        break;
    }
  } catch (e) { /* ignore parse errors */ }
};

function updatePriceChart() {
  if (!priceChart) {
    const ctx = document.getElementById('priceChart').getContext('2d');
    priceChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: [],
        datasets: [{
          label: 'Preço BTC',
          data: [],
          borderColor: '#f7931a',
          borderWidth: 1.5,
          pointRadius: 0,
          fill: false
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { display: true, ticks: { maxTicksLimit: 10 } },
          y: { display: true }
        }
      }
    });
  }
  const slice = priceData.slice(-200);
  priceChart.data.labels = slice.map(d => new Date(d.t).toLocaleTimeString());
  priceChart.data.datasets[0].data = slice.map(d => d.p);
  priceChart.update('none');
}

function updateEquityChart() {
  if (!equityChart) {
    const ctx = document.getElementById('equityChart').getContext('2d');
    equityChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          { label: 'Equity', data: [], borderColor: '#00c853', borderWidth: 2, pointRadius: 3, fill: false },
          { label: 'Entry', data: [], borderColor: '#2979ff', borderWidth: 1, pointRadius: 5, pointStyle: 'triangle', fill: false },
          { label: 'TP', data: [], borderColor: '#00e676', borderWidth: 1, pointRadius: 5, pointStyle: 'triangle', fill: false },
          { label: 'SL', data: [], borderColor: '#ff1744', borderWidth: 1, pointRadius: 5, pointStyle: 'triangle-down', fill: false }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: 'top', labels: { color: '#aaa' } } },
        scales: {
          x: { display: true, ticks: { maxTicksLimit: 10 } },
          y: { display: true }
        }
      }
    });
  }
  let equity = 1000;
  equityData = [{ t: trades.length ? trades[0].ts : Date.now(), eq: equity }];
  const labels = [], eqVals = [], entryVals = [], tpVals = [], slVals = [];
  trades.forEach((t, i) => {
    const pnl = (t.side === 'long' ? 1 : -1) * 100; // simulated PnL
    equity += pnl;
    const label = new Date(t.ts).toLocaleDateString();
    labels.push(label);
    eqVals.push(equity);
    entryVals.push(t.entryPx / 100);
    tpVals.push(t.tpPx / 100);
    slVals.push(t.slPx / 100);
    equityData.push({ t: t.ts, eq: equity });
  });
  equityChart.data.labels = labels;
  equityChart.data.datasets[0].data = eqVals;
  equityChart.data.datasets[1].data = entryVals;
  equityChart.data.datasets[2].data = tpVals;
  equityChart.data.datasets[3].data = slVals;
  equityChart.update('none');
}
