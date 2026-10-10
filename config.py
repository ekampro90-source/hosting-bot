import os
from pathlib import Path

_HERE = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv
    # script ke folder ki .env explicitly load karo (hosting panels ka cwd alag ho sakta hai)
    load_dotenv(_HERE / ".env")
except ImportError:
    # python-dotenv na ho to simple manual parser
    _f = _HERE / ".env"
    if _f.is_file():
        for _line in _f.read_text(encoding="utf-8", errors="ignore").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip().strip("\"'"))


def _clean(v):
    """Strip spaces and surrounding quotes (docker --env-file keeps quotes as-is)."""
    return (v or "").strip().strip("\"'").strip()


def _int(name, default):
    try:
        return int(_clean(os.getenv(name, str(default))))
    except ValueError:
        return int(default)


BASE_DIR = Path(__file__).resolve().parent


def _writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        t = path / ".write_test"
        t.write_text("ok")
        t.unlink()
        return True
    except Exception:
        return False


DATA_DIR = Path(_clean(os.getenv("DATA_DIR", "")) or BASE_DIR / "data").resolve()
if not _writable_dir(DATA_DIR):
    # volume / folder not writable (common on hosts) -> fall back to a folder that is
    _fallback = Path(os.getenv("TMPDIR", "/tmp")) / "hosting_bot_data"
    print(f"[config] WARNING: {DATA_DIR} writable nahi hai, {_fallback} use ho raha hai "
          f"(data restart pe ud sakta hai - volume permission fix karo)")
    DATA_DIR = _fallback.resolve()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "hosting.db"

BOT_TOKEN = _clean(os.getenv("BOT_TOKEN", ""))
OWNER_ID = _int("OWNER_ID", 0)
OWNER_USERNAME = _clean(os.getenv("OWNER_USERNAME", "DEVIL_MODS1")).lstrip("@")
UPDATES_CHANNEL = _clean(os.getenv("UPDATES_CHANNEL", "https://t.me/your_channel"))

FREE_LIMIT = _int("FREE_LIMIT", 1)          # files for free users
PREMIUM_LIMIT = _int("PREMIUM_LIMIT", 10)   # files for premium users
MAX_FILE_MB = _int("MAX_FILE_MB", 15)       # Telegram bots can download max 20 MB
MAX_UNZIPPED_MB = _int("MAX_UNZIPPED_MB", 100)
MAX_ZIP_FILES = _int("MAX_ZIP_FILES", 2000)
MAX_MEMORY_MB = _int("MAX_MEMORY_MB", 512)  # per python script (Linux only)
INSTALL_TIMEOUT = _int("INSTALL_TIMEOUT", 300)

PREMIUM_TEXT = os.getenv(
    "PREMIUM_TEXT",
    "💎 <b>Premium Plan</b>\n\n"
    f"• Upto {PREMIUM_LIMIT} files hosting\n"
    "• Priority support\n\n"
    "💰 Price: set PREMIUM_TEXT in .env\n\n"
    "Buy karne ke liye Contact Owner dabao 👇",
)

