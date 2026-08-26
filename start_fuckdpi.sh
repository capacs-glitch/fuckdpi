#!/bin/bash
# start_fuckdpi.sh — запуск nfqws для обхода DPI.
# Аргумент: "select" (только список доменов) или "all" (весь трафик).
# Запуск: sudo bash start_fuckdpi.sh select
set -euo pipefail

MODE="${1:-all}"
CFG_DIR="$HOME/.config/fuckdpi"
HOSTLIST="$CFG_DIR/hostlist.txt"
PIDFILE="/tmp/fuckdpi-nfqws.pid"
QUEUE_NUM=200
FWMARK=0x40000000

NFQWS=""
  for p in /opt/zapret/nfq/nfqws /opt/fuckdpi/nfq/nfqws /usr/local/bin/nfqws /usr/bin/nfqws; do
  if [[ -x "$p" ]]; then NFQWS="$p"; break; fi
done
if [[ -z "$NFQWS" ]]; then
  echo "nfqws не найден. Установи: fuckdpi"
  exit 1
fi

if [[ -f "$PIDFILE" ]]; then
  OLD=$(cat "$PIDFILE" 2>/dev/null || true)
  if [[ -n "$OLD" ]] && kill -0 "$OLD" 2>/dev/null; then
    kill "$OLD" 2>/dev/null || true
    sleep 0.5
  fi
  rm -f "$PIDFILE"
fi

HOSTLIST_ARG=""
if [[ "$MODE" == "select" ]]; then
  if [[ -s "$HOSTLIST" ]]; then
    HOSTLIST_ARG="--hostlist=$HOSTLIST"
  else
    echo "список доменов пуст: $HOSTLIST"
    exit 1
  fi
fi

$NFQWS \
  --daemon \
  --pidfile="$PIDFILE" \
  --qnum="$QUEUE_NUM" \
  --filter-tcp=80 \
  --dpi-desync=fake,multisplit \
  --dpi-desync-split-pos=method+2 \
  --dpi-desync-fooling=md5sig \
  --dpi-desync-fwmark="$FWMARK" \
  $HOSTLIST_ARG \
  --new \
  --filter-tcp=443 \
  --dpi-desync=fake,multidisorder \
  --dpi-desync-split-pos=1,midsld \
  --dpi-desync-fooling=badseq,md5sig \
  --dpi-desync-fwmark="$FWMARK" \
  $HOSTLIST_ARG \
  --new \
  --filter-udp=443 \
  --dpi-desync=fake \
  --dpi-desync-repeats=6 \
  --dpi-desync-fwmark="$FWMARK" \
  $HOSTLIST_ARG

sleep 0.5

if ! iptables -t mangle -C OUTPUT -p tcp -m multiport --dports 80,443 \
     -m connbytes --connbytes-dir=original --connbytes-mode=packets \
     --connbytes 1:6 \
     -m mark ! --mark "$FWMARK/$FWMARK" \
     -j NFQUEUE --queue-num "$QUEUE_NUM" --queue-bypass 2>/dev/null; then
  iptables -t mangle -I OUTPUT 1 -p tcp -m multiport --dports 80,443 \
    -m connbytes --connbytes-dir=original --connbytes-mode=packets \
    --connbytes 1:6 \
    -m mark ! --mark "$FWMARK/$FWMARK" \
    -j NFQUEUE --queue-num "$QUEUE_NUM" --queue-bypass
fi

if ! iptables -t mangle -C OUTPUT -p udp --dport 443 \
     -m connbytes --connbytes-dir=original --connbytes-mode=packets \
     --connbytes 1:6 \
     -m mark ! --mark "$FWMARK/$FWMARK" \
     -j NFQUEUE --queue-num "$QUEUE_NUM" --queue-bypass 2>/dev/null; then
  iptables -t mangle -I OUTPUT 2 -p udp --dport 443 \
    -m connbytes --connbytes-dir=original --connbytes-mode=packets \
    --connbytes 1:6 \
    -m mark ! --mark "$FWMARK/$FWMARK" \
    -j NFQUEUE --queue-num "$QUEUE_NUM" --queue-bypass
fi

echo "FuckDPI запущен (nfqws pid=$(cat "$PIDFILE" 2>/dev/null || echo '?'), mode=$MODE)"
