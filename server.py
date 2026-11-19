from __future__ import annotations

import asyncio
import ctypes
import hashlib
import ipaddress
import json
import logging
import math
import os
import platform
import secrets
import socket
import sys
import time
import ssl
import datetime
from pathlib import Path
from urllib.parse import urlparse

from aiohttp import web, WSMsgType

try:
    import psutil
except Exception:
    psutil = None

try:
    import screen_brightness_control as sbc
except Exception as exc:  # pragma: no cover - optional at runtime
    sbc = None
    BRIGHTNESS_IMPORT_ERROR = str(exc)
else:
    BRIGHTNESS_IMPORT_ERROR = None

APP_DIR = Path(__file__).resolve().parent
WEB_DIR = APP_DIR / "web"
PORT = int(os.environ.get("WINREMOTE_PORT", "8765"))
PAIR_PIN = f"{secrets.randbelow(1_000_000):06d}"
SESSIONS: set[str] = set()
PAIR_ATTEMPTS: dict[str, tuple[int, float]] = {}
PAIR_GLOBAL_ATTEMPTS: tuple[int, float] = (0, 0.0)
PAIR_LOCK_SECONDS = 60
PAIR_MAX_ATTEMPTS = 5
TRUSTED_TOKEN_MAX_AGE_DAYS = 90

# Connection details are written only to the signed-in Windows user's local
# AppData folder. They are never exposed by an HTTP endpoint.
STATE_DIR = Path(os.environ.get("LOCALAPPDATA", str(APP_DIR))) / "WinRemote"
CONNECTION_FILE = STATE_DIR / "connection.json"
TRUSTED_DEVICES_FILE = STATE_DIR / "trusted_devices.json"
TLS_CA_CERT = STATE_DIR / "WinRemote-Root-CA.cer"
TLS_CA_KEY = STATE_DIR / "WinRemote-Root-CA.key"
TLS_SERVER_CERT = STATE_DIR / "server-cert.pem"
TLS_SERVER_KEY = STATE_DIR / "server-key.pem"


def load_trusted_tokens() -> set[str]:
    try:
        data = json.loads(TRUSTED_DEVICES_FILE.read_text(encoding="utf-8"))
        values = data.get("token_hashes", [])
        return {value for value in values if isinstance(value, str) and len(value) == 64}
    except (OSError, ValueError, AttributeError):
        return set()


PERSISTENT_TOKEN_HASHES: set[str] = load_trusted_tokens()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_is_valid(token: str) -> bool:
    return bool(token and (token in SESSIONS or token_hash(token) in PERSISTENT_TOKEN_HASHES))


def save_trusted_tokens() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = TRUSTED_DEVICES_FILE.with_suffix(".tmp")
    temp_path.write_text(json.dumps({"token_hashes": sorted(PERSISTENT_TOKEN_HASHES)}, indent=2), encoding="utf-8")
    temp_path.replace(TRUSTED_DEVICES_FILE)
    secure_windows_path(TRUSTED_DEVICES_FILE)


def secure_windows_path(path: Path) -> None:
    """Restrict sensitive state files to the current Windows account."""
    if not is_windows():
        return
    try:
        import subprocess
        account = os.environ.get("USERDOMAIN", "") + "\\" + os.environ.get("USERNAME", "")
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{account}:(F)", "SYSTEM:(F)"],
                       check=True, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as exc:
        log.warning("Could not restrict permissions on %s: %s", path.name, exc)

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("winremote")

ALLOWED_KEYS = {
    "enter", "backspace", "tab", "esc", "delete", "space", "up", "down",
    "left", "right", "home", "end", "pageup", "pagedown", "insert",
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
    "ctrl", "alt", "shift", "win", "capslock", "printscreen",
}
ALLOWED_CHORD_KEYS = ALLOWED_KEYS | set("abcdefghijklmnopqrstuvwxyz0123456789") | {
    "c", "v", "x", "a", "z", "y", "s", "w", "t", "r", "d", "l", "n", "p"
}
MEDIA_VK = {
    "playpause": 0xB3,
    "next": 0xB0,
    "previous": 0xB1,
    "volumeup": 0xAF,
    "volumedown": 0xAE,
    "mute": 0xAD,
}


