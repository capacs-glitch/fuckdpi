#!/bin/bash
# install.sh — установка FuckDPI для Linux (Arch/Debian/Fedora).
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
  echo "Нужен пароль sudo. Введи пароль когда попросит."
  sudo true
}

detect_distro() {
  if [[ -f /etc/arch-release ]]; then echo "arch"
  elif [[ -f /etc/debian_version ]]; then echo "debian"
  elif [[ -f /etc/fedora-release ]]; then echo "fedora"
  elif [[ -f /etc/redhat-release ]]; then echo "fedora"
  else echo "unknown"
  fi
}

DISTRO=$(detect_distro)
echo "  дистрибутив: $DISTRO"

install_pkg() {
  case "$DISTRO" in
    arch)    sudo pacman -S --needed --noconfirm "$@" ;;
    debian)  sudo apt-get install -y "$@" ;;
    fedora)  sudo dnf install -y "$@" ;;
    *)       echo "  неизвестный дистрибутив, установи вручную: $*"; return 1 ;;
  esac
}

echo "[1/6] скачиваю fuckdpi..."
TMPDIR=$(mktemp -d)
git clone --depth 1 "https://github.com/${REPO}.git" "$TMPDIR/fuckdpi" 2>/dev/null || {
  echo "ошибка клонирования; установи git"
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
  case "$DISTRO" in
    arch)
      sudo pacman -S --needed --noconfirm sing-box 2>/dev/null || {
        command -v yay &>/dev/null && yay -S --needed sing-box-bin
        command -v paru &>/dev/null && paru -S --needed sing-box-bin
      }
      ;;
    debian)
      sudo mkdir -p /etc/apt/keyrings
      curl -fsSL https://sing-box.app/deb.gpg.key | sudo gpg --dearmor -o /etc/apt/keyrings/sing-box.gpg 2>/dev/null || true
      echo "deb [signed-by=/etc/apt/keyrings/sing-box.gpg] https://deb.sing-box.app stable main" | sudo tee /etc/apt/sources.list.d/sing-box.list >/dev/null
      sudo apt-get update -qq && sudo apt-get install -y sing-box
      ;;
    fedora)
      sudo rpm --import https://sing-box.app/fedora.gpg.key 2>/dev/null || true
      sudo tee /etc/yum.repos.d/sing-box.repo >/dev/null <<'REPO'
[sing-box]
name=sing-box
baseurl=https://copr.fedorainfracloud.org/coprs/sing-box/sing-box/rpm/fedora-$releasever/$basearch/
enabled=1
gpgcheck=0
REPO
      sudo dnf install -y sing-box
      ;;
  esac
fi
echo "  sing-box: $(command -v sing-box || echo 'не найден')"

echo "[5/6] ставлю zapret (nfqws)..."
ZAPRET_DIR="/opt/zapret"
if [[ ! -x "$ZAPRET_DIR/nfq/nfqws" ]]; then
  case "$DISTRO" in
    arch)
      install_pkg base-devel libnetfilter_queue libmnl zlib
      ;;
    debian)
      install_pkg build-essential libnetfilter-queue-dev libmnl-dev zlib1g-dev
      ;;
    fedora)
      install_pkg gcc make libnetfilter_queue-devel libmnl-devel zlib-devel
      ;;
  esac
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
