"""Starts / stops hosted scripts as separate OS processes (Linux/macOS)."""
import asyncio
import os
import signal
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import config

MB = 1024 * 1024
PROCS: dict[int, subprocess.Popen] = {}

ENTRY_CANDIDATES = [
    "main.py", "bot.py", "app.py", "run.py", "start.py", "index.py",
    "index.js", "main.js", "bot.js", "app.js", "server.js", "start.js",
]


# ---------- status ----------
def is_running(fid):
    p = PROCS.get(fid)
    return p is not None and p.poll() is None


def status(fid):
    """('running', pid) | ('stopped', exit_code or None)"""
    p = PROCS.get(fid)
    if p is None:
        return "stopped", None
    code = p.poll()
    return ("running", p.pid) if code is None else ("stopped", code)


def running_count():
    return sum(1 for p in PROCS.values() if p.poll() is None)


# ---------- unzip ----------
def safe_extract(zpath: Path, dest: Path):
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    total = 0
    with zipfile.ZipFile(zpath) as z:
        infos = z.infolist()
        if len(infos) > config.MAX_ZIP_FILES:
            raise ValueError("Zip me bahut zyada files hain")
        for info in infos:
            target = (root / info.filename).resolve()
            if target != root and root not in target.parents:
                raise ValueError("Unsafe path in zip (zip-slip blocked)")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Symlinks zip me allowed nahi hain")
            total += info.file_size
            if total > config.MAX_UNZIPPED_MB * MB:
                raise ValueError(f"Unzipped size {config.MAX_UNZIPPED_MB} MB se zyada hai")
        z.extractall(root)


def flatten(dest: Path) -> Path:
    items = [p for p in dest.iterdir() if p.name != "__MACOSX"]
    if len(items) == 1 and items[0].is_dir():
        return items[0]
    return dest


def find_entry(folder: Path):
    for name in ENTRY_CANDIDATES:
        if (folder / name).is_file():
            return name
    for ext in (".py", ".js"):
        for p in sorted(folder.glob(f"*{ext}")):
            return p.name
    return None


# ---------- process env / limits ----------
def child_env(workdir: Path):
    """Clean environment: bot token / secrets are NOT passed to hosted scripts."""
    libs = workdir / ".libs"
    return {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(workdir),
        "LANG": "C.UTF-8",
        "PYTHONUNBUFFERED": "1",
        "PYTHONPATH": f"{libs}{os.pathsep}{workdir}",
        "NODE_PATH": str(workdir / "node_modules"),
        "PIP_NO_CACHE_DIR": "1",
    }


def _make_preexec(kind):
    def _limits():
        try:
            import resource

            resource.setrlimit(resource.RLIMIT_FSIZE, (200 * MB, 200 * MB))
            resource.setrlimit(resource.RLIMIT_NOFILE, (512, 512))
            if kind == "py" and config.MAX_MEMORY_MB > 0:
                # RLIMIT_AS (virtual memory) aiohttp/ssl/threads wali scripts ko
                # start hote hi MemoryError se crash kar deta tha -> RLIMIT_DATA use karo
                lim = config.MAX_MEMORY_MB * MB
                resource.setrlimit(resource.RLIMIT_DATA, (lim, lim))
        except Exception:
            pass

    return _limits


def _signal_group(p, sig):
    try:
        if os.name == "posix":
            os.killpg(p.pid, sig)
        else:
            p.terminate() if sig == signal.SIGTERM else p.kill()
    except (ProcessLookupError, PermissionError):
        pass


# ---------- dependencies ----------
async def _run(cmd, cwd: Path):
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=cwd, env=child_env(cwd),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), config.INSTALL_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        return False, "timeout"
    return proc.returncode == 0, out.decode(errors="replace")[-400:]


async def install_deps(workdir: Path) -> str:
    notes = []
    if (workdir / "requirements.txt").is_file():
        ok, out = await _run(
            [sys.executable, "-m", "pip", "install", "-r", "requirements.txt",
             "--target", str(workdir / ".libs"), "--no-input",
             "--disable-pip-version-check", "-q"],
            workdir,
        )
        notes.append("✅ requirements.txt installed" if ok else f"⚠️ pip install failed:\n{out}")
    if (workdir / "package.json").is_file():
        ok, out = await _run(["npm", "install", "--omit=dev", "--no-audit", "--no-fund"], workdir)
        notes.append("✅ npm packages installed" if ok else f"⚠️ npm install failed:\n{out}")
    return "\n".join(notes)


# ---------- start / stop ----------
def start(fid, workdir, entry):
    """Returns (ok, pid_or_error)."""
    if is_running(fid):
        return False, "Already running"
    wd = Path(workdir)
    if not (wd / entry).is_file():
        return False, "Entry file missing"
    kind = "js" if entry.endswith(".js") else "py"
    cmd = ["node", entry] if kind == "js" else [sys.executable, "-u", entry]

    log_path = wd / "output.log"
    if log_path.exists() and log_path.stat().st_size > 5 * MB:
        log_path.write_bytes(b"")
    log = open(log_path, "ab")
    log.write(f"\n--- started {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n".encode())
    log.flush()
    try:
        p = subprocess.Popen(
            cmd, cwd=wd, env=child_env(wd),
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            preexec_fn=_make_preexec(kind) if os.name == "posix" else None,
            start_new_session=True,
        )
    except FileNotFoundError:
        return False, "node installed nahi hai" if kind == "js" else "python nahi mila"
    except Exception as e:
        return False, str(e)
    finally:
        log.close()
    PROCS[fid] = p
    return True, p.pid


async def stop(fid):
    p = PROCS.pop(fid, None)
    if p is None:
        return False
    if p.poll() is None:
        _signal_group(p, signal.SIGTERM)
        for _ in range(50):
            if p.poll() is not None:
                break
            await asyncio.sleep(0.1)
        else:
            _signal_group(p, signal.SIGKILL)
    try:
        p.wait(timeout=2)
    except Exception:
        pass
    return True


def kill_stale(pid, workdir):
    """After a bot restart: kill orphaned script only if its cwd is still the script folder."""
    if not pid or os.name != "posix":
        return
    try:
        if os.path.realpath(os.readlink(f"/proc/{pid}/cwd")) == os.path.realpath(workdir):
            os.killpg(pid, signal.SIGKILL)
    except Exception:
        pass


def tail_log(workdir, limit=2000):
    p = Path(workdir) / "output.log"
    if not p.is_file():
        return ""
    with open(p, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - limit))
        return f.read().decode(errors="replace").strip()
