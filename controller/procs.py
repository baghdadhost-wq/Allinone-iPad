"""Cross-platform process helpers.

Gateways run in the background, detached from the terminal's Ctrl+C, so that
interrupting Claude Code never kills the gateway it talks to. Claude Code runs
in the foreground with the terminal; the controller ignores Ctrl+C while it
waits so the keypress reaches Claude Code only.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

IS_WINDOWS = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000


def spawn_background(cmd: Sequence[str], cwd: Path, env: Dict[str, str], log_path: Path) -> subprocess.Popen:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = open(log_path, "ab")
    try:
        log.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} start: {' '.join(map(str, cmd))}\n".encode("utf-8", "replace"))
        log.flush()
        kwargs = dict(cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        if IS_WINDOWS:
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True
        return subprocess.Popen([str(c) for c in cmd], **kwargs)
    finally:
        log.close()


def pid_alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    if IS_WINDOWS:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        # Reap it first if it is our own finished child (avoids counting zombies as alive).
        reaped, _ = os.waitpid(pid, os.WNOHANG)
        if reaped == pid:
            return False
    except ChildProcessError:
        pass
    except OSError:
        pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def process_start_time(pid: int) -> Optional[float]:
    """When the process started (epoch seconds), or None if it cannot be determined.

    Used to make sure a PID saved earlier still belongs to the same process:
    after a reboot the operating system may give that number to another program.
    """
    try:
        if IS_WINDOWS:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, int(pid))
            if not handle:
                return None
            try:
                ft = [ctypes.c_ulonglong() for _ in range(4)]
                if not kernel32.GetProcessTimes(handle, *[ctypes.byref(f) for f in ft]):
                    return None
                return ft[0].value / 1e7 - 11644473600.0  # FILETIME (1601) -> Unix epoch
            finally:
                kernel32.CloseHandle(handle)
        stat = Path(f"/proc/{int(pid)}/stat")
        if stat.exists():
            fields = stat.read_text().rsplit(")", 1)[1].split()
            ticks = int(fields[19])  # field 22 overall: starttime
            btime = next(int(line.split()[1]) for line in Path("/proc/stat").read_text().splitlines()
                         if line.startswith("btime "))
            return btime + ticks / os.sysconf("SC_CLK_TCK")
        out = subprocess.run(["ps", "-o", "lstart=", "-p", str(int(pid))], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, timeout=5).stdout.decode().strip()
        if out:
            return time.mktime(time.strptime(out, "%a %b %d %H:%M:%S %Y"))
    except (OSError, ValueError, IndexError, StopIteration, subprocess.SubprocessError):
        return None
    return None


def same_process(pid: int, recorded_start: Optional[float], tolerance: float = 120.0) -> bool:
    if not pid_alive(pid):
        return False
    if not recorded_start:
        return True
    actual = process_start_time(pid)
    return actual is None or abs(actual - float(recorded_start)) <= tolerance


def kill_tree(pid: int, timeout: float = 10.0) -> None:
    """Stop a process and everything it started."""
    if not pid_alive(pid):
        return
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + timeout
        while pid_alive(pid) and time.time() < deadline:
            time.sleep(0.2)
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not pid_alive(pid):
            return
        time.sleep(0.2)
    try:
        os.killpg(pid, signal.SIGKILL)
    except OSError:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def run_foreground(cmd: Sequence[str], cwd: Path, env: Dict[str, str]) -> int:
    """Run an interactive program attached to this terminal; Ctrl+C goes to it, not to us."""
    proc = subprocess.Popen([str(c) for c in cmd], cwd=str(cwd), env=env)
    old_int = signal.signal(signal.SIGINT, signal.SIG_IGN)
    old_break = None
    if IS_WINDOWS and hasattr(signal, "SIGBREAK"):
        old_break = signal.signal(signal.SIGBREAK, signal.SIG_IGN)
    try:
        return proc.wait()
    finally:
        signal.signal(signal.SIGINT, old_int)
        if old_break is not None:
            signal.signal(signal.SIGBREAK, old_break)


def run(cmd: Sequence[str], cwd: Optional[Path] = None, env: Optional[Dict[str, str]] = None,
        check: bool = True, capture: bool = False, input_text: Optional[str] = None,
        timeout: Optional[float] = None) -> subprocess.CompletedProcess:
    result = subprocess.run(
        [str(c) for c in cmd],
        cwd=str(cwd) if cwd else None,
        env=env,
        input=input_text.encode("utf-8") if input_text is not None else None,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        raise CommandError(cmd, result.returncode, _decode(result.stdout), _decode(result.stderr))
    return result


def _decode(data: Optional[bytes]) -> str:
    return data.decode("utf-8", errors="replace") if data else ""


class CommandError(RuntimeError):
    def __init__(self, cmd: Sequence[str], code: int, stdout: str = "", stderr: str = ""):
        self.cmd = [str(c) for c in cmd]
        self.code = code
        self.stdout = stdout
        self.stderr = stderr
        tail = (stderr or stdout).strip().splitlines()[-15:]
        super().__init__(f"command failed ({code}): {' '.join(self.cmd)}" + ("\n" + "\n".join(tail) if tail else ""))


def port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def which(name: str) -> Optional[str]:
    import shutil

    return shutil.which(name)


def as_cmd(parts: List[str]) -> str:
    return " ".join(f'"{p}"' if " " in p else p for p in parts)
