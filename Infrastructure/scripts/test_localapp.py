#!/usr/bin/env python3
"""Test suite for the shared local-app kit (`Infrastructure/scripts/localapp/`).

`python3 Infrastructure/scripts/test_localapp.py` from anywhere. One `PASS` line per case:

    1  YAML byte identity     both tools' dumps match the bytes pinned before the move
    2  YAML load and save     string timestamps, reorder, mode kept, LF, cleanup, retry
    3  File lock              contended across processes, timeout names the PID, waits,
                              refuses a planted symlink, releases on a failed PID write
    4  Project root           explicit root checked against the id, walk-up, refusals
    5  Loopback server        origin and host, headers and CSP, body cap, routing, port
    6  Lint types and harness findings and the fixture digest

It reads the war-room and review-board fixtures and never writes them: both directories
must hash the same before and after. Exit codes: 0 pass, 1 fail, 2 unusable environment.

Dependencies: Python 3.11+ and PyYAML. Git is used by case 3 when present.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent.parent
sys.path.insert(0, str(SCRIPTS))

try:
    import yaml
    import review_board_lib as rb  # noqa: E402
    import war_room_lib as wr  # noqa: E402
    from localapp import filelock, lint, projroot, server, testkit, yamlio  # noqa: E402
except (ImportError, SystemExit) as exc:
    print(f"ENVIRONMENT: {exc}")
    raise SystemExit(2)

from localapp.testkit import CaseFailure, check, check_eq  # noqa: E402

WR_FIXTURES = SCRIPTS / "war_room_fixtures"
RB_FIXTURES = SCRIPTS / "review_board_fixtures"


# =========================================================================== case 1
TRICKY = {"plain": "one line", "multi": "first\nsecond\n", "trailing": "ends with space \nx",
          "indented": "  starts indented\nnext", "unicode": "café — naïve\n", "cr": "a\rb",
          "tab": "a\tb\nc", "empty": "", "keys": {"lines": [3, 4], "n": None, "ok": True}}


def _board_documents() -> list[tuple[str, dict, Any]]:
    """Synthetic feedback and ledger files that use every board marking."""
    head = {"schema_version": 1, "project": {"id": "proj-fig"}, "board": {"id": "demo"},
            "fixture": True}
    feedback = {**head, "events": [
        {"text": "Line one.\nLine two:\n  indented\n", "kind": "comment",
         "id": "ev-00001", "seq": 1, "item": "fig-a", "by": "owner",
         "at": "2026-09-24T10:00:00.000000Z", "source": "local"},
        {"id": "ev-00003", "seq": 3, "item": "fig-a", "by": "owner", "kind": "comment",
         "at": "2026-09-24T10:02:00Z", "text": "trailing space \nfalls back to quotes"},
        {"id": "ev-00002", "seq": 2, "item": "fig-a", "by": "rlee", "kind": "status",
         "at": "2026-09-24T10:01:00Z", "status": "approved", "approved_hash": "a" * 64}]}
    measurements = {"contrast": {"result": "not-measured"}, "width_px": 1200, "height_px": 800,
                    "dpi": 200, "dpi_changed": False,
                    "text_floor": {"result": "pass", "smallest_pt": 8.8, "offenders": []},
                    "palette": {"result": "fail", "off_palette": ["#123456", "#abcdef"]}}
    ledger = {**head, "rounds": [{
        "n": 1, "opened_at": "2026-09-24T09:00:00Z", "cursor_seq": 2, "listed": ["ev-00001"],
        "carried": [], "stop_gate": {"reason": "why\nnot", "verdict": "proceed"},
        "triage": [{"event": "ev-00001", "decision": "do", "reason": "Two\nlines"}],
        "changes": [{"item": "fig-a", "what_changed": "Axis", "explanation": "a\nb"}],
        "changed_files": {"outside_sources": ["code/x.py"], "available": True},
        "closed_at": "2026-09-24T11:00:00Z"}],
        "items": [{"renders": [{"round": 1, "hash": "b" * 64, "classification": "new",
                                "snapshot": "renders/r01/fig-a.png",
                                "measurements": measurements}], "id": "fig-a"}]}
    return [("feedback", feedback, rb.order_feedback), ("ledger", ledger, rb.order_ledger)]


# Both tools write through the kit, so their bytes are pinned to what each tool's own dumper
# wrote before the move (sha256 of the text).
WAR_ROOM_DUMP_SHA256 = {
    "ledgers/fast-forward/ledger.yaml": "4f6ec74203facdfeb241ed27b5d81022a13bd9206587c45c476626b40429ac73",
    "ledgers/ordered/ledger.yaml": "10a2ed5ca06fc7efcee7d7da6f4905f85e577bafd22ab635ff94e8985a0eb9a2",
    "ledgers/two-reviewer/ledger.yaml": "4f0aa8b1912baf1a1c17c1a0aa12bbafac15dcd6bcf714c5f3ee3183989af190",
    "predictions/proj_a--code--sample.R.yaml": "3657037671d6f4aa9e198b6845709eb0f707ac351d87b43493ac7d5c7053262f",
    "predictions/proj_a--code--sample.Rmd.yaml": "341ee171e1d42216a6df28e21bfd4c05a2c2faa032c2b862cbc073fd608a7437",
    "predictions/proj_a--code--sample.ado.yaml": "0f0301b5b884bc899ccd933d60c39d4f302cf76bc6fd96bdfbbea3634bf80bae",
    "predictions/proj_a--code--sample.do.yaml": "2f6661f404ff7a21db695474ab3f25936d8483bd441f4956716d6517eff232e9",
    "predictions/proj_a--code--sample.py.yaml": "78ba52f8e60ddedafa60db244bc9268dc5b59463eccb8f7eabbe7733025003f6",
    "predictions/proj_a--code--sample.qmd.yaml": "2db3509f11dca62e3a661e001e58b180b6975765783107e8069fe98a4d6076a0",
    "tricky": "271a89ce142589025797d756649d5c3aea40220d1a819119569b6cae6aa889a8",
}
BOARD_DUMP_SHA256 = {
    "board.yaml": "891d97dbe8e3e39b76eb561db911fc40f4b784673e386f93cc95dcc388a69be1",
    "feedback": "e0d787620923b98254fde5360b39bf9da87a1e8647102438b44251944fd6e69e",
    "ledger": "4aff84d3112108ddb9bbbfadd26b7374970e59cf313eed1bb1f49031a033afe4",
    "tricky": "885f5a51ff3f11f555810caebebe34febfe9e76ccf8c49af18968058e46cbded",
}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def case_1_byte_identity(work: Path) -> str:
    compared = 0
    for path in sorted(WR_FIXTURES.rglob("*.yaml")):
        name = path.relative_to(WR_FIXTURES).as_posix()
        check_eq(_sha(wr.dump_ledger(wr.load_ledger(path))), WAR_ROOM_DUMP_SHA256[name],
                 f"war-room dump of {name}")
        compared += 1
    board_docs = [(p.name, rb.load_yaml(p), dict) for p in sorted(RB_FIXTURES.rglob("*.yaml"))]
    for name, data, order in [*board_docs, *_board_documents(), ("tricky", TRICKY, dict)]:
        check_eq(_sha(rb.dump_yaml(order(copy.deepcopy(data)))), BOARD_DUMP_SHA256[name],
                 f"board dump of {name}")
        compared += 1
    check_eq(_sha(yamlio.dump_yaml(copy.deepcopy(TRICKY), literal_multiline=False)),
             WAR_ROOM_DUMP_SHA256["tricky"], "tricky strings, literal_multiline=False")
    return f"{compared + 1} documents byte-identical"


# =========================================================================== case 2
def case_2_load_and_save(work: Path) -> None:
    loaded = yaml.load("at: 2026-09-17T10:11:44Z\nday: 2026-09-17\nn: 3\n", Loader=yamlio.Loader)
    check_eq(loaded, {"at": "2026-09-17T10:11:44Z", "day": "2026-09-17", "n": 3},
             "timestamps and dates stay strings")
    check_eq(list(yamlio.reorder({"c": 1, "a": 2, "z": 3}, ("a", "b", "c"))), ["a", "c", "z"],
             "reorder puts known keys first, then the rest as they were")
    check_eq(yamlio.reorder([1, 2], ("a",)), [1, 2], "reorder passes a non-mapping through")

    target = work / "record.yaml"
    yamlio.atomic_write_text(target, "a: 1\n")
    umask = os.umask(0)
    os.umask(umask)
    if sys.platform == "win32":
        # Windows has no permission bits; os.stat reports 0o666 for any writable file and
        # 0o444 for a read-only one, so only "writable, not mkstemp's 0600" can be checked.
        check_eq(stat.S_IMODE(target.stat().st_mode), 0o666,
                 "a new file is writable, not mkstemp's 0600")
        print("  (mode preservation not checked: Windows has no POSIX permission bits)")
    else:
        check_eq(stat.S_IMODE(target.stat().st_mode), 0o666 & ~umask,
                 "a new file gets the umask's mode, not mkstemp's 0600")
        for mode in (0o644, 0o640, 0o664):
            target.chmod(mode)
            yamlio.atomic_write_text(target, "a: 2\nb: 'x'\n")
            check_eq(stat.S_IMODE(target.stat().st_mode), mode,
                     f"mode {oct(mode)} survives a save")
    yamlio.atomic_write_text(target, "a\nb\n")
    check_eq(target.read_bytes(), b"a\nb\n", "LF endings on every platform")

    before = target.read_bytes()
    try:
        yamlio.atomic_write_text(target, "bad \udcff surrogate")
    except UnicodeEncodeError:
        pass
    else:
        raise CaseFailure("an unencodable string must raise")
    check_eq(target.read_bytes(), before, "a failed write leaves the target unchanged")
    check_eq(sorted(p.name for p in work.iterdir()), ["record.yaml"], "and no temporary file")

    real_replace, calls = os.replace, []

    def flaky(src, dst):
        calls.append(src)
        if len(calls) < 3:
            raise PermissionError("held open by another process")
        return real_replace(src, dst)
    os.replace = flaky
    try:
        yamlio.atomic_write_text(target, "retried: true\n")
    finally:
        os.replace = real_replace
    check_eq((len(calls), target.read_text()), (3, "retried: true\n"),
             "a transient PermissionError on replace is retried")
    os.replace = lambda src, dst: (_ for _ in ()).throw(PermissionError("always held"))
    try:
        yamlio.atomic_write_text(target, "never\n")
    except PermissionError:
        pass
    else:
        raise CaseFailure("a replace that never succeeds must raise")
    finally:
        os.replace = real_replace
    check_eq(sorted(p.name for p in work.iterdir()), ["record.yaml"], "no temp file after retries")


# =========================================================================== case 3
# The holder prints its own PID: on Windows a venv's python.exe is a launcher that runs the
# real interpreter as a child, so Popen.pid is not the process that holds the lock.
HOLDER = ("import os, sys; sys.path.insert(0, sys.argv[1]); from localapp import filelock\n"
          "with filelock.locked(sys.argv[2]):\n"
          "    print('held', os.getpid(), flush=True)\n"
          "    sys.stdin.read()\n")
SYMLINK_SKIP = ("this account cannot create symlinks (Windows needs Developer Mode or an "
                "administrator); the refusal is exercised on CI's Windows runner")


def can_symlink(work: Path) -> bool:
    """True when this process may create a symlink: always on POSIX, and on Windows only with
    Developer Mode or elevation."""
    probe = work / ".symlink-probe"
    try:
        probe.symlink_to(work, target_is_directory=True)
    except OSError:
        return False
    probe.unlink()
    return True


def case_3_file_lock(work: Path) -> str:
    target = work / "ledger.yaml"
    target.write_text("a: 1\n", newline="\n")
    holder = subprocess.Popen([sys.executable, "-c", HOLDER, str(SCRIPTS), str(target)],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        word, _, holder_pid = holder.stdout.readline().strip().partition(" ")
        check_eq(word, "held", "the other process holds the lock")
        try:
            with filelock.locked(target, timeout=0.3):
                raise CaseFailure("the lock was acquired while another process held it")
        except filelock.LockTimeout as exc:
            message = str(exc)
        check(f"process {holder_pid}" in message, f"the timeout names the holder: {message}")
        check("Stop the server" in message and "retry" in message,
              f"the timeout says what to do: {message}")
        threading.Timer(0.5, holder.stdin.close).start()
        started = time.monotonic()
        with filelock.locked(target, timeout=10):
            waited = time.monotonic() - started
            with filelock.locked(target, timeout=0.3):  # nesting in one thread is safe
                pass
        check(waited >= 0.3, f"the lock waited for the holder to finish ({waited:.2f}s)")
    finally:
        holder.kill()
        holder.wait(timeout=10)
    check_eq(filelock.lock_path(target).name, "ledger.yaml.lock", "the lock is a sibling file")

    # A planted `ledger.yaml.lock -> victim` must not let the PID write empty the victim.
    victim = work / "victim.txt"
    victim.write_text("precious\n", newline="\n")
    planted = work / "planted.yaml"
    symlinks = can_symlink(work)
    if symlinks:
        filelock.lock_path(planted).symlink_to(victim)
        try:
            with filelock.locked(planted, timeout=0.3):
                raise CaseFailure("a symlinked lock file was accepted")
        except filelock.LockError as exc:
            check(not isinstance(exc, filelock.LockTimeout), f"refused, not timed out: {exc}")
        check_eq(victim.read_text(), "precious\n", "the symlink target is untouched")
    else:
        print(f"  (symlink checks skipped: {SYMLINK_SKIP})")
    linked = work / "linked.yaml"
    os.link(victim, filelock.lock_path(linked))  # a hard link shares the victim's bytes
    try:
        with filelock.locked(linked, timeout=0.3):
            raise CaseFailure("a hard-linked lock file was accepted")
    except filelock.LockError as exc:
        check(not isinstance(exc, filelock.LockTimeout), f"refused, not timed out: {exc}")
    check_eq(victim.read_text(), "precious\n", "the hard-link target is untouched")
    (work / "real").mkdir()
    if symlinks:
        (work / "alias").symlink_to(work / "real", target_is_directory=True)
        with filelock.locked(work / "real" / "x.yaml", timeout=0.3):
            with filelock.locked(work / "alias" / "x.yaml", timeout=0.3):  # same file, same key
                pass
    if hasattr(os, "mkfifo"):  # POSIX only: Windows has no FIFOs in the file system
        fifo = work / "odd.yaml"
        os.mkfifo(filelock.lock_path(fifo))
        try:
            with filelock.locked(fifo, timeout=0.3):
                raise CaseFailure("a non-regular lock file was accepted")
        except filelock.LockError:
            pass

    # A failed PID write after the flock releases the lock instead of leaking it.
    real_write = os.write
    os.write = lambda fd, data: (_ for _ in ()).throw(OSError("disk full"))
    try:
        with filelock.locked(target, timeout=0.3):
            raise CaseFailure("the lock was held although the PID write failed")
    except OSError:
        pass
    finally:
        os.write = real_write
    with filelock.locked(target, timeout=0.3):  # would time out if the flock had leaked
        pass

    # Force the last-resort fallback: neither the POSIX nor the Windows lock is available.
    real, filelock.fcntl = filelock.fcntl, None
    real_msvcrt, filelock.msvcrt = filelock.msvcrt, None
    try:
        with contextlib.redirect_stderr(io.StringIO()) as err:
            held, release = threading.Event(), threading.Event()

            def hold() -> None:
                with filelock.locked(target):
                    held.set()
                    release.wait(5)
            thread = threading.Thread(target=hold)
            thread.start()
            held.wait(5)
            try:
                with filelock.locked(target, timeout=0.2):
                    raise CaseFailure("the fallback lock let a second thread in")
            except filelock.LockTimeout:
                pass
            release.set()
            thread.join(5)
        check("neither fcntl nor msvcrt is available" in err.getvalue(), "the fallback warns once")
    finally:
        filelock.fcntl = real
        filelock.msvcrt = real_msvcrt

    probe = "records/war_rooms/p--code--a.R/ledger.yaml.lock"
    if shutil.which("git") is None:
        return "git absent: the .gitignore check was skipped"
    ignored = subprocess.run(["git", "check-ignore", "-q", probe], cwd=REPO)
    if ignored.returncode == 128:
        return "not a git checkout: the .gitignore check was skipped"
    check_eq(ignored.returncode, 0, f"{probe} is gitignored")
    return "cross-process contention, timeout, wait, fallback, gitignore"


# =========================================================================== case 4
def case_4_project_root(work: Path) -> None:
    root = work / "proj_x"
    (root / "code").mkdir(parents=True)
    (root / "PROJECT.md").write_text("# X\n", newline="\n")
    (work / "other").mkdir()
    (work / "other" / "PROJECT.md").write_text("# Other\n", newline="\n")

    def refused(fn, fragment: str, what: str) -> None:
        try:
            fn()
        except projroot.ProjectRootError as exc:
            check(fragment in str(exc), f"{what}: {exc} lacks {fragment!r}")
            return
        raise CaseFailure(f"{what}: no ProjectRootError")

    check_eq(projroot.resolve_project_root(str(root), "proj_x"), root.resolve(), "explicit root")
    refused(lambda: projroot.resolve_project_root(str(work / "other"), "proj_x"),
            "does not match", "an explicit root is checked against the id")
    refused(lambda: projroot.resolve_project_root(str(work), "proj_x"),
            "does not contain PROJECT.md", "an explicit root needs PROJECT.md")
    refused(lambda: projroot.resolve_project_root(str(root), "", record="the ledger"),
            "the ledger has no project.id", "the id is required")
    cwd = os.getcwd()
    try:
        os.chdir(root / "code")
        check_eq(projroot.resolve_project_root(None, "proj_x"), root.resolve(), "walk up")
        refused(lambda: projroot.resolve_project_root(None, "proj_y", record="board.yaml"),
                "board.yaml records project.id 'proj_y'", "a walk-up root with another id")
        os.chdir(work)
        refused(lambda: projroot.resolve_project_root(None, "proj_x"), "--project-root",
                "no PROJECT.md at or above the working directory")
    finally:
        os.chdir(cwd)
    projroot.check_project_id(root, "proj_x")
    refused(lambda: projroot.check_project_id(root, "proj_y"), "proj_y", "check_project_id")


# =========================================================================== case 5
def case_5_loopback_server(work: Path) -> None:
    index = work / "index.html"
    index.write_text("<!doctype html><p>app</p>\n", newline="\n")

    class Handler(server.LoopbackHandler):
        static = {"/": (index, "text/html; charset=utf-8")}

        def handle_get(self, route: str) -> None:
            if route == "/api/ping":
                return self.send_json({"ok": True})
            return super().handle_get(route)

        def handle_post(self, route: str, body: bytes) -> None:
            if route != "/api/echo":
                return super().handle_post(route, body)
            payload = self.json_object(body)
            if payload is not None:
                self.send_json({"ok": True, "echo": payload})

    srv = server.LoopbackServer(0, Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        check_eq(srv.server_address[0], "127.0.0.1", "binds loopback only")
        check_eq(srv.url, f"http://127.0.0.1:{srv.port}/", "the printed URL")
        client = testkit.Client(srv.port)
        status, head, body = client.request("GET", "/")
        check_eq((status, body), (200, index.read_bytes()), "the static map serves the app")
        for key, value in server.SECURITY_HEADERS.items():
            check_eq(head.get(key.lower()), value, f"{key} on every response")
        check("script-src 'self'" in head["content-security-policy"]
              and "unsafe-inline" not in head["content-security-policy"].split("style-src")[0],
              "the CSP allows no inline script")
        check_eq(client.request("GET", "/api/ping?x=1")[0], 200, "a query string still routes")
        status, head, _ = client.request("GET", "/nope")
        check_eq((status, "content-security-policy" in head), (404, True), "404 has headers")
        for headers, why in (({"Origin": "http://evil.example"}, "a foreign Origin"),
                             ({"Host": "evil.example"}, "a foreign Host without Origin"),
                             ({"Origin": f"http://127.0.0.1:{srv.port + 1}"}, "another port"),
                             ({"Host": "127.0.0.1:notaport"}, "a malformed Host")):
            check_eq(client.request("GET", "/api/ping", headers=headers)[0], 403, why)
        check_eq(client.request("GET", "/api/ping",
                                headers={"Origin": f"http://localhost:{srv.port}"})[0], 200,
                 "localhost on the bound port is accepted")
        check_eq(client.json("POST", "/api/echo?y=2", {"a": 1}), (200, {"ok": True, "echo": {"a": 1}}),
                 "a JSON POST with the app's Origin")
        check_eq(client.json("POST", "/api/echo", {"a": 1},
                             headers={"Origin": "http://evil.example"})[0], 403,
                 "a foreign Origin cannot write")
        status, _, _ = client.request("POST", "/api/echo", b"x" * (server.MAX_BODY_BYTES + 1),
                                      {"Origin": client.origin})
        check_eq(status, 413, "a body over the cap is refused")
        for raw, why in ((b"{not json", "bad JSON"), (b"[1, 2]", "a JSON array")):
            check_eq(client.request("POST", "/api/echo", raw, {"Origin": client.origin})[0],
                     400, why)
        check_eq(client.request("PUT", "/api/echo", b"{}")[0], 405, "PUT is refused")
        with socket.create_connection(("127.0.0.1", srv.port), timeout=10) as sock:
            sock.sendall(f"POST /api/echo HTTP/1.1\r\nHost: 127.0.0.1:{srv.port}\r\n\r\n".encode())
            check(sock.recv(64).startswith(b"HTTP/1.1 400"), "no Content-Length is a 400")

        # The standard library's own error page (501 for a method no app defines, such as
        # HEAD or OPTIONS) carries the same headers and CSP, exactly once.
        def raw(request: bytes) -> bytes:
            with socket.create_connection(("127.0.0.1", srv.port), timeout=10) as sock:
                sock.sendall(request)
                chunks = []
                while chunk := sock.recv(4096):
                    chunks.append(chunk)
                return b"".join(chunks)

        host = f"Host: 127.0.0.1:{srv.port}\r\nConnection: close\r\n\r\n".encode()
        for request, status in ((b"HEAD / HTTP/1.1\r\n" + host, b"501"),
                                (b"OPTIONS / HTTP/1.1\r\n" + host, b"501"),
                                (b"TRACE / HTTP/1.1\r\n" + host, b"501")):
            reply = raw(request)
            head = reply.split(b"\r\n\r\n", 1)[0].decode("latin-1").lower()
            check(reply.split(b" ", 2)[1] == status, f"{request[:8]!r}: status {status!r}")
            for key, value in server.SECURITY_HEADERS.items():
                check_eq(head.count(f"\r\n{key.lower()}: {value.lower()}"), 1,
                         f"{request[:8]!r}: {key} exactly once on the stdlib error page")
        try:
            server.LoopbackServer(srv.port, Handler).server_close()
        except server.PortInUseError as exc:
            check("already in use" in str(exc) and "--port 0" in str(exc), f"message: {exc}")
        else:
            raise CaseFailure("binding a port in use must raise PortInUseError")
    finally:
        srv.shutdown()
        srv.server_close()

    # A client that connects and sends nothing is dropped after the handler's timeout, so
    # it cannot hold a handler thread for ever.
    timeout = getattr(server.LoopbackHandler, "timeout", None)
    check(isinstance(timeout, (int, float)) and 0 < timeout <= 60,
          f"the handler sets a socket timeout (got {timeout!r})")

    class Quick(Handler):
        timeout = 0.5

    quick = server.LoopbackServer(0, Quick)
    threading.Thread(target=quick.serve_forever, daemon=True).start()
    try:
        with socket.create_connection(("127.0.0.1", quick.port), timeout=10) as sock:
            started = time.monotonic()
            check_eq(sock.recv(64), b"", "an idle connection is closed by the server")
            check(time.monotonic() - started < 5, "and closed promptly after the timeout")
    finally:
        quick.shutdown()
        quick.server_close()

    # No browser under CI, or on Linux with no display, where webbrowser would fall back to
    # a text browser in the agent's own terminal.
    saved = {k: os.environ.get(k) for k in ("CI", "DISPLAY", "WAYLAND_DISPLAY")}
    real_platform = sys.platform
    try:
        for key in saved:
            os.environ.pop(key, None)
        os.environ["CI"] = "true"
        check_eq(server.browser_skip_reason(), "CI is set", "CI skips the browser")
        del os.environ["CI"]
        sys.platform = "linux"
        check(server.browser_skip_reason() and "no display" in server.browser_skip_reason(),
              "headless Linux skips the browser")
        os.environ["WAYLAND_DISPLAY"] = "wayland-0"
        check_eq(server.browser_skip_reason(), None, "a Wayland display allows it")
        sys.platform = "darwin"
        del os.environ["WAYLAND_DISPLAY"]
        check_eq(server.browser_skip_reason(), None, "macOS needs no DISPLAY")
    finally:
        sys.platform = real_platform
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# =========================================================================== case 6
def case_6_lint_and_harness(work: Path) -> None:
    result = lint.LintResult()
    check(result.ok, "an empty result is ok")
    result.fail("WL-03", "b001", "line 4 is in two blocks")
    result.warn("WL-13", None, "whole-file hash changed")
    check_eq((result.ok, result.codes), (False, {"WL-03"}), "failures decide ok and codes")
    check_eq(result.failures[0].line(), "WL-03: b001 line 4 is in two blocks", "finding line")
    check_eq(result.as_dict()["failures"][0],
             {"code": "WL-03", "subject": "b001", "message": "line 4 is in two blocks"},
             "as_dict")
    check_eq(result.warnings[0].line(), "WL-13: whole-file hash changed", "no subject")

    tree = work / "tree"
    (tree / "d").mkdir(parents=True)
    (tree / "d" / "a.txt").write_text("a", newline="\n")
    digest = testkit.tree_digest(tree)
    (tree / "d" / "a.yaml.lock").write_text("123\n", newline="\n")
    (tree / "__pycache__").mkdir()
    check_eq(testkit.tree_digest(tree), digest, "lock files and caches are not fixture content")
    (tree / "d" / "renv.lock").write_text("{}\n", newline="\n")
    check(testkit.tree_digest(tree) != digest, "renv.lock is fixture content, not a record lock")
    digest = testkit.tree_digest(tree)
    (tree / "d" / "b.txt").write_text("b", newline="\n")
    check(testkit.tree_digest(tree) != digest, "a new file changes the digest")


CASES = [
    ("case 1 — YAML byte identity", case_1_byte_identity),
    ("case 2 — YAML load and save", case_2_load_and_save),
    ("case 3 — file lock", case_3_file_lock),
    ("case 4 — project root", case_4_project_root),
    ("case 5 — loopback server", case_5_loopback_server),
    ("case 6 — lint types and harness", case_6_lint_and_harness),
]


def main() -> int:
    """Run each case in its own temporary directory; the fixtures must not change."""
    started = time.monotonic()
    testkit.install_network_guard()
    try:
        testkit.self_test_network_guard()
    except CaseFailure as exc:
        print(f"ENVIRONMENT: {exc}")
        return 2
    before = [testkit.tree_digest(f) for f in (WR_FIXTURES, RB_FIXTURES)]
    failures = 0
    with tempfile.TemporaryDirectory(prefix="localapp-test-") as tmp:
        for index, (name, func) in enumerate(CASES, start=1):
            work = Path(tmp) / f"case{index:02d}"
            work.mkdir()
            try:
                note = func(work)
            except Exception as exc:  # one failing case never stops the rest
                failures += 1
                print(f"FAIL {name}\n  " + (str(exc) if isinstance(exc, CaseFailure)
                                            else traceback.format_exc().rstrip()))
                continue
            print(f"PASS {name}" + (f"  [{note}]" if note else ""))
    if [testkit.tree_digest(f) for f in (WR_FIXTURES, RB_FIXTURES)] != before:
        failures += 1
        print("FAIL the run modified the war-room or review-board fixtures")
    elapsed = time.monotonic() - started
    if elapsed > 60:
        failures += 1
        print(f"FAIL the suite took {elapsed:.1f}s, over its 60s budget")
    print(f"{len(CASES)} cases, {failures} failure(s), {elapsed:.1f}s")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
