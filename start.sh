#!/bin/bash
set -e

echo "=== Iniciando BTC Live Trading Bot ==="
echo "Port: $PORT"
echo "Python: $(python3 --version)"

exec python3 live_bot.py