def ensure_tls_certificate() -> ssl.SSLContext:
    """Create a local CA and an IP-SAN server certificate for trusted HTTPS.

    The CA certificate is installed manually on the user's phone. Its private
    key remains in the signed-in Windows profile and is never served over HTTP.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc)
    if TLS_CA_CERT.exists() and TLS_CA_KEY.exists():
        ca_key = serialization.load_pem_private_key(TLS_CA_KEY.read_bytes(), password=None)
        raw_ca = TLS_CA_CERT.read_bytes()
        try:
            ca_cert = x509.load_pem_x509_certificate(raw_ca)
        except ValueError:
            ca_cert = x509.load_der_x509_certificate(raw_ca)
    else:
        ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "WinRemote Local Root CA")])
        ca_cert = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
            .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                key_encipherment=False, data_encipherment=False, key_agreement=False,
                key_cert_sign=True, crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
            .sign(ca_key, hashes.SHA256()))
        TLS_CA_KEY.write_bytes(ca_key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        TLS_CA_CERT.write_bytes(ca_cert.public_bytes(serialization.Encoding.DER))
        secure_windows_path(TLS_CA_KEY)
        secure_windows_path(TLS_CA_CERT)

    # Re-apply restrictive ACLs on every launch, including pre-existing keys.
    secure_windows_path(TLS_CA_KEY)
    secure_windows_path(TLS_CA_CERT)

    ips = {ip for _, ip in get_network_addresses()}
    ips.add("127.0.0.1")
    sans = [x509.IPAddress(ipaddress.ip_address(ip)) for ip in sorted(ips)]
    sans.extend([x509.DNSName("localhost"), x509.DNSName(socket.gethostname())])
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "WinRemote")])
    server_cert = (x509.CertificateBuilder().subject_name(server_name)
        .issuer_name(ca_cert.subject).public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(server_key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256()))
    TLS_SERVER_KEY.write_bytes(server_key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    TLS_SERVER_CERT.write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))
    secure_windows_path(TLS_SERVER_KEY)

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(TLS_SERVER_CERT), str(TLS_SERVER_KEY))
    return context


def is_windows() -> bool:
    return sys.platform == "win32"


def get_network_addresses() -> list[tuple[str, str]]:
    """Return reachable-looking private IPv4 addresses with adapter labels.

    The server listens on all interfaces, so Wi-Fi, Ethernet, and a Bluetooth
    Personal Area Network (PAN) adapter can all carry the same WebSocket link.
    """
    found: list[tuple[str, str]] = []
    seen: set[str] = set()

    if psutil is not None:
        try:
            stats = psutil.net_if_stats()
            for adapter, entries in psutil.net_if_addrs().items():
                state = stats.get(adapter)
                if state is not None and not state.isup:
                    continue
                for entry in entries:
                    if entry.family != socket.AF_INET:
                        continue
                    ip = entry.address
                    try:
                        parsed = ipaddress.ip_address(ip)
                    except ValueError:
                        continue
                    if not parsed.is_private or parsed.is_loopback or ip in seen:
                        continue
                    seen.add(ip)
                    lowered = adapter.lower()
                    if "bluetooth" in lowered or "bth" in lowered or "pan" in lowered:
                        label = "Bluetooth PAN"
                    elif "wi-fi" in lowered or "wifi" in lowered or "wlan" in lowered:
                        label = "Wi-Fi"
                    elif "ethernet" in lowered:
                        label = "Ethernet"
                    else:
                        label = adapter
                    found.append((label, ip))
        except Exception:
            pass

    if not found:
        candidates: set[str] = set()
        try:
            for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                ip = item[4][0]
                parsed = ipaddress.ip_address(ip)
                if parsed.is_private and not parsed.is_loopback:
                    candidates.add(ip)
        except OSError:
            pass
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe.connect(("192.0.2.1", 80))
            ip = probe.getsockname()[0]
            probe.close()
            parsed = ipaddress.ip_address(ip)
            if parsed.is_private and not parsed.is_loopback:
                candidates.add(ip)
        except OSError:
            pass
        found.extend(("Network", ip) for ip in sorted(candidates))

    return found


def _wmi_brightness_connection():
    """Create a COM-initialized connection to Windows' monitor WMI namespace."""
    import pythoncom
    import wmi

    pythoncom.CoInitialize()
    try:
        connection = wmi.WMI(namespace=r"root\wmi")
    except Exception:
        pythoncom.CoUninitialize()
        raise
    return pythoncom, connection


