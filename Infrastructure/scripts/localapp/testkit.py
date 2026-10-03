"""Test harness shared by the local-app suites.

The pieces a hermetic suite needs: a guard that makes non-loopback connects raise, a
fixture digest to compare before and after a run, assertions, and a loopback client.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable


# --------------------------------------------------------------------------- assertions
class CaseFailure(AssertionError):
    """One failed expectation inside one case."""


def check(condition: Any, message: str) -> None:
    if not condition:
        raise CaseFailure(message)


def check_eq(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise CaseFailure(f"{message}\n    expected: {expected!r}\n    actual:   {actual!r}")


# --------------------------------------------------------------------------- network guard
class NetworkBlocked(RuntimeError):
    """A connect to something that is not loopback."""


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "ip6-localhost"})
_real = (socket.socket.connect, socket.socket.connect_ex)


def _is_loopback(address: Any) -> bool:
    if isinstance(address, (str, bytes, os.PathLike)):  # an AF_UNIX path is local
        return True
    if isinstance(address, tuple) and address:
        host = str(address[0])
        return host in _LOOPBACK_HOSTS or host.startswith("127.")
    return False


def install_network_guard() -> None:
    """Make every non-loopback `connect` raise, so a stray fetch fails instead of slowing."""
    def guard(func: Callable) -> Callable:
        def wrapper(self, address, *args, **kwargs):
            if not _is_loopback(address):
                raise NetworkBlocked(f"the suite made a non-loopback connection to {address!r}")
            return func(self, address, *args, **kwargs)
        return wrapper
    socket.socket.connect = guard(_real[0])        # type: ignore[method-assign]
    socket.socket.connect_ex = guard(_real[1])     # type: ignore[method-assign]


def self_test_network_guard() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect(("192.0.2.1", 80))  # TEST-NET-1, a literal, so no DNS lookup happens
    except NetworkBlocked:
        return
    except OSError as exc:
        raise CaseFailure(f"the network guard did not fire; the socket layer did ({exc})")
    finally:
        sock.close()
    raise CaseFailure("the network guard did not fire on a non-loopback connect")


# --------------------------------------------------------------------------- digest
def tree_digest(root: Path) -> str:
    """One sha256 over every path and file under `root`, skipping caches and record locks."""
    digest = hashlib.sha256()
    for path in sorted(Path(root).rglob("*")):
        if "__pycache__" in path.parts or path.name.endswith(".yaml.lock"):  # not renv.lock
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        if path.is_file():
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


# --------------------------------------------------------------------------- client
class Client:
    """An HTTP client for one local app, on loopback only."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.origin = f"http://127.0.0.1:{port}"

    def request(self, method: str, path: str, body: bytes | None = None,
                headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            sent = {"Host": f"127.0.0.1:{self.port}", **(headers or {})}
            conn.request(method, path, body=body, headers=sent)
            resp = conn.getresponse()
            return resp.status, {k.lower(): v for k, v in resp.getheaders()}, resp.read()
        finally:
            conn.close()

    def json(self, method: str, path: str, payload: Any = None,
             headers: dict[str, str] | None = None) -> tuple[int, Any]:
        """Send `payload` as JSON with this app's Origin; return the status and parsed body."""
        sent = {"Origin": self.origin, "Content-Type": "application/json", **(headers or {})}
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        status, _, raw = self.request(method, path, body, sent)
        try:
            return status, json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return status, raw.decode("utf-8", "replace")


# --------------------------------------------------------------------------- browser
def probe_browser_open(cmd: list[str], ready: re.Pattern[str], work: Path) -> str:
    """Start an app server as a user would, with a `BROWSER` that blocks for 20 s.

    The app must answer `/api/state` while that browser is still open, the browser must be
    handed the app's URL, and with `CI` set no browser may be started at all. Returns a
    note for the PASS line; raises `CaseFailure` otherwise. A shell script plays the browser
    on POSIX and a .cmd script on Windows (CreateProcess runs it through cmd.exe).
    """
    windows = sys.platform == "win32"
    marker = Path(work) / "browser-opened.txt"
    if windows:
        fake = Path(work) / "slow-browser.cmd"
        fake.write_text(f'@echo off\r\necho %~1>"{marker}"\r\nping -n 21 127.0.0.1 >nul\r\n',
                        encoding="utf-8", newline="")
    else:
        fake = Path(work) / "slow-browser.sh"
        fake.write_text(f'#!/bin/sh\necho "$1" > "{marker}"\nsleep 20\n', encoding="utf-8",
                        newline="\n")
        fake.chmod(0o755)
    base = {k: v for k, v in os.environ.items() if k != "CI"}
    base.update({"BROWSER": str(fake), "DISPLAY": base.get("DISPLAY") or ":0"})
    group = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if windows
             else {"start_new_session": True})

    def stop(proc: subprocess.Popen) -> str:
        """Kill the server and the sleeping browser; return what the server printed since."""
        if windows:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, check=False)
        else:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        proc.wait(timeout=20)
        rest = proc.stdout.read() if proc.stdout else ""
        if proc.stdout:
            proc.stdout.close()
        return rest

    def launch(env: dict[str, str]) -> tuple[subprocess.Popen, int, list[str]]:
        proc = subprocess.Popen(cmd, env=env, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, **group)
        lines: list[str] = []
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            line = proc.stdout.readline() if proc.stdout else ""
            if not line:
                break
            lines.append(line)
            match = ready.search(line)
            if match:
                return proc, int(match.group(1)), lines
        stop(proc)
        raise CaseFailure("the server did not start:\n" + "".join(lines))

    proc, port, _ = launch(base)
    try:
        started = time.monotonic()
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request("GET", "/api/state", headers={"Host": f"127.0.0.1:{port}"})
            status = conn.getresponse().status
        except OSError as exc:
            raise CaseFailure(f"the app must serve while the browser is open, but /api/state "
                              f"failed after {time.monotonic() - started:.1f}s ({exc})") from None
        finally:
            conn.close()
        check_eq(status, 200, "/api/state answers while a slow browser is open")
        deadline = time.monotonic() + 10
        while not marker.is_file() and time.monotonic() < deadline:
            time.sleep(0.1)
        check(marker.is_file() and f"127.0.0.1:{port}" in marker.read_text(encoding="utf-8"),
              "the browser is opened on the app's URL once the server is serving")
    finally:
        stop(proc)
    marker.unlink()

    proc, _, lines = launch({**base, "CI": "1"})
    try:
        time.sleep(1.5)
        check(not marker.exists(), "with CI set no browser is started")
    finally:
        lines.append(stop(proc))
    check(any("Not opening a browser: CI is set" in line for line in lines),
          "with CI set the server says it is not opening a browser")
    return "served beside a blocking browser; none under CI"

