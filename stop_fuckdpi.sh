#!/bin/bash
# stop_fuckdpi.sh — остановка nfqws + удаление iptables правил.
# Запуск: sudo bash stop_fuckdpi.sh
set -u

PIDFILE="/tmp/fuckdpi-nfqws.pid"
QUEUE_NUM=200

if [[ -f "$PIDFILE" ]]; then
  PID=$(cat "$PIDFILE" 2>/dev/null || true)
  if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null || true
    echo "nfqws остановлен (pid=$PID)"
  else
    echo "nfqws уже не работает"
  fi
  rm -f "$PIDFILE"
else
  killall nfqws 2>/dev/null && echo "nfqws killall" || echo "nfqws не найден"
fi

while IFS= read -r rule; do
  eval "iptables $rule" 2>/dev/null || true
done < <(iptables -t mangle -S OUTPUT 2>/dev/null | \
         grep -- "--queue-num $QUEUE_NUM" | \
         sed 's/^-A/-D/')

echo "iptables правила очищены"
