#!/bin/bash
# install.sh — установка FuckDPI для Linux.
# Запуск: bash <(curl -sSL https://raw.githubusercontent.com/capacs-glitch/fuckdpi/main/install.sh)
set -euo pipefail

REPO="capacs-glitch/fuckdpi"
INSTALL_DIR="${HOME}/.local/bin"
CFG_DIR="${HOME}/.config/fuckdpi"

echo "==> FuckDPI — установка для Linux"
echo ""

if [[ $EUID -eq 0 ]]; then
  echo "Не запускай от root. Просто выполни:"
  echo "  bash <(curl -sSL https://raw.githubusercontent.com/capacs-glitch/fuckdpi/main/install.sh)"
  exit 1
fi

sudo -v 2>/dev/null || {
  echo "Нужен пароль sudo. Попробуй ещё раз — введи пароль когда попросит."
  sudo true
}

echo "[1/6] скачиваю fuckdpi..."
TMPDIR=$(mktemp -d)
git clone --depth 1 "https://github.com/${REPO}.git" "$TMPDIR/fuckdpi" 2>/dev/null || {
  echo "ошибка клонирования"
  exit 1
}

echo "[2/6] копирую файлы..."
mkdir -p "$INSTALL_DIR"
cp "$TMPDIR/fuckdpi/fuckdpi.py" "$INSTALL_DIR/fuckdpi"
cp "$TMPDIR/fuckdpi/start_fuckdpi.sh" "$INSTALL_DIR/start_fuckdpi.sh"
cp "$TMPDIR/fuckdpi/stop_fuckdpi.sh" "$INSTALL_DIR/stop_fuckdpi.sh"
chmod +x "$INSTALL_DIR/fuckdpi" "$INSTALL_DIR/start_fuckdpi.sh" "$INSTALL_DIR/stop_fuckdpi.sh"
rm -rf "$TMPDIR"

echo "[3/6] создаю конфиги..."
mkdir -p "$CFG_DIR"

echo "[4/6] ставлю sing-box..."
if ! command -v sing-box &>/dev/null; then
  sudo pacman -S --needed --noconfirm sing-box 2>/dev/null || {
    if command -v yay &>/dev/null; then
      yay -S --needed sing-box-bin 2>/dev/null || yay -S --needed sing-box
    elif command -v paru &>/dev/null; then
      paru -S --needed sing-box-bin 2>/dev/null || paru -S --needed sing-box
    fi
  }
fi
echo "  sing-box: $(command -v sing-box || echo 'не найден')"

echo "[5/6] ставлю zapret (nfqws)..."
ZAPRET_DIR="/opt/zapret"
if [[ ! -x "$ZAPRET_DIR/nfq/nfqws" ]]; then
  sudo pacman -S --needed --noconfirm base-devel libnetfilter_queue libmnl zlib
  sudo git clone --depth 1 https://github.com/bol-van/zapret.git "$ZAPRET_DIR"
  sudo make -C "$ZAPRET_DIR/nfq"
  sudo make -C "$ZAPRET_DIR/tpws" 2>/dev/null || true
  if [[ -f "$ZAPRET_DIR/install_prereq.sh" ]]; then
    sudo bash "$ZAPRET_DIR/install_prereq.sh" 2>/dev/null || true
  fi
else
  echo "  zapret уже установлен"
fi

echo "[6/6] настраиваю PATH..."
if [[ ":$PATH:" != *":$INSTALL_DIR:"* ]]; then
  SHELL_RC=""
  [[ -f "$HOME/.bashrc" ]] && SHELL_RC="$HOME/.bashrc"
  [[ -f "$HOME/.zshrc" ]] && SHELL_RC="$HOME/.zshrc"
  if [[ -n "$SHELL_RC" ]] && ! grep -q '$HOME/.local/bin' "$SHELL_RC" 2>/dev/null; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$SHELL_RC"
  fi
  export PATH="$HOME/.local/bin:$PATH"
fi

echo ""
echo "==> Установка завершена!"
echo ""
echo "Запусти: fuckdpi"
echo ""
