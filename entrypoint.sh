#!/bin/sh
# Mounted volume (-v ./data:/app/data) aksar root ka hota hai -> botuser write nahi kar pata
mkdir -p /app/data
chown -R botuser:botuser /app/data 2>/dev/null || true
exec setpriv --reuid=botuser --regid=botuser --init-groups python bot.py
