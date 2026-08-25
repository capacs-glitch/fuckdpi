#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fuckdpi — Linux: терминальный менеджер VPN (VLESS-Reality)
          + FuckDPI (nfqws/zapret — обход DPI без VPN).
Зависимости: только Python stdlib.
"""

import base64
import curses
import json
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlparse

# ---------------------------------------------------------------- пути/константы

CFG_DIR = Path.home() / ".config" / "fuckdpi"
KEY_FILE = CFG_DIR / "key.txt"
STATE_FILE = CFG_DIR / "state.json"
SERVERS_FILE = CFG_DIR / "servers.json"
CONFIG_FILE = CFG_DIR / "config.json"
HOSTLIST_FILE = CFG_DIR / "hostlist.txt"

SERVICE = "fuckdpid.service"
SB_CANDIDATES = ["/usr/bin/sing-box", "/usr/local/bin/sing-box"]
UA_BROWSER = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
TUN_IFACE = "mytun0"

FUCKDPI_SCRIPTS = [
    Path.home() / "fuckdpi" / "start_fuckdpi.sh",
    Path.home() / "fuckdpi" / "stop_fuckdpi.sh",
]

# ---------------------------------------------------------------- FuckDPI ASCII art

BANNER = [
    " _____ _                ____  ____  _   _  ____  _____",
    "|  ___| |_   _ ___ ___|  _ \\/ ___|| \\ | |/ ___|| ____|",
    "| |_  | | | | / __/ _ \\ | | | |   |  \\| | |  _ |  _|  ",
    "|  _| | | |_| | \\__ \\  __/ |_| |___| |\\  | |_| || |___",
    "|_|   |_|\\__,_|___/\\___|____/\\___/|_| \\_|\\____||_____|",
]

HELP_LINES = [
    ("/key <ссылка>",     "сохранить ключ: подписка или vless://"),
    ("/start",            "подключить VPN (спросит sudo)"),
    ("/stop",             "отключить VPN / FuckDPI"),
    ("/restart",          "перезапустить туннель"),
    ("/status",           "состояние: сервис, интерфейс, внешний IP"),
    ("/list",             "редактор списка доменов (nano-подобный)"),
    ("/use <№|слово>",    "выбрать сервер по номеру или названию"),
    ("/ping",             "замер задержки всех серверов"),
    ("/update",           "обновить подписку"),
    ("/ip",               "текущий внешний IP"),
    ("/log",              "последние логи сервиса"),
    ("/vpn select",       "VPN — только список доменов через туннель"),
    ("/vpn all",          "VPN — весь трафик через туннель"),
    ("/fuckdpi select",   "FuckDPI — только список доменов через nfqws"),
    ("/fuckdpi all",      "FuckDPI — весь трафик через nfqws"),
    ("/help",             "эта справка"),
    ("/quit",             "выход (или Ctrl+C)"),
]


# ---------------------------------------------------------------- утилиты

def sb_bin() -> str:
    for p in SB_CANDIDATES:
        if os.path.exists(p):
            return p
    return "sing-box"


def ensure_dirs():
    CFG_DIR.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data):
    ensure_dirs()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    tmp.replace(path)


def load_hostlist() -> list[str]:
    try:
        lines = HOSTLIST_FILE.read_text(encoding="utf-8").splitlines()
        return [l.strip().lower() for l in lines if l.strip()]
    except Exception:
        return []


def save_hostlist(domains: list[str]):
    ensure_dirs()
    HOSTLIST_FILE.write_text("\n".join(domains) + "\n" if domains else "",
                            encoding="utf-8")


def router_dns() -> str:
    try:
        for line in Path("/etc/resolv.conf").read_text().splitlines():
            line = line.strip()
            if line.startswith("nameserver"):
                ip = line.split()[1]
                if not ip.startswith("127.") and ":" not in ip:
                    return ip
    except Exception:
        pass
    return "192.168.0.1"


def run(cmd, timeout=25, **kw):
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, **kw)
    except Exception as e:
        class R:
            returncode, stdout, stderr = 1, "", str(e)
        return R()


def tcping(host, port=443, timeout=3):
    t0 = time.time()
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return int((time.time() - t0) * 1000)
    except Exception:
        return None


def resolve_ips(host):
    ips = []
    try:
        for r in socket.getaddrinfo(host, None, socket.AF_INET,
                                    socket.SOCK_STREAM):
            ip = r[4][0]
            if ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    return ips


def fill_ips(servers):
    def one(s):
        if not s.get("ips"):
            s["ips"] = resolve_ips(s["address"])
    with ThreadPoolExecutor(max_workers=10) as ex:
        list(ex.map(one, servers))


# ---------------------------------------------------------------- парсинг ключей

def parse_vless(link: str):
    u = urlparse(link.strip())
    q = dict(parse_qsl(u.query))
    name = unquote(u.fragment).strip() or (u.hostname or "?")
    return {
        "name": name,
        "address": u.hostname,
        "port": u.port or 443,
        "uuid": u.username or "",
        "flow": q.get("flow", ""),
        "security": q.get("security", "reality"),
        "sni": q.get("sni", ""),
        "pbk": q.get("pbk", ""),
        "sid": q.get("sid", ""),
        "fp": q.get("fp", "chrome"),
    }


def decode_sub_payload(text: str):
    cand = text
    raw = "".join(text.split())
    if raw and re.fullmatch(r"[A-Za-z0-9+/=]+", raw[:2048]):
        try:
            dec = base64.b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8")
            if "://" in dec:
                cand = dec
        except Exception:
            pass
    links = [l.strip() for l in cand.splitlines() if l.strip()]
    return [l for l in links if l.startswith("vless://")]


def fetch_subscription(url: str, log=lambda m: None):
    attempts = [
        ["curl", "-sL", "--max-time", "25", "-A", UA_BROWSER, url],
        ["wget", "-qO-", "--timeout=25", url],
        ["curl", "-s", "--http1.1", "--max-time", "25", "-A", UA_BROWSER, url],
    ]
    for i, cmd in enumerate(attempts, 1):
        tool = cmd[0]
        log(f"загрузка подписки ({tool}, попытка {i}/3)...")
        r = run(cmd, timeout=30)
        body = (r.stdout or "").strip()
        if r.returncode == 0 and len(body) > 200 and \
           "<html" not in body[:300].lower():
            links = decode_sub_payload(body)
            if links:
                log(f"получено серверов: {len(links)} (через {tool})")
                return links
        elif body:
            log(f"{tool}: ответ не похож на подписку ({len(body)} б)")
        else:
            log(f"{tool}: ошибка сети")
    return []


def load_key():
    try:
        return KEY_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def save_key(value: str):
    ensure_dirs()
    KEY_FILE.write_text(value.strip(), encoding="utf-8")


# ---------------------------------------------------------------- сервис /FuckDPI

def service_active() -> bool:
    return run(["systemctl", "is-active", "--quiet", SERVICE],
               timeout=5).returncode == 0


def tun_exists() -> bool:
    return run(["ip", "link", "show", TUN_IFACE], timeout=5).returncode == 0


def exit_ip(timeout=6):
    for _attempt in range(2):
        for url in ("https://api.ipify.org", "https://ifconfig.me",
                    "https://ipecho.net/plain"):
            r = run(["curl", "-4", "-s", "--max-time", str(timeout), url],
                    timeout=timeout + 3)
            ip = (r.stdout or "").strip()
            if r.returncode == 0 and re.fullmatch(r"[\d.]+", ip):
                return ip
        time.sleep(1)
    return None


def systemctl_sudo(action):
    return subprocess.run(["sudo", "systemctl", action, SERVICE]).returncode


def fuckdpi_running() -> bool:
    return run(["pgrep", "-x", "nfqws"], timeout=5).returncode == 0


def fuckdpi_start(mode: str, log=lambda m: None) -> bool:
    script = FUCKDPI_SCRIPTS[0]
    if not script.exists():
        log(f"скрипт не найден: {script}")
        return False
    log(f"запуск FuckDPI ({mode})...")
    r = subprocess.run(["sudo", "bash", str(script), mode],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()
        log(f"ошибка запуска FuckDPI: {err[:300]}")
        return False
    time.sleep(1)
    return fuckdpi_running()


def fuckdpi_stop(log=lambda m: None):
    script = FUCKDPI_SCRIPTS[1]
    if script.exists():
        subprocess.run(["sudo", "bash", str(script)],
                       capture_output=True, timeout=15)
    else:
        subprocess.run(["sudo", "killall", "nfqws"],
                       capture_output=True, timeout=5)


# ---------------------------------------------------------------- конфиг sing-box

def gen_config(server: dict, servers=None, log=lambda m: None,
               mode="all") -> bool:
    ensure_dirs()
    if server.get("security") != "reality":
        log(f"(!) '{server['name']}': протокол "
            f"'{server.get('security')}' — проверен только reality")
    ips = list(server.get("ips") or [])
    if not ips:
        ips = resolve_ips(server["address"])
        if ips:
            server["ips"] = ips
    all_servers = servers if servers is not None else load_json(SERVERS_FILE, [])
    protected = set(ips)
    for s in all_servers:
        protected.update(s.get("ips") or [])

    hostlist = load_hostlist() if mode == "select" else []

    cfg = {
        "log": {"level": "info", "timestamp": True},
        "dns": {
            "servers": [
                {"type": "udp", "tag": "dns-direct",
                 "server": router_dns()},
                {"type": "udp", "tag": "dns-tunnel", "server": "1.1.1.1",
                 "detour": "proxy"},
            ],
            "final": "dns-tunnel",
            "strategy": "prefer_ipv4",
        },
        "inbounds": [{
            "type": "tun", "tag": "tun-in",
            "interface_name": TUN_IFACE,
            "address": ["172.19.0.1/30"], "mtu": 1500,
            "auto_route": True, "strict_route": False,
            "auto_redirect": True, "stack": "system",
        }],
        "outbounds": [
            {
                "type": "vless", "tag": "proxy",
                "server": server["address"],
                "server_port": server["port"],
                "uuid": server["uuid"],
                "flow": server.get("flow", ""),
                "domain_resolver": {"server": "dns-direct",
                                    "strategy": "prefer_ipv4"},
                "tls": {
                    "enabled": True,
                    "server_name": server.get("sni") or server["address"],
                    "utls": {"enabled": True,
                             "fingerprint": server.get("fp", "chrome")},
                    "reality": {"enabled": True,
                                "public_key": server.get("pbk", ""),
                                "short_id": server.get("sid", "")},
                },
            },
            {"type": "direct", "tag": "direct"},
        ],
        "route": {
            "auto_detect_interface": True,
            "final": "proxy",
            "default_domain_resolver": {"server": "dns-direct",
                                        "strategy": "prefer_ipv4"},
            "rules": [
                {"action": "sniff"},
                {"protocol": "dns", "action": "hijack-dns"},
                {"ip_is_private": True, "outbound": "direct"},
                {"ip_cidr": sorted(f"{ip}/32" for ip in protected),
                 "outbound": "direct"},
            ],
        },
    }

    if mode == "select" and hostlist:
        cfg["route"]["final"] = "direct"
        cfg["route"]["rules"].insert(2, {
            "domain_suffix": hostlist, "outbound": "proxy"
        })
        cfg["dns"]["final"] = "dns-direct"
        cfg["dns"]["servers"].append({
            "type": "udp", "tag": "dns-hostlist",
            "server": "1.1.1.1", "detour": "proxy"
        })
        cfg["dns"]["rules"] = [
            {"domain_suffix": hostlist, "server": "dns-hostlist"},
            {"disable_cache": True, "server": "dns-direct"},
        ]

    CONFIG_FILE.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    check = run([sb_bin(), "check", "-c", str(CONFIG_FILE)], timeout=20)
    if check.returncode == 0:
        log(f"конфиг валиден ({CONFIG_FILE})")
        return True
    err = ((check.stderr or "") + (check.stdout or "")).strip()
    log(f"sing-box check: {err[:400]}")
    return False


# ---------------------------------------------------------------- ядро

class Engine:
    def __init__(self, emit):
        self.emit = emit
        self._lock = threading.Lock()

    def say(self, msg):
        with self._lock:
            self.emit(msg)

    def _selected(self):
        servers = load_json(SERVERS_FILE, [])
        state = load_json(STATE_FILE, {})
        sel = state.get("selected")
        idx = 0
        if sel:
            for i, s in enumerate(servers):
                if s["name"] == sel:
                    idx = i
                    break
        return servers, idx

    @staticmethod
    def _save_servers(servers):
        write_json(SERVERS_FILE, servers)

    def cmd_key(self, value: str):
        value = (value or "").strip()
        if not value:
            self.say("использование: /key <https://... | vless://...>")
            return
        ensure_dirs()
        if value.startswith("vless://"):
            srv = parse_vless(value)
            srv["ips"] = resolve_ips(srv["address"])
            save_key(value)
            self._save_servers([srv])
            write_json(STATE_FILE, {"selected": srv["name"]})
            gen_config(srv, [srv], self.say)
            self.say(f"ключ сохранён, сервер: {srv['name']} "
                     f"({srv['address']})")
            self.say("-> /vpn all или /vpn select")
            return
        if value.startswith(("http://", "https://")):
            links = fetch_subscription(value, self.say)
            if not links:
                self.say("подписка пустая/недоступна")
                return
            servers = []
            for l in links:
                p = parse_vless(l)
                p["ips"] = []
                servers.append(p)
            fill_ips(servers)
            save_key(value)
            self._save_servers(servers)
            write_json(STATE_FILE, {"selected": servers[0]["name"]})
            gen_config(servers[0], servers, self.say)
            self.say(f"подписка: {len(servers)} серверов; "
                     f"выбран '{servers[0]['name']}'")
            self.say("/list -- домены / /use <№> -- выбор / /vpn all")
            return
        path = Path(value).expanduser()
        if path.is_file():
            links = [l.strip() for l in path.read_text().splitlines()
                     if l.strip().startswith("vless://")]
            if not links:
                self.say("в файле нет vless:// ссылок")
                return
            servers = []
            for l in links:
                p = parse_vless(l)
                p["ips"] = []
                servers.append(p)
            fill_ips(servers)
            save_key(str(path))
            self._save_servers(servers)
            write_json(STATE_FILE, {"selected": servers[0]["name"]})
            gen_config(servers[0], servers, self.say)
            self.say(f"из файла загружено серверов: {len(servers)}")
            return
        self.say("не похоже на ссылку подписки/vless/файл")

    def select_server(self, token: str):
        servers, _ = self._selected()
        if not servers:
            self.say("сначала /key")
            return
        pick = None
        if token.isdigit() and 1 <= int(token) <= len(servers):
            pick = servers[int(token) - 1]
        if pick is None:
            t = token.lower()
            pick = next((s for s in servers if t in s["name"].lower()), None)
        if pick is None:
            self.say(f"сервер не найден: {token}")
            return
        st = load_json(STATE_FILE, {})
        st["selected"] = pick["name"]
        write_json(STATE_FILE, st)
        if any(not s.get("ips") for s in servers):
            fill_ips(servers)
            self._save_servers(servers)
        bypass = st.get("bypass", "all")
        gen_config(pick, servers, self.say, mode=bypass)
        self.say(f"выбран '{pick['name']}' ({pick['address']})")
        if service_active():
            self.say("сервис запущен; /restart для применения")

    def start(self, bypass="all"):
        if not CONFIG_FILE.exists():
            self.say("нет конфига — сначала /key")
            return
        if fuckdpi_running():
            self.say("FuckDPI активен; /stop перед запуском VPN")
            return
        servers, idx = self._selected()
        if servers:
            gen_config(servers[idx], servers, self.say, mode=bypass)
        rc = systemctl_sudo("start")
        if rc != 0:
            self.say(f"systemctl start вернул код {rc}")
            return
        ok = False
        for _ in range(15):
            if tun_exists():
                ok = True
                break
            time.sleep(1)
        ip = None
        for _ in range(4):
            ip = exit_ip()
            if ip:
                break
            time.sleep(2)
        st = load_json(STATE_FILE, {})
        st["mode"] = "vpn"
        st["bypass"] = bypass
        write_json(STATE_FILE, st)
        label = "по списку" if bypass == "select" else "весь трафик"
        if ok and ip:
            self.say(f"VPN подключен ({label}) . {TUN_IFACE} . IP: {ip}")
        elif ok:
            self.say(f"туннель поднят ({label}); IP определяется...")
        else:
            self.say(f"интерфейс {TUN_IFACE} не появился за 15 с — /log")

    def stop(self):
        if service_active():
            rc = systemctl_sudo("stop")
        else:
            rc = 0
        if fuckdpi_running():
            fuckdpi_stop(self.say)
        time.sleep(1)
        gone_tun = not tun_exists()
        gone_nf = not fuckdpi_running()
        st = load_json(STATE_FILE, {})
        st["mode"] = "off"
        write_json(STATE_FILE, st)
        if rc == 0 and gone_tun and gone_nf:
            self.say("ОТКЛЮЧЕНО")
        else:
            self.say(f"остановлено (systemctl={rc}, tun={gone_tun}, "
                     f"nfqws={gone_nf})")

    def restart(self):
        if fuckdpi_running():
            self.say("FuckDPI активен; /stop перед перезапуском VPN")
            return
        rc = systemctl_sudo("restart")
        if rc != 0:
            self.say(f"restart вернул код {rc}")
            return
        for _ in range(15):
            if tun_exists():
                break
            time.sleep(1)
        ip = exit_ip()
        self.say(f"ПЕРЕЗАПУЩЕНО . внешний IP: {ip or '?'}")

    def status_lines(self):
        act = service_active()
        tun = tun_exists()
        nf = fuckdpi_running()
        lines = []
        if act and tun:
            lines.append("режим:      VPN активен")
        elif nf:
            lines.append("режим:      FuckDPI активен")
        else:
            lines.append("режим:      отключен")
        lines.append(f"интерфейс:  {TUN_IFACE if tun else 'отсутствует'}")
        st = load_json(STATE_FILE, {})
        bypass = st.get("bypass", "all")
        if act or nf:
            lines.append(f"трафик:     "
                         f"{'по списку' if bypass == 'select' else 'весь трафик'}")
        ip = exit_ip()
        if ip:
            tag = "через VPN" if (act and tun) else \
                  "через FuckDPI" if nf else "напрямую"
            lines.append(f"внешний IP: {ip}  ({tag})")
        else:
            lines.append("внешний IP: не определён")
        servers, idx = self._selected()
        if servers:
            s = servers[idx]
            ms = tcping((s.get("ips") or [s["address"]])[0])
            lat = f"{ms} мс" if ms else "нет ответа"
            lines.append(f"сервер:     [{idx+1}/{len(servers)}] "
                         f"{s['name']} ({lat})")
        else:
            lines.append("сервер:     ключ не задан (/key)")
        hl = load_hostlist()
        lines.append(f"список:     {len(hl)} доменов (/list)")
        return lines

    def ping_all(self, done_cb):
        servers, idx = self._selected()
        if not servers:
            done_cb(["сначала /key"])
            return

        def worker():
            def one(i_s):
                i, s = i_s
                host = (s.get("ips") or [s["address"]])[0]
                return i, tcping(host)
            with ThreadPoolExecutor(max_workers=10) as ex:
                res = dict(ex.map(one, list(enumerate(servers))))
            rows = []
            for i in range(len(servers)):
                ms = res[i]
                mark = "  <-- выбран" if i == idx else ""
                shown = "--" if ms is None else f"{ms} мс"
                rows.append((99999 if ms is None else ms,
                             f"{i+1:>2}. {shown:>7}  "
                             f"{servers[i]['name']}{mark}"))
            rows.sort(key=lambda x: x[0])
            done_cb([r[1] for r in rows])

        threading.Thread(target=worker, daemon=True).start()

    def ping_all_sync(self):
        ev = threading.Event()
        box = {}
        self.ping_all(lambda rows: (box.update(r=rows), ev.set()))
        ev.wait(90)
        return box.get("r", ["таймаут опроса"])

    def update_sync(self):
        key = load_key()
        if not key.startswith(("http://", "https://")):
            self.say("ключ не является ссылкой подписки")
            return
        links = fetch_subscription(key, self.say)
        if not links:
            self.say("обновление не удалось")
            return
        old = {s["name"]: s for s in load_json(SERVERS_FILE, [])}
        servers = []
        for l in links:
            p = parse_vless(l)
            p["ips"] = old.get(p["name"], {}).get("ips", [])
            servers.append(p)
        fill_ips(servers)
        servers_old, idx = self._selected()
        sel = servers_old[idx]["name"] if servers_old else servers[0]["name"]
        self._save_servers(servers)
        write_json(STATE_FILE, {"selected": sel})
        cur = next((s for s in servers if s["name"] == sel), servers[0])
        st = load_json(STATE_FILE, {})
        bypass = st.get("bypass", "all")
        gen_config(cur, servers, self.say, mode=bypass)
        self.say(f"подписка обновлена: {len(servers)} серверов")
        if service_active():
            self.say("/restart чтобы применить")

    def update(self):
        threading.Thread(target=self.update_sync, daemon=True).start()

    def logs(self, n=30):
        r = run(["journalctl", "-u", SERVICE, "-n", str(n),
                 "--no-pager", "-q"], timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.rstrip().splitlines()
        return ["логи недоступны без прав; выполни:",
                "  sudo journalctl -u " + SERVICE + " -n 40"]

    def cmd_fuckdpi(self, mode: str):
        if mode not in ("select", "all"):
            self.say("использование: /fuckdpi select | /fuckdpi all")
            return
        if service_active():
            self.say("VPN активен; /stop перед запуском FuckDPI")
            return
        if fuckdpi_running():
            fuckdpi_stop(self.say)
        ok = fuckdpi_start(mode, self.say)
        if ok:
            st = load_json(STATE_FILE, {})
            st["mode"] = "fuckdpi"
            st["bypass"] = mode
            write_json(STATE_FILE, st)
            label = "по списку" if mode == "select" else "весь трафик"
            self.say(f"FuckDPI подключен ({label})")
        else:
            self.say("не удалось запустить FuckDPI; см. /log")


# ---------------------------------------------------------------- TUI

class UI:
    POPUP_MAX = 6
    ATTR = {0: curses.A_NORMAL, 1: curses.A_BOLD, 2: curses.A_NORMAL,
            3: curses.A_BOLD, 4: curses.A_BOLD, 5: curses.A_DIM,
            7: curses.A_DIM}

    def __init__(self, stdscr):
        self.scr = stdscr
        self.q = queue.Queue()
        self.engine = Engine(lambda t, c=0: self.q.put((t, c)))
        self.outbuf = deque(maxlen=400)
        self.history = deque(maxlen=100)
        self.hidx = None
        self.input = ""
        self.pending_key = False
        self.status_cache = (0.0, "...", False)
        self.cidx = None
        self.editor_active = False
        self.editor_lines: list[str] = []
        self.editor_cy = 0
        self.editor_cx = 0
        self.editor_scroll = 0

    def post(self, text, color=0):
        self.outbuf.append((str(text), color))

    def drain_queue(self):
        while True:
            try:
                text, color = self.q.get_nowait()
            except queue.Empty:
                break
            for chunk in (str(text).splitlines() or [""]):
                self.post(chunk, color)

    # ---------------- статус ----------------

    def status_text(self):
        now = time.time()
        ts, cached, _ = self.status_cache
        if now - ts > 2:
            try:
                act = service_active()
                tun = tun_exists()
                nf = fuckdpi_running()
                if act and tun:
                    head = "VPN"
                elif nf:
                    head = "FuckDPI"
                else:
                    head = "OFF"
                servers, idx = self.engine._selected()
                srv = servers[idx]["name"] if servers else ""
                st = load_json(STATE_FILE, {})
                bypass = st.get("bypass", "all")
                mode_tag = " [select]" if bypass == "select" and \
                    (act or nf) else ""
                cached = (head + mode_tag +
                          ("  " + srv if srv else ""), act or nf)
            except Exception:
                cached = ("...", False)
            self.status_cache = (now, cached[0], cached[1])
        return self.status_cache[1], self.status_cache[2]

    # ---------------- автодополнение ----------------

    def completions(self):
        tok = self.input.strip().lower()
        if not tok.startswith("/"):
            return []
        res = []
        for c, d in HELP_LINES:
            base = c.split()[0].lower()
            if base.startswith(tok) or (tok == "/" and base != "/quit"):
                res.append((base, d))
        return res[:self.POPUP_MAX]

    # ---------------- sudo ----------------

    def _ensure_sudo(self):
        if subprocess.run(["sudo", "-n", "true"],
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0:
            return True
        try:
            curses.endwin()
        except curses.error:
            pass
        print("одноразовый запрос пароля sudo...")
        rc = subprocess.run(["sudo", "v"]).returncode
        try:
            input("[Enter -- вернуться в FuckDPI]")
        except EOFError:
            pass
        try:
            self.scr.refresh()
        except curses.error:
            pass
        return rc == 0

    # ---------------- editor ----------------

    def _editor_open(self):
        ensure_dirs()
        try:
            text = HOSTLIST_FILE.read_text(encoding="utf-8")
            self.editor_lines = text.splitlines() or [""]
        except Exception:
            self.editor_lines = [""]
        self.editor_active = True
        self.editor_cy = 0
        self.editor_cx = 0
        self.editor_scroll = 0

    def _editor_save(self):
        content = "\n".join(self.editor_lines) + "\n"
        HOSTLIST_FILE.write_text(content, encoding="utf-8")
        self.editor_active = False
        self.post("список сохранен: " + HOSTLIST_FILE.name)

    def _editor_close(self):
        self.editor_active = False
        self.post("редактор закрыт (без сохранения)")

    def _editor_draw(self):
        self.scr.erase()
        h, w = self.scr.getmaxyx()
        hdr = "  FuckDPI -- редактор списка доменов"
        sub = "  Ctrl+S: сохранить | Ctrl+X: выход | Enter: новая строка"
        self.scr.addnstr(0, 0, hdr[:w-1], w-1, curses.A_BOLD)
        self.scr.addnstr(1, 0, sub[:w-1], w-1, curses.A_DIM)
        editor_top = 3
        editor_h = max(1, h - editor_top - 2)
        self.editor_cy = max(0, min(self.editor_cy,
                                    len(self.editor_lines) - 1))
        self.editor_cx = max(0, min(self.editor_cx,
                                    len(self.editor_lines[self.editor_cy])))
        if self.editor_cy < self.editor_scroll:
            self.editor_scroll = self.editor_cy
        if self.editor_cy >= self.editor_scroll + editor_h:
            self.editor_scroll = self.editor_cy - editor_h + 1
        gutter_w = len(str(len(self.editor_lines))) + 2
        for i in range(editor_h):
            li = self.editor_scroll + i
            y = editor_top + i
            if y >= h - 1:
                break
            if li < len(self.editor_lines):
                num = f"{li+1:>{gutter_w-2}}  "
                self.scr.addnstr(y, 0, num, gutter_w, curses.A_DIM)
                line = self.editor_lines[li]
                self.scr.addnstr(y, gutter_w, line[:w-gutter_w-1],
                                 max(0, w-gutter_w-1), curses.A_NORMAL)
                fill = w - gutter_w - len(line) - 1
                if fill > 0:
                    self.scr.addnstr(y, gutter_w + len(line),
                                     " " * fill, fill)
            else:
                num = f"~{' '*(gutter_w-1)}"
                self.scr.addnstr(y, 0, num, gutter_w, curses.A_DIM)
                fill = w - gutter_w
                if fill > 0:
                    self.scr.addnstr(y, gutter_w, " " * fill, fill,
                                     curses.A_NORMAL)
        help_y = h - 1
        self.scr.addnstr(help_y, 0,
                         " Ctrl+S=save  Ctrl+X=exit  "
                         "arrows=navigate  Enter=newline "[:w-1],
                         w-1, curses.A_DIM)
        cur_x = gutter_w + self.editor_cx
        cur_y = editor_top + (self.editor_cy - self.editor_scroll)
        if cur_x < w and cur_y < h - 1:
            try:
                self.scr.move(cur_y, cur_x)
            except curses.error:
                pass
        self.scr.refresh()

    def _editor_key(self, ch):
        if isinstance(ch, int):
            if ch in (19, 367):
                self._editor_save()
                return
            if ch in (24, 330):
                self._editor_close()
                return
            if ch in (curses.KEY_UP, 353):
                self.editor_cy = max(0, self.editor_cy - 1)
                self.editor_cx = min(self.editor_cx,
                                     len(self.editor_lines[self.editor_cy]))
                return
            if ch in (curses.KEY_DOWN, 525):
                self.editor_cy = min(len(self.editor_lines) - 1,
                                     self.editor_cy + 1)
                self.editor_cx = min(self.editor_cx,
                                     len(self.editor_lines[self.editor_cy]))
                return
            if ch == curses.KEY_LEFT:
                if self.editor_cx > 0:
                    self.editor_cx -= 1
                elif self.editor_cy > 0:
                    self.editor_cy -= 1
                    self.editor_cx = len(self.editor_lines[self.editor_cy])
                return
            if ch == curses.KEY_RIGHT:
                line = self.editor_lines[self.editor_cy]
                if self.editor_cx < len(line):
                    self.editor_cx += 1
                elif self.editor_cy < len(self.editor_lines) - 1:
                    self.editor_cy += 1
                    self.editor_cx = 0
                return
            if ch == curses.KEY_HOME:
                self.editor_cx = 0
                return
            if ch == curses.KEY_END:
                self.editor_cx = len(self.editor_lines[self.editor_cy])
                return
            if ch == curses.KEY_PPAGE:
                self.editor_cy = max(0, self.editor_cy - 10)
                self.editor_cx = min(self.editor_cx,
                                     len(self.editor_lines[self.editor_cy]))
                return
            if ch == curses.KEY_NPAGE:
                self.editor_cy = min(len(self.editor_lines) - 1,
                                     self.editor_cy + 10)
                self.editor_cx = min(self.editor_cx,
                                     len(self.editor_lines[self.editor_cy]))
                return
            if ch in (127, curses.KEY_BACKSPACE, 8):
                line = self.editor_lines[self.editor_cy]
                if self.editor_cx > 0:
                    self.editor_lines[self.editor_cy] = \
                        line[:self.editor_cx-1] + line[self.editor_cx:]
                    self.editor_cx -= 1
                elif self.editor_cy > 0:
                    prev = self.editor_lines[self.editor_cy - 1]
                    self.editor_cx = len(prev)
                    self.editor_lines[self.editor_cy - 1] = prev + line
                    del self.editor_lines[self.editor_cy]
                    self.editor_cy -= 1
                return
            if ch == curses.KEY_DC:
                line = self.editor_lines[self.editor_cy]
                if self.editor_cx < len(line):
                    self.editor_lines[self.editor_cy] = \
                        line[:self.editor_cx] + line[self.editor_cx+1:]
                elif self.editor_cy < len(self.editor_lines) - 1:
                    nxt = self.editor_lines[self.editor_cy + 1]
                    self.editor_lines[self.editor_cy] = line + nxt
                    del self.editor_lines[self.editor_cy + 1]
                return
            if ch in (10, 13, curses.KEY_ENTER):
                line = self.editor_lines[self.editor_cy]
                before = line[:self.editor_cx]
                after = line[self.editor_cx:]
                self.editor_lines[self.editor_cy] = before
                self.editor_lines.insert(self.editor_cy + 1, after)
                self.editor_cy += 1
                self.editor_cx = 0
                return
            if ch == 9:
                line = self.editor_lines[self.editor_cy]
                self.editor_lines[self.editor_cy] = \
                    line[:self.editor_cx] + "    " + line[self.editor_cx:]
                self.editor_cx += 4
                return
            return
        if isinstance(ch, str):
            if ch in ("\x7f", "\b"):
                line = self.editor_lines[self.editor_cy]
                if self.editor_cx > 0:
                    self.editor_lines[self.editor_cy] = \
                        line[:self.editor_cx-1] + line[self.editor_cx:]
                    self.editor_cx -= 1
                elif self.editor_cy > 0:
                    prev = self.editor_lines[self.editor_cy - 1]
                    self.editor_cx = len(prev)
                    self.editor_lines[self.editor_cy - 1] = prev + line
                    del self.editor_lines[self.editor_cy]
                    self.editor_cy -= 1
                return
            if ch in ("\n", "\r"):
                line = self.editor_lines[self.editor_cy]
                before = line[:self.editor_cx]
                after = line[self.editor_cx:]
                self.editor_lines[self.editor_cy] = before
                self.editor_lines.insert(self.editor_cy + 1, after)
                self.editor_cy += 1
                self.editor_cx = 0
                return
            if ch == "\t":
                line = self.editor_lines[self.editor_cy]
                self.editor_lines[self.editor_cy] = \
                    line[:self.editor_cx] + "    " + line[self.editor_cx:]
                self.editor_cx += 4
                return
            if ch == "\x13":
                self._editor_save()
                return
            if ch == "\x18":
                self._editor_close()
                return
            if ch.isprintable():
                line = self.editor_lines[self.editor_cy]
                self.editor_lines[self.editor_cy] = \
                    line[:self.editor_cx] + ch + line[self.editor_cx:]
                self.editor_cx += 1
                return

    # ---------------- отрисовка ----------------

    def put_center(self, y, text, attr):
        h, w = self.scr.getmaxyx()
        x = max(0, (w - len(text)) // 2)
        self.scr.addnstr(y, x, text[:max(0, w - x - 1)],
                         max(0, w - x - 1), attr)

    def draw(self):
        self.scr.erase()
        h, w = self.scr.getmaxyx()

        bw = len(BANNER[0]) if BANNER else 0
        bx = max(0, (w - bw) // 2)
        for i, row in enumerate(BANNER):
            self.scr.addnstr(i, bx, row[:max(0, w - bx - 1)],
                             max(0, w - bx - 1), curses.A_BOLD)

        stext, conn = self.status_text()
        self.put_center(len(BANNER) + 1, stext,
                        curses.A_BOLD if conn else curses.A_DIM)
        sub = "vless-reality . fuckdpi . /help"
        self.put_center(len(BANNER) + 2, sub, curses.A_DIM)

        comps = self.completions()
        popup_h = len(comps)
        inp_y = max(len(BANNER) + 4, min(h - 3, h - 4))
        bx0 = 2
        box_w = max(20, w - 4)

        log_top = len(BANNER) + 4
        log_h = inp_y - popup_h - log_top
        if log_h > 0:
            for text, color in list(self.outbuf)[-log_h:]:
                attr = self.ATTR.get(color, curses.A_NORMAL)
                self.scr.addnstr(log_top, 1, text[:w - 2], w - 3, attr)
                log_top += 1

        py = inp_y - popup_h
        for ci, (base, desc) in enumerate(comps):
            sel = (self.cidx is not None and ci == self.cidx)
            line = f"  {base:<20} "
            if sel:
                self.scr.addnstr(py, bx0, (line + desc)[:box_w - 1],
                                 box_w - 1, curses.A_REVERSE)
            else:
                self.scr.addnstr(py, bx0, line[:box_w - 1], box_w - 1,
                                 curses.A_BOLD)
                self.scr.addnstr(py, bx0 + len(line),
                                 desc[:max(0, box_w - 1 - len(line))],
                                 max(0, box_w - 1 - len(line)),
                                 curses.A_DIM)
            py += 1

        border = curses.A_DIM
        top = "+" + "-" * (box_w - 2) + "+"
        bot = "+" + "-" * (box_w - 2) + "+"
        self.scr.addnstr(inp_y, bx0, top[:max(0, w - bx0)],
                         max(0, w - bx0), border)
        inner_w = box_w - 6
        shown = self.input[-inner_w:] if len(self.input) > inner_w \
            else self.input
        pad = "| " + "> " + shown.ljust(inner_w) + " |"
        self.scr.addnstr(inp_y + 1, bx0, pad[:max(0, w - bx0)],
                         max(0, w - bx0), curses.A_NORMAL)
        self.scr.addnstr(inp_y + 2, bx0, bot[:max(0, w - bx0)],
                         max(0, w - bx0), border)
        cur_x = bx0 + 4 + min(len(self.input), inner_w)
        try:
            self.scr.move(inp_y + 1, min(cur_x, w - 2))
        except curses.error:
            pass

        self.put_center(h - 1,
                        "enter=send  tab=complete  ctrl+c=exit",
                        curses.A_DIM)
        self.scr.refresh()

    # ---------------- цикл ----------------

    def loop(self):
        self.post("FuckDPI ready. /help -- commands. /key <link>.")
        while True:
            if self.editor_active:
                self._editor_draw()
            else:
                self.draw()
            self.scr.timeout(120)
            try:
                ch = self.scr.get_wch()
            except curses.error:
                ch = -1
            if not self.editor_active:
                self.drain_queue()

            if self.editor_active:
                if (isinstance(ch, str) and ch in ("\n", "\r")) or \
                   ch in (10, 13, curses.KEY_ENTER):
                    self._editor_key(ch)
                    continue
                if (isinstance(ch, str) and ch in ("\x7f", "\b")) or \
                   ch in (8, 127, curses.KEY_BACKSPACE):
                    self._editor_key(ch)
                    continue
                if ch == curses.KEY_RESIZE:
                    continue
                if isinstance(ch, int) and ch in (3, 4, 26, 27):
                    self._editor_close()
                    continue
                if isinstance(ch, int) and ch in (19, 367):
                    self._editor_key(ch)
                    continue
                if isinstance(ch, int) and ch in (24, 330):
                    self._editor_key(ch)
                    continue
                if isinstance(ch, int) and ch in (
                    curses.KEY_UP, curses.KEY_DOWN,
                    curses.KEY_LEFT, curses.KEY_RIGHT,
                    curses.KEY_HOME, curses.KEY_END,
                    curses.KEY_PPAGE, curses.KEY_NPAGE,
                    curses.KEY_DC,
                ):
                    self._editor_key(ch)
                    continue
                if isinstance(ch, str) and ch.isprintable():
                    self._editor_key(ch)
                    continue
                if isinstance(ch, int):
                    self._editor_key(ch)
                    continue
                continue

            if (isinstance(ch, str) and ch in ("\n", "\r")) or \
               ch in (10, 13, curses.KEY_ENTER):
                self.exec_line()
                continue
            if (isinstance(ch, str) and ch in ("\x7f", "\b")) or \
               ch in (8, 127, curses.KEY_BACKSPACE):
                self.input = self.input[:-1]
                self.cidx = None
                continue
            if ch == curses.KEY_RESIZE:
                continue
            if ch in (curses.KEY_UP, curses.KEY_DOWN):
                comps = self.completions()
                if comps:
                    n = len(comps)
                    if self.cidx is None:
                        self.cidx = n - 1 if ch == curses.KEY_UP else 0
                    else:
                        step = -1 if ch == curses.KEY_UP else 1
                        self.cidx = (self.cidx + step) % n
                    self.input = comps[self.cidx][0]
                elif ch == curses.KEY_UP and self.history:
                    if self.hidx is None:
                        self.hidx = len(self.history)
                    self.hidx = max(0, self.hidx - 1)
                    self.input = self.history[self.hidx]
                elif ch == curses.KEY_DOWN and self.hidx is not None:
                    self.hidx += 1
                    if self.hidx >= len(self.history):
                        self.hidx = None
                        self.input = ""
                    else:
                        self.input = self.history[self.hidx]
                continue
            if ch == "\t" or ch == curses.KEY_BTAB:
                comps = self.completions()
                if comps:
                    k = self.cidx if (self.cidx is not None
                                      and self.cidx < len(comps)) else 0
                    base = comps[k][0]
                    self.input = base + (" " if base in ("/key",) else "")
                self.cidx = None
                continue
            if ch == 3 or ch == "\x03":
                raise SystemExit
            if isinstance(ch, str) and ch.isprintable():
                self.input += ch
                self.cidx = None

    def exec_line(self):
        line = self.input.strip()
        self.input = ""
        self.hidx = None
        self.cidx = None
        if not line:
            return
        self.history.append(line)
        self.post("> " + line, 3)

        if self.pending_key:
            self.pending_key = False
            threading.Thread(target=self.engine.cmd_key, args=(line,),
                             daemon=True).start()
            return

        parts = line.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("/quit", "/exit") or cmd == "q":
            raise SystemExit
        elif cmd == "/help":
            for c, d in HELP_LINES:
                self.post(f"  {c:<20} {d}", 7)
        elif cmd == "/key":
            if arg:
                threading.Thread(target=self.engine.cmd_key, args=(arg,),
                                 daemon=True).start()
            else:
                self.pending_key = True
                self.post("вставь ссылку следующей строкой:", 3)
        elif cmd == "/start":
            if self._ensure_sudo():
                st = load_json(STATE_FILE, {})
                bypass = st.get("bypass", "all")
                self.post(f"поднимаю VPN ({bypass})...", 7)
                threading.Thread(target=self.engine.start,
                                 args=(bypass,), daemon=True).start()
        elif cmd == "/stop":
            if self._ensure_sudo():
                threading.Thread(target=self.engine.stop,
                                 daemon=True).start()
        elif cmd == "/restart":
            if self._ensure_sudo():
                threading.Thread(target=self.engine.restart,
                                 daemon=True).start()
        elif cmd == "/status":
            threading.Thread(target=lambda: [
                self.post(l) for l in self.engine.status_lines()],
                daemon=True).start()
        elif cmd == "/list":
            self._editor_open()
        elif cmd == "/use":
            if arg:
                threading.Thread(target=self.engine.select_server,
                                 args=(arg,), daemon=True).start()
            else:
                self.post("использование: /use <№|часть названия>")
        elif cmd == "/ping":
            self.post("пингую все серверы...", 7)
            threading.Thread(target=lambda: [
                self.post(r) for r in self.engine.ping_all_sync()],
                daemon=True).start()
        elif cmd == "/update":
            threading.Thread(target=self.engine.update,
                             daemon=True).start()
        elif cmd == "/ip":
            threading.Thread(
                target=lambda: self.post(
                    f"внешний IP: {exit_ip() or 'не определён'}"),
                daemon=True).start()
        elif cmd == "/log":
            for l in self.engine.logs():
                self.post("| " + l, 7)
        elif cmd == "/vpn":
            if arg in ("select", "all"):
                if self._ensure_sudo():
                    self.post(f"поднимаю VPN ({arg})...", 7)
                    threading.Thread(target=self.engine.start,
                                     args=(arg,), daemon=True).start()
            else:
                self.post("использование: /vpn select | /vpn all")
        elif cmd == "/fuckdpi":
            if arg in ("select", "all"):
                if self._ensure_sudo():
                    threading.Thread(target=self.engine.cmd_fuckdpi,
                                     args=(arg,), daemon=True).start()
            else:
                self.post("использование: /fuckdpi select | /fuckdpi all")
        else:
            self.post(f"неизвестная команда: {cmd} (см. /help)", 4)


# ---------------------------------------------------------------- CLI

def cli_main(args):
    eng = Engine(print)
    cmd = args[0].lower()
    if cmd in ("help", "--help", "-h"):
        print("fuckdpi -- управление VPN + FuckDPI\n")
        for c, d in HELP_LINES:
            print(f"  {c:<20} {d}")
        print("\nБез аргументов: интерактивный интерфейс.")
    elif cmd == "key":
        eng.cmd_key(args[1] if len(args) > 1 else "")
    elif cmd == "start":
        eng.start()
    elif cmd == "stop":
        eng.stop()
    elif cmd == "restart":
        eng.restart()
    elif cmd == "status":
        for l in eng.status_lines():
            print(l)
    elif cmd == "list":
        servers, idx = eng._selected()
        if not servers:
            print("ключ не задан -- fuckdpi key <ссылка>")
            return
        for i, s in enumerate(servers):
            mark = "   <--" if i == idx else ""
            print(f"{i+1:>2}. {s['name']}  ({s['address']}){mark}")
    elif cmd == "use":
        if len(args) > 1:
            eng.select_server(args[1])
        else:
            print("использование: fuckdpi use <№|часть имени>")
    elif cmd == "ping":
        ev = threading.Event()
        box = {}
        eng.ping_all(lambda rows: (box.update(r=rows), ev.set()))
        ev.wait(60)
        for r in box.get("r", []):
            print(r)
    elif cmd == "update":
        eng.update_sync()
    elif cmd == "ip":
        print(exit_ip() or "не определён")
    elif cmd == "log":
        for l in eng.logs(50):
            print(l)
    elif cmd == "vpn":
        mode = args[1] if len(args) > 1 else ""
        if mode in ("select", "all"):
            eng.start(mode)
        else:
            print("использование: fuckdpi vpn select | fuckdpi vpn all")
    elif cmd == "fuckdpi":
        mode = args[1] if len(args) > 1 else ""
        if mode in ("select", "all"):
            eng.cmd_fuckdpi(mode)
        else:
            print("использование: fuckdpi fuckdpi select | "
                  "fuckdpi fuckdpi all")
    else:
        print(f"неизвестная команда: {cmd}\nсм.: fuckdpi help")
        sys.exit(2)


# ---------------------------------------------------------------- точка входа

def main():
    ensure_dirs()
    args = sys.argv[1:]
    if args:
        cli_main(args)
        return
    if not sys.stdin.isatty():
        print("интерактивный режим требует терминала; см.: fuckdpi help")
        return

    def run_ui(stdscr):
        try:
            UI(stdscr).loop()
        except SystemExit:
            pass

    curses.wrapper(run_ui)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