def _wmi_get_brightness() -> int:
    pythoncom = None
    try:
        pythoncom, connection = _wmi_brightness_connection()
        displays = connection.WmiMonitorBrightness()
        active = [item for item in displays if bool(getattr(item, "Active", True))]
        candidates = active or list(displays)
        if not candidates:
            raise RuntimeError("Windows did not report a WMI-controlled display.")
        return int(candidates[0].CurrentBrightness)
    finally:
        if pythoncom is not None:
            pythoncom.CoUninitialize()


def _wmi_set_brightness(level: int) -> None:
    pythoncom = None
    try:
        pythoncom, connection = _wmi_brightness_connection()
        monitors = connection.WmiMonitorBrightnessMethods()
        active = [item for item in monitors if bool(getattr(item, "Active", True))]
        targets = active or list(monitors)
        if not targets:
            raise RuntimeError("Windows did not report a WMI brightness controller for the laptop display.")

        for monitor in targets:
            result = monitor.WmiSetBrightness(1, int(level))
            # WMI returns zero when WmiSetBrightness succeeds.
            if isinstance(result, (tuple, list)) and result:
                result = result[0]
            if hasattr(result, "ReturnValue"):
                result = result.ReturnValue
            if result is not None and int(result) != 0:
                raise RuntimeError(f"Windows WMI rejected the brightness change (return code {result}).")
    finally:
        if pythoncom is not None:
            pythoncom.CoUninitialize()


def brightness_status() -> dict:
    if not is_windows():
        return {"value": None, "available": False, "method": None,
                "error": "Brightness control is available only on Windows."}

    errors = []
    try:
        value = _wmi_get_brightness()
        return {"value": value, "available": True, "method": "Windows WMI", "error": None}
    except Exception as exc:
        errors.append(f"Windows WMI: {exc}")

    if sbc is not None:
        for method in ("wmi", None):
            try:
                kwargs = {"method": method} if method else {}
                value = sbc.get_brightness(**kwargs)
                if isinstance(value, list):
                    value = value[0] if value else None
                if value is not None:
                    return {"value": int(value), "available": True,
                            "method": "screen-brightness-control", "error": None}
            except Exception as exc:
                errors.append(f"screen-brightness-control: {exc}")

    detail = errors[-1] if errors else (BRIGHTNESS_IMPORT_ERROR or "Brightness components are unavailable.")
    return {
        "value": None,
        "available": False,
        "method": None,
        "error": ("Windows did not expose a controllable display brightness interface. "
                  "Check that the HP display/graphics drivers are installed and that Windows Settings > System > Display has a brightness slider. "
                  f"Details: {detail}")[:500],
    }


def set_brightness_level(level: int) -> str:
    """Prefer the built-in laptop panel's native WMI brightness interface."""
    errors = []
    try:
        _wmi_set_brightness(level)
        return "Windows WMI"
    except Exception as exc:
        errors.append(f"Windows WMI: {exc}")

    if sbc is not None:
        # First force WMI, which is the correct method for most laptop panels.
        # If that is unavailable, allow the library to choose a supported
        # backend such as DDC/CI for an external monitor.
        for method in ("wmi", None):
            try:
                kwargs = {"method": method} if method else {}
                sbc.set_brightness(level, **kwargs)
                return "screen-brightness-control"
            except Exception as exc:
                errors.append(f"screen-brightness-control: {exc}")

    detail = errors[-1] if errors else (BRIGHTNESS_IMPORT_ERROR or "Brightness components are unavailable.")
    raise RuntimeError(
        "Windows could not change display brightness. Make sure the HP display and graphics drivers are installed, "
        "and confirm that Windows Settings > System > Display provides a brightness slider. "
        f"Details: {detail}"
    )


