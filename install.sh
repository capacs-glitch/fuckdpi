#!/bin/bash
# install.sh — установка FuckDPI для Linux.
# Запуск: curl -sSL https://raw.githubusercontent.com/capacs-glitch/fuckdpi/main/install.sh | bash
set -euo pipefail

REPO="capacs-glitch/fuckdpi"
INSTALL_DIR="${HOME}/.local/bin"
CFG_DIR="${HOME}/.config/fuckdpi"

echo "==> FuckDPI — установка для Linux"
echo ""

# 1. Клонируем
echo "[1/6] скачиваю fuckdpi..."
TMPDIR=$(mktemp -d)
git clone --depth 1 "https://github.com/${REPO}.git" "$TMPDIR/fuckdpi" 2>/dev/null || {
  echo "ошибка клонирования; установи git: sudo pacman -S git"
  exit 1
}

# 2. Копируем файлы
echo "[2/6] копирую файлы..."
mkdir -p "$INSTALL_DIR"
cp "$TMPDIR/fuckdpi/fuckdpi.py" "$INSTALL_DIR/fuckdpi"
cp "$TMPDIR/fuckdpi/start_fuckdpi.sh" "$INSTALL_DIR/start_fuckdpi.sh"
cp "$TMPDIR/fuckdpi/stop_fuckdpi.sh" "$INSTALL_DIR/stop_fuckdpi.sh"
chmod +x "$INSTALL_DIR/fuckdpi" "$INSTALL_DIR/start_fuckdpi.sh" "$INSTALL_DIR/stop_fuckdpi.sh"

# 3. Конфиги
echo "[3/6] создаю конфиги..."
mkdir -p "$CFG_DIR"

# 4. sing-box
echo "[4/6] проверяю sing-box..."
if ! command -v sing-box &>/dev/null; then
  echo "  ставлю sing-box через pacman..."
  sudo pacman -S --needed --noconfirm sing-box 2>/dev/null || {
    if command -v yay &>/dev/null; then
      yay -S --needed sing-box-bin 2>/dev/null || yay -S --needed sing-box
    elif command -v paru &>/dev/null; then
      paru -S --needed sing-box-bin 2>/dev/null || paru -S --needed sing-box
    else
      echo "  установи sing-box вручную: https://github.com/SagerNet/sing-box"
    fi
  }
else
  echo "  sing-box: $(command -v sing-box)"
fi

# 5. zapret (nfqws)
echo "[5/6] проверяю zapret (nfqws)..."
ZAPRET_DIR="/opt/zapret"
if [[ ! -x "$ZAPRET_DIR/nfq/nfqws" ]]; then
  echo "  ставлю зависимости для сборки..."
  sudo pacman -S --needed --noconfirm base-devel libnetfilter_queue libmnl zlib 2>/dev/null || true

  echo "  клонирую zapret..."
  sudo git clone --depth 1 https://github.com/bol-van/zapret.git "$ZAPRET_DIR"
  echo "  компилирую nfqws..."
  sudo make -C "$ZAPRET_DIR/nfq"
  sudo make -C "$ZAPRET_DIR/tpws" 2>/dev/null || true
  if [[ -f "$ZAPRET_DIR/install_prereq.sh" ]]; then
    sudo bash "$ZAPRET_DIR/install_prereq.sh" 2>/dev/null || true
  fi
else
  echo "  zapret уже установлен"
fi

# 6. PATH
echo "[6/6] настраиваю PATH..."
if [[ ":$PATH:" != *":$INSTALL_DIR:"* ]]; then
  SHELL_RC=""
  if [[ -f "$HOME/.bashrc" ]]; then SHELL_RC="$HOME/.bashrc"
  elif [[ -f "$HOME/.zshrc" ]]; then SHELL_RC="$HOME/.zshrc"
  fi
  if [[ -n "$SHELL_RC" ]]; then
    if ! grep -q 'export PATH="$HOME/.local/bin:$PATH"' "$SHELL_RC" 2>/dev/null; then
      echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$SHELL_RC"
      echo "  добавлено в $SHELL_RC"
    fi
    export PATH="$HOME/.local/bin:$PATH"
  fi
fi

# Готово
echo ""
echo "==> Установка завершена!"
echo ""
echo "  fuckdpi              -- интерфейс"
echo "  fuckdpi key <URL>    -- добавить ключ"
echo "  fuckdpi vpn select   -- VPN по списку"
echo "  fuckdpi vpn all      -- VPN весь трафик"
echo "  fuckdpi fuckdpi select -- FuckDPI по списку"
echo "  fuckdpi fuckdpi all  -- FuckDPI весь трафик"
echo ""
echo "Если 'fuckdpi' не найден — перезапусти терминал."
