# FuckDPI

Терминальный менеджер VPN (VLESS Reality через sing-box) + обход DPI блокировок (nfqws/winws).

## Установка

### Linux
```bash
bash <(curl -sSL https://raw.githubusercontent.com/capacs-glitch/fuckdpi/main/install.sh)
```

### Windows 11
```powershell
irm https://raw.githubusercontent.com/capacs-glitch/fuckdpi/main/install.ps1 | iex
```

## Использование

```
fuckdpi                     # интерактивный TUI
fuckdpi key <URL>           # добавить ключ подписки
fuckdpi vpn select          # VPN — только список доменов
fuckdpi vpn all             # VPN — весь трафик
fuckdpi fuckdpi select      # FuckDPI — только список доменов
fuckdpi fuckdpi all         # FuckDPI — весь трафик
fuckdpi stop                # остановить всё
fuckdpi status              # статус
```

### Команды в TUI

| Команда | Описание |
|---|---|
| `/key <ссылка>` | добавить ключ подписки |
| `/vpn select` | VPN только для списка доменов |
| `/vpn all` | VPN весь трафик |
| `/fuckdpi select` | FuckDPI только для списка доменов |
| `/fuckdpi all` | FuckDPI весь трафик |
| `/list` | nano-подобный редактор списка доменов |
| `/use <№>` | выбрать сервер |
| `/stop` | остановить |
| `/status` | статус |

## Зависимости

### Linux
- Python 3.10+
- sing-box
- nfqws — для FuckDPI

### Windows 11
- Python 3.10+ с `pip install windows-curses`
- sing-box (winget install SagerNet.sing-box)
- winws.exe — для FuckDPI

## Лицензия

MIT