def brightness_value():
    return brightness_status()["value"]


# Native SendInput avoids PyAutoGUI's default 100 ms pause on every action.
ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", ctypes.c_ulong), ("wParamL", ctypes.c_ushort), ("wParamH", ctypes.c_ushort)]


class INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("union", INPUTUNION)]


INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
WHEEL_DELTA = 120

KEY_VK = {
    "enter": 0x0D, "backspace": 0x08, "tab": 0x09, "esc": 0x1B,
    "delete": 0x2E, "space": 0x20, "up": 0x26, "down": 0x28,
    "left": 0x25, "right": 0x27, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22, "insert": 0x2D,
    "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B,
    "capslock": 0x14, "printscreen": 0x2C,
}
KEY_VK.update({f"f{i}": 0x6F + i for i in range(1, 13)})
KEY_VK.update({chr(code).lower(): code for code in range(ord("A"), ord("Z") + 1)})
KEY_VK.update({str(n): 0x30 + n for n in range(10)})


def _send_inputs(items: list[INPUT]) -> None:
    if not items:
        return
    array_type = INPUT * len(items)
    inputs = array_type(*items)
    sent = ctypes.windll.user32.SendInput(len(inputs), inputs, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        raise ctypes.WinError()


def _mouse_event(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> INPUT:
    item = INPUT()
    item.type = INPUT_MOUSE
    item.union.mi = MOUSEINPUT(dx, dy, data, flags, 0, 0)
    return item


def _key_event(vk: int, flags: int = 0, scan: int = 0) -> INPUT:
    item = INPUT()
    item.type = INPUT_KEYBOARD
    item.union.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    return item


def move_pointer(dx: int, dy: int) -> None:
    if not is_windows():
        raise RuntimeError("Mouse input is supported on Windows only.")
    if dx or dy:
        _send_inputs([_mouse_event(MOUSEEVENTF_MOVE, dx, dy)])


def click_mouse(button: str, clicks: int = 1) -> None:
    if not is_windows():
        raise RuntimeError("Mouse input is supported on Windows only.")
    flags = (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP) if button == "left" else (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP)
    events: list[INPUT] = []
    for _ in range(clicks):
        events.extend((_mouse_event(flags[0]), _mouse_event(flags[1])))
    _send_inputs(events)


def scroll_mouse(amount: int, horizontal: bool = False) -> None:
    if not is_windows():
        raise RuntimeError("Mouse input is supported on Windows only.")
    if amount:
        flags = MOUSEEVENTF_HWHEEL if horizontal else MOUSEEVENTF_WHEEL
        _send_inputs([_mouse_event(flags, data=amount * WHEEL_DELTA)])


def press_keys(keys: list[str]) -> None:
    if not is_windows():
        raise RuntimeError("Keyboard input is supported on Windows only.")
    codes = [KEY_VK[key] for key in keys]
    events = [_key_event(code) for code in codes]
    events.extend(_key_event(code, KEYEVENTF_KEYUP) for code in reversed(codes))
    _send_inputs(events)


def send_unicode_text(text: str) -> None:
    """Inject Unicode text through SendInput without touching the clipboard."""
    if not is_windows():
        raise RuntimeError("Text injection is supported on Windows only.")
    encoded = text.encode("utf-16-le", errors="replace")
    units = [encoded[i] | (encoded[i + 1] << 8) for i in range(0, len(encoded), 2)]
    events: list[INPUT] = []
    for unit in units:
        events.append(_key_event(0, KEYEVENTF_UNICODE, unit))
        events.append(_key_event(0, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, unit))
    _send_inputs(events)


def press_media_key(name: str) -> None:
    if not is_windows():
        raise RuntimeError("Media controls are supported on Windows only.")
    vk = MEDIA_VK[name]
    _send_inputs([_key_event(vk), _key_event(vk, KEYEVENTF_KEYUP)])


def lock_workstation() -> None:
    if not is_windows():
        raise RuntimeError("Lock is supported on Windows only.")
    if not ctypes.windll.user32.LockWorkStation():
        raise ctypes.WinError()


def client_ip(request: web.Request) -> str:
    peer = request.transport.get_extra_info("peername") if request.transport else None
    if not peer:
        return ""
    return str(peer[0]).split("%", 1)[0]


@web.middleware
async def lan_only_middleware(request: web.Request, handler):
    ip = client_ip(request)
    try:
        parsed = ipaddress.ip_address(ip)
        if getattr(parsed, "ipv4_mapped", None):
            parsed = parsed.ipv4_mapped
        if not (parsed.is_private or parsed.is_loopback or parsed.is_link_local):
            return web.json_response({"error": "This app only accepts local-network connections."}, status=403)
    except ValueError:
        return web.json_response({"error": "Unable to verify the local-network connection."}, status=403)

    origin = request.headers.get("Origin")
    if origin:
        try:
            origin_netloc = urlparse(origin).netloc.lower()
            request_netloc = request.host.lower()
            if origin_netloc and origin_netloc != request_netloc:
                return web.json_response({"error": "Cross-origin requests are not allowed."}, status=403)
        except Exception:
            return web.json_response({"error": "Invalid request origin."}, status=403)
    return await handler(request)


def require_token(request: web.Request) -> bool:
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else ""
    return token_is_valid(token)


async def index(request: web.Request):
    return web.FileResponse(WEB_DIR / "index.html")


async def pwa_manifest(request: web.Request):
    return web.FileResponse(WEB_DIR / "manifest.webmanifest",
                            headers={"Content-Type": "application/manifest+json"})


async def service_worker(request: web.Request):
    return web.FileResponse(WEB_DIR / "sw.js",
                            headers={"Content-Type": "application/javascript",
                                     "Service-Worker-Allowed": "/",
                                     "Cache-Control": "no-cache"})


async def pwa_icon(request: web.Request):
    name = request.match_info["name"]
    if name not in {"icon-192.png", "icon-512.png"}:
        raise web.HTTPNotFound()
    return web.FileResponse(WEB_DIR / "icons" / name)


async def pair(request: web.Request):
    global PAIR_GLOBAL_ATTEMPTS
    ip = client_ip(request)
    now = time.monotonic()
    attempts, blocked_until = PAIR_ATTEMPTS.get(ip, (0, 0.0))
    global_attempts, global_blocked_until = PAIR_GLOBAL_ATTEMPTS
    if blocked_until > now or global_blocked_until > now:
        return web.json_response({"error": "Too many pairing attempts. Try again in a minute."}, status=429)

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid request."}, status=400)

    supplied = str(data.get("pin", "")).strip()
    if not secrets.compare_digest(supplied, PAIR_PIN):
        attempts += 1
        global_attempts += 1
        PAIR_ATTEMPTS[ip] = (attempts, now + PAIR_LOCK_SECONDS if attempts >= PAIR_MAX_ATTEMPTS else 0.0)
        PAIR_GLOBAL_ATTEMPTS = (global_attempts, now + PAIR_LOCK_SECONDS if global_attempts >= 20 else 0.0)
        return web.json_response({"error": "That pairing code is not correct."}, status=401)

    PAIR_ATTEMPTS.pop(ip, None)
    PAIR_GLOBAL_ATTEMPTS = (0, 0.0)
    token = secrets.token_urlsafe(32)
    SESSIONS.add(token)
    if data.get("remember") is True:
        PERSISTENT_TOKEN_HASHES.add(token_hash(token))
        save_trusted_tokens()
    return web.json_response({"token": token, "device": platform.node() or "Windows laptop"})


async def status(request: web.Request):
    if not require_token(request):
        return web.json_response({"error": "Pair this device again."}, status=401)
    brightness = brightness_status()
    return web.json_response({
        "device": platform.node() or "Windows laptop",
        "brightness": brightness["value"],
        "brightnessAvailable": brightness["available"],
        "brightnessMethod": brightness["method"],
        "brightnessError": brightness["error"],
        "windows": is_windows(),
    })


async def health(request: web.Request):
    # Used by the Windows launcher to avoid starting duplicate server processes.
    return web.json_response({"ok": True, "port": PORT})


def write_connection_file() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": os.getpid(),
        "port": PORT,
        "pairing_code": PAIR_PIN,
        "device": platform.node() or "Windows laptop",
        "addresses": [
            {"label": label, "ip": ip, "url": f"https://{ip}:{PORT}"}
            for label, ip in get_network_addresses()
        ],
        "updated": time.time(),
    }
    temporary = CONNECTION_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(CONNECTION_FILE)


async def refresh_connection_file(app: web.Application) -> None:
    # Refresh adapter addresses periodically in case Wi-Fi comes up after logon.
    while True:
        try:
            write_connection_file()
        except OSError as exc:
            log.warning("Could not refresh connection details: %s", exc)
        await asyncio.sleep(15)


async def on_startup(app: web.Application) -> None:
    write_connection_file()
    app["connection_refresh_task"] = asyncio.create_task(refresh_connection_file(app))


async def on_cleanup(app: web.Application) -> None:
    task = app.get("connection_refresh_task")
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    try:
        existing = json.loads(CONNECTION_FILE.read_text(encoding="utf-8"))
        if existing.get("pid") == os.getpid():
            CONNECTION_FILE.unlink(missing_ok=True)
    except (OSError, ValueError, AttributeError):
        pass


async def websocket(request: web.Request):
    # Authenticate with the first encrypted WebSocket message, never in the URL.
    ws = web.WebSocketResponse(heartbeat=25, max_msg_size=16 * 1024, compress=False)
    await ws.prepare(request)
    transport_socket = request.transport.get_extra_info("socket") if request.transport else None
    if transport_socket is not None:
        try:
            transport_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass

    try:
        auth_msg = await asyncio.wait_for(ws.receive(), timeout=5.0)
        if auth_msg.type != WSMsgType.TEXT:
            await ws.close(code=1008, message=b"Authentication required")
            return ws
        try:
            auth_payload = json.loads(auth_msg.data)
        except (TypeError, json.JSONDecodeError):
            auth_payload = {}
        token = auth_payload.get("token", "") if isinstance(auth_payload, dict) and auth_payload.get("type") == "auth" else ""
        if not token_is_valid(token):
            await ws.close(code=1008, message=b"Not paired")
            return ws
        await ws.send_json({"type": "ready"})
    except asyncio.TimeoutError:
        await ws.close(code=1008, message=b"Authentication timeout")
        return ws

    async for msg in ws:
        if msg.type == WSMsgType.TEXT:
            try:
                payload = json.loads(msg.data)
                keep_open = await handle_action(ws, payload, token)
                if not keep_open:
                    break
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "message": "Invalid message."})
            except Exception as exc:
                log.debug("Input command failed: %s", exc)
                await ws.send_json({"type": "error", "message": str(exc)[:180]})
        elif msg.type == WSMsgType.ERROR:
            log.info("WebSocket closed with error: %s", ws.exception())
    return ws


