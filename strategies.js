const crypto = require('crypto');

function ema(data, period) {
  const r = new Array(data.length).fill(0);
  const m = 2 / (period + 1);
  r[0] = data[0];
  for (let i = 1; i < data.length; i++) r[i] = (data[i] - r[i - 1]) * m + r[i - 1];
  return r;
}

function rsi(data, period = 14) {
  const r = new Array(data.length).fill(50);
  if (data.length < period + 1) return r;
  let g = 0, l = 0;
  for (let i = 1; i <= period; i++) {
    const d = data[i] - data[i - 1];
    if (d > 0) g += d; else l -= d;
  }
  let ag = g / period, al = l / period;
  r[period] = 100 - 100 / (1 + (al === 0 ? 100 : ag / al));
  for (let i = period + 1; i < data.length; i++) {
    const d = data[i] - data[i - 1];
    ag = (ag * (period - 1) + (d > 0 ? d : 0)) / period;
    al = (al * (period - 1) + (d < 0 ? -d : 0)) / period;
    r[i] = 100 - 100 / (1 + (al === 0 ? 100 : ag / al));
  }
  return r;
}

function macd(data, fast = 12, slow = 26, sig = 9) {
  const ef = ema(data, fast), es = ema(data, slow);
  const m = new Array(data.length).fill(0);
  for (let i = 0; i < data.length; i++) m[i] = ef[i] - es[i];
  return { macd: m, signal: ema(m, sig) };
}

const STRATEGIES = [
  {
    id: 'MACD_12_26_9_L',
    name: 'MACD 12/26/9 Long',
    timeframe: '15m',
    direction: 'long',
    leverage: 25,
    tp_pct: 1,
    sl_pct: 5,
    check(candles) {
      if (candles.length < 50) return false;
      const closes = candles.map(c => c.c);
      const { macd: m, signal: s } = macd(closes, 12, 26, 9);
      const i = m.length - 1;
      return m[i - 1] <= s[i - 1] && m[i] > s[i];
    }
  },
  {
    id: 'EMA_MACD_L',
    name: 'EMA 9/21 + MACD Long',
    timeframe: '15m',
    direction: 'long',
    leverage: 25,
    tp_pct: 1,
    sl_pct: 5,
    check(candles) {
      if (candles.length < 50) return false;
      const closes = candles.map(c => c.c);
      const e9 = ema(closes, 9), e21 = ema(closes, 21);
      const { macd: m, signal: s } = macd(closes, 12, 26, 9);
      const i = m.length - 1;
      const emaBull = e9[i - 1] <= e21[i - 1] && e9[i] > e21[i];
      const macdBull = m[i - 1] <= s[i - 1] && m[i] > s[i];
      return emaBull || macdBull;
    }
  },
  {
    id: 'EMA_MACD_S',
    name: 'EMA 9/21 + MACD Short',
    timeframe: '1D',
    direction: 'short',
    leverage: 25,
    tp_pct: 3,
    sl_pct: 5,
    check(candles) {
      if (candles.length < 50) return false;
      const closes = candles.map(c => c.c);
      const e9 = ema(closes, 9), e21 = ema(closes, 21);
      const { macd: m, signal: s } = macd(closes, 12, 26, 9);
      const i = m.length - 1;
      const emaBear = e9[i - 1] >= e21[i - 1] && e9[i] < e21[i];
      const macdBear = m[i - 1] >= s[i - 1] && m[i] < s[i];
      return emaBear || macdBear;
    }
  }
];

module.exports = STRATEGIES;
