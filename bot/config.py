import base64
import os
import re
from pathlib import Path


def _ints(s):
    return {int(x) for x in re.findall(r"-?\d+", s or "")}


def _int(name, default):
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _data_dir() -> Path:
    for cand in (os.getenv("DATA_DIR") or "/app/data", "./data"):
        try:
            p = Path(cand)
            p.mkdir(parents=True, exist_ok=True)
            t = p / ".w"
            t.write_text("1")
            t.unlink()
            return p
        except Exception:
            continue
    return Path("/tmp")


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = _ints(os.getenv("ADMIN_IDS", ""))
TZ_NAME = os.getenv("BOT_TZ", "Asia/Tehran")
DATA_DIR = _data_dir()

MAX_CONCURRENT = max(1, _int("MAX_CONCURRENT", 3))
USER_MAX_ACTIVE = max(1, _int("USER_MAX_ACTIVE", 2))
DAILY_LIMIT = _int("DAILY_LIMIT", 0)
MAX_DURATION_MIN = _int("MAX_DURATION_MIN", 120)
DL_TIMEOUT = _int("DL_TIMEOUT", 900)
COLORED_BUTTONS = os.getenv("COLORED_BUTTONS", "1") == "1"

LOCAL_API_URL = os.getenv("LOCAL_API_URL", "").strip()
UPLOAD_LIMIT = (2000 if LOCAL_API_URL else 49) * 1024 * 1024
PROXY = os.getenv("PROXY", "").strip() or None

COOKIES_FILE = None
_b64 = os.getenv("COOKIES_B64", "").strip()
if _b64:
    try:
        _p = DATA_DIR / "cookies.txt"
        _p.write_bytes(base64.b64decode(_b64))
        COOKIES_FILE = str(_p)
    except Exception:
        COOKIES_FILE = None
elif (DATA_DIR / "cookies.txt").exists():
    COOKIES_FILE = str(DATA_DIR / "cookies.txt")