async def handle_action(ws: web.WebSocketResponse, payload: dict, token: str) -> bool:
    if not isinstance(payload, dict):
        raise ValueError("Invalid command.")
    if not token_is_valid(token):
        return False
    action = payload.get("action")

    if not is_windows():
        raise RuntimeError("Run the companion app on your Windows laptop.")

    # These actions intentionally do not send acknowledgements. On a local
    # network, an acknowledgement for every pointer update creates needless
    # bidirectional traffic and makes the touchpad feel less immediate.
    if action == "move":
        dx = payload.get("dx", 0)
        dy = payload.get("dy", 0)
        if not isinstance(dx, (int, float)) or not isinstance(dy, (int, float)):
            raise ValueError("Invalid pointer movement.")
        dx = max(-2000, min(2000, int(dx)))
        dy = max(-2000, min(2000, int(dy)))
        move_pointer(dx, dy)

    elif action == "click":
        button = payload.get("button", "left")
        if button not in {"left", "right"}:
            raise ValueError("Invalid mouse button.")
        clicks = 2 if payload.get("double") is True else 1
        click_mouse(button, clicks)

    elif action == "scroll":
        amount = payload.get("amount", 0)
        if not isinstance(amount, (int, float)):
            raise ValueError("Invalid scroll amount.")
        amount = max(-20, min(20, int(amount)))
        scroll_mouse(amount)

    elif action == "hscroll":
        amount = payload.get("amount", 0)
        if not isinstance(amount, (int, float)):
            raise ValueError("Invalid horizontal scroll amount.")
        amount = max(-20, min(20, int(amount)))
        scroll_mouse(amount, horizontal=True)

    elif action == "key":
        key = str(payload.get("key", "")).lower()
        keys = payload.get("keys")
        if isinstance(keys, list):
            chord = [str(k).lower() for k in keys]
            if not 1 <= len(chord) <= 4 or any(k not in ALLOWED_CHORD_KEYS for k in chord):
                raise ValueError("That key combination is not supported.")
            press_keys(chord)
        elif key in ALLOWED_KEYS:
            press_keys([key])
        else:
            raise ValueError("That key is not supported.")

    elif action == "text":
        value = payload.get("value", "")
        if not isinstance(value, str) or len(value) > 1500:
            raise ValueError("Text must be 1,500 characters or fewer.")
        send_unicode_text(value)

    elif action == "media":
        command = str(payload.get("command", ""))
        if command not in MEDIA_VK:
            raise ValueError("Unknown media command.")
        press_media_key(command)

    elif action == "brightness":
        level = payload.get("value")
        if not isinstance(level, (int, float)) or not math.isfinite(level):
            raise ValueError("Invalid brightness level.")
        level = max(0, min(100, int(level)))
        method = await asyncio.to_thread(set_brightness_level, level)
        await ws.send_json({"type": "ack", "action": "brightness", "value": level, "method": method})

    elif action == "lock":
        lock_workstation()
        await ws.send_json({"type": "ack", "action": "lock"})

    elif action == "disconnect":
        SESSIONS.discard(token)
        token_digest = token_hash(token)
        if token_digest in PERSISTENT_TOKEN_HASHES:
            PERSISTENT_TOKEN_HASHES.discard(token_digest)
            save_trusted_tokens()
        await ws.send_json({"type": "disconnected"})
        await ws.close(code=1000, message=b"Disconnected by user")
        return False

    elif action == "ping":
        await ws.send_json({"type": "pong"})

    else:
        raise ValueError("Unknown command.")

    return True


def create_app() -> web.Application:
    app = web.Application(middlewares=[lan_only_middleware], client_max_size=16 * 1024)
    app.router.add_get("/", index)
    app.router.add_get("/manifest.webmanifest", pwa_manifest)
    app.router.add_get("/sw.js", service_worker)
    app.router.add_get("/icons/{name}", pwa_icon)
    app.router.add_get("/api/health", health)
    app.router.add_post("/api/pair", pair)
    app.router.add_get("/api/status", status)
    app.router.add_get("/ws", websocket)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


def main():
    if not is_windows():
        print("WinRemote must be run on the Windows laptop you want to control.")
        raise SystemExit(1)

    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        log_path = STATE_DIR / "server.log"
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            handlers=[logging.FileHandler(log_path, encoding="utf-8")],
        )
    except OSError:
        pass

    tls_context = ensure_tls_certificate()
    print("\nWinRemote is starting in the background with HTTPS.\n")
    addresses = get_network_addresses()
    if addresses:
        for label, ip in addresses:
            print(f"  Open on your phone ({label}): https://{ip}:{PORT}")
    else:
        print(f"  Open on your phone:  https://<your-laptop-ip>:{PORT}")
    print(f"  Pairing code:        {PAIR_PIN}")
    print("\nConnect over Wi-Fi, Ethernet, or Bluetooth PAN if your phone supports it.")
    print(f"  Android CA certificate: {TLS_CA_CERT}")
    print("Install this CA certificate on your phone before opening the HTTPS URL.")
    print("Keep the pairing code private.\n")
    if sbc is None:
        print(f"WARNING: Brightness library failed to load: {BRIGHTNESS_IMPORT_ERROR}")

    web.run_app(create_app(), host="0.0.0.0", port=PORT, ssl_context=tls_context, access_log=None, print=None)


if __name__ == "__main__":
    main()
