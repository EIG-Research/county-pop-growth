#!/usr/bin/env python3
"""End-to-end test suite for the code war room (Workstream F, D8).

Runs the whole war-room toolchain -- `war_room_prep.py`, `war_room_lint.py`,
`war_room_server.py`, `war_room_reconcile.py`, `war_room_render.py`, and the shared
`war_room_lib.py` -- against the synthetic fixtures in
`Infrastructure/scripts/war_room_fixtures/`, with no model in the loop and no network.
It is the `war-room-tests` maintenance check: `make war-room-test`, or
`python3 Infrastructure/scripts/test_war_room.py` from anywhere.

Thirteen cases, one `PASS` line each:

    1  Full path on sample.R      prep -> server -> reconcile -> render, lint green throughout
    2  Divergence handoff          the needs-agent list, the classification, then reconciled
    3  Resume and project namespace  slug lookup, second reviewer, root-mismatch refusals
    4  Drift and regression        an edited block, a relocated block, the WR-A4 signal
    5  Merge and split             through the CLI and the API, and the refusals
    6  Lint matrix and immutability  WL-01..WL-14 one at a time; predictions never change
    7  Concurrency and origin      twenty simultaneous answers; the four origin cases
    8  Starter pipeline            a frozen copy pinned; a live run_all.R partition-checked
    9  WR-A1 golden hashes         LF, CRLF, a lone CR, and no final newline, pinned
   10  Duplicate content           no re-anchor onto another block; accept restores lint
   11  Open constructs             a blank line inside a construct stays in its block;
                                   an old ledger still lints; docstring equals reference
   12  Ledger lock                 a CLI and the server wait for the lock; file mode and
                                   ledger bytes kept
   13  App security                no inline script; CSP on every response; origin, body
                                   cap, traversal, query-string routing, port in use

What the suite guarantees about itself:

  - **It writes nothing it does not own.** Every ledger, every copy of a fixture project,
    and every rendered artifact goes to one temporary directory that is removed at the
    end. The fixtures directory is read-only here: a recursive sha256 digest of it is
    printed before and after and the two must match (AC-T3).
  - **It touches no network.** `socket.socket.connect` is wrapped for the duration and
    raises on any address that is not loopback, so an accidental fetch fails the suite
    rather than making it slow and non-hermetic (AC-T4). The guard is self-tested.
  - **It is fast.** Wall-clock time is printed and anything over 120 seconds fails
    (AC-T4).
  - **Its fixtures are labelled.** Every ledger under the fixtures directory must carry
    `session.fixture: true`, so fixture prose can never be read as an agent's account of
    real code (completion rule 9 of the hardening plan).

Every server is started on an ephemeral port (`--port 0`, with the bound port read back
from the server's own startup line) and killed in a `finally`, so a failing assertion
never leaves a listener behind.

Exit codes: 0 every case passed; 1 a case failed; 2 the environment is unusable.

Dependencies: Python 3.11+ and PyYAML. Nothing else.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import html as htmllib
import http.client
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterable

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent.parent
FIXTURES = SCRIPTS / "war_room_fixtures"

sys.path.insert(0, str(SCRIPTS))

try:
    import war_room_lib as wr  # noqa: E402
    import war_room_lint as wl  # noqa: E402
except SystemExit as exc:  # PyYAML missing
    print(f"ENVIRONMENT: {exc}")
    raise SystemExit(2)

PREP = SCRIPTS / "war_room_prep.py"
LINT = SCRIPTS / "war_room_lint.py"
SERVER = SCRIPTS / "war_room_server.py"
RECONCILE = SCRIPTS / "war_room_reconcile.py"
RENDER = SCRIPTS / "war_room_render.py"

TIME_LIMIT_SECONDS = 120.0

# Case 8 segments a frozen copy of the template's starter pipeline, so the case never
# depends on the live `code/run_all.R`, which a derived project rewrites. The copy is
# pinned by hash and by its expected block ranges; a segmentation change that moves a
# boundary updates STARTER_BLOCKS in the same commit.
STARTER = FIXTURES / "code" / "run_all_starter.R"
STARTER_SHA256 = "745d9da24a53f865d141ed43b5d40c148ed7780c0a6c8369e455dd6cde0dc81d"
# Two blocks moved with the WR-S7 amendment: the `for` loop (40-53) keeps the blank line
# inside its braces, and the `tryCatch(` call (117-198) keeps the blank lines inside its
# parentheses; the pre-amendment ranges are pinned in case 11.
STARTER_BLOCKS = [
    [1, 4], [6, 8], [10, 12], [14, 17], [19, 24], [26, 28], [30, 32], [34, 38], [40, 53],
    [55, 57], [59, 72], [74, 77], [79, 82], [84, 86], [88, 89], [91, 93], [95, 97],
    [99, 103], [105, 111], [113, 115], [117, 198],
]

# The six fixture scripts and the language each must be detected as (AC-A5, spec M23).
FIXTURE_SCRIPTS = {
    "code/sample.R": "R",
    "code/sample.Rmd": "R",
    "code/sample.qmd": "R",
    "code/sample.py": "Python",
    "code/sample.do": "Stata",
    "code/sample.ado": "Stata",
}


# =========================================================================== assertions
class CaseFailure(AssertionError):
    """One assertion inside one case."""


def check(condition: Any, message: str) -> None:
    if not condition:
        raise CaseFailure(message)


def check_eq(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise CaseFailure(f"{message}\n    expected: {expected!r}\n    actual:   {actual!r}")


def check_in(needle: str, haystack: str, message: str) -> None:
    if needle not in haystack:
        excerpt = haystack if len(haystack) < 1200 else haystack[:1200] + " ..."
        raise CaseFailure(f"{message}\n    looked for: {needle!r}\n    in: {excerpt}")


# =========================================================================== no network
class NetworkBlocked(RuntimeError):
    """A connect to something that is not loopback. The suite is hermetic (AC-T4)."""


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "ip6-localhost"})


def _address_is_loopback(address: Any) -> bool:
    # A str/bytes address is an AF_UNIX path: local by construction, never a network hop.
    if isinstance(address, (str, bytes, os.PathLike)):
        return True
    if isinstance(address, tuple) and address:
        host = str(address[0])
        return host in _LOOPBACK_HOSTS or host.startswith("127.")
    return False


def install_network_guard() -> None:
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def guard(func: Callable) -> Callable:
        def wrapper(self, address, *args, **kwargs):
            if not _address_is_loopback(address):
                raise NetworkBlocked(
                    f"the war-room suite made a non-loopback connection to {address!r}; "
                    f"every case must run offline (AC-T4)")
            return func(self, address, *args, **kwargs)
        return wrapper

    socket.socket.connect = guard(real_connect)          # type: ignore[assignment]
    socket.socket.connect_ex = guard(real_connect_ex)    # type: ignore[assignment]


def self_test_network_guard() -> None:
    """AC-T4: prove the guard bites before trusting it for the rest of the run."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect(("93.184.216.34", 80))  # a literal IP, so no DNS lookup happens
    except NetworkBlocked:
        return
    except OSError as exc:  # pragma: no cover - the guard should have fired first
        raise CaseFailure(f"the network guard did not fire; the socket layer did ({exc})")
    finally:
        sock.close()
    raise CaseFailure("the network guard did not fire on a non-loopback connect")


# =========================================================================== digests
def tree_digest(root: Path) -> str:
    """One sha256 over every path and every byte under `root`, in sorted path order."""
    digest = hashlib.sha256()
    for path in sorted(Path(root).rglob("*")):
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        if path.is_file():
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


# =========================================================================== subprocess
class Run:
    """One finished subprocess, with its output already decoded."""

    def __init__(self, proc: subprocess.CompletedProcess) -> None:
        self.code = proc.returncode
        self.out = proc.stdout or ""
        self.err = proc.stderr or ""

    @property
    def text(self) -> str:
        return self.out + self.err

    def __repr__(self) -> str:  # shown inside a failure message
        return f"<exit {self.code}>\n{self.text}"


def run(args: Iterable[Any], cwd: Path | None = None, expect: int | None = 0) -> Run:
    proc = subprocess.run(
        [str(a) for a in args], cwd=str(cwd or REPO), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
    result = Run(proc)
    if expect is not None and result.code != expect:
        raise CaseFailure(
            f"expected exit {expect} from {' '.join(str(a) for a in args)}, "
            f"got {result.code}\n{result.text}")
    return result


def prep(*args: Any, cwd: Path | None = None, expect: int | None = 0) -> Run:
    return run([sys.executable, PREP, *args], cwd=cwd, expect=expect)


def lint(ledger: Path, project_root: Path | None = None, cwd: Path | None = None,
         expect: int | None = 0, as_json: bool = False) -> Run:
    args: list[Any] = [sys.executable, LINT, ledger]
    if project_root is not None:
        args += ["--project-root", project_root]
    if as_json:
        args.append("--json")
    return run(args, cwd=cwd, expect=expect)


def lint_codes(ledger: Path, project_root: Path | None = None) -> set[str]:
    """The set of failure codes lint emits, for the WL matrix (AC-B8)."""
    result = lint(ledger, project_root, expect=None, as_json=True)
    payload = json.loads(result.out)
    return {f["code"] for f in payload["failures"]}


def lint_green(ledger: Path, project_root: Path | None, where: str) -> None:
    result = lint(ledger, project_root, expect=None)
    check(result.code == 0, f"lint should be green {where}, but it said:\n{result.text}")


def reconcile(ledger: Path, project_root: Path | None = None, write: bool = False,
              allow_incomplete: bool = False, cwd: Path | None = None,
              expect: int | None = 0) -> Run:
    args: list[Any] = [sys.executable, RECONCILE, "--ledger", ledger]
    if project_root is not None:
        args += ["--project-root", project_root]
    if write:
        args.append("--write")
    if allow_incomplete:
        args.append("--allow-incomplete")
    return run(args, cwd=cwd, expect=expect)


def render(subcommand: str, ledger: Path, out: Path, project_root: Path | None = None,
           expect: int | None = 0) -> Run:
    args: list[Any] = [sys.executable, RENDER, subcommand, ledger, "--out", out]
    if project_root is not None:
        args += ["--project-root", project_root]
    return run(args, expect=expect)


# =========================================================================== the app
class Client:
    """An HTTP client for one running war-room server, on loopback only."""

    def __init__(self, port: int) -> None:
        self.port = port

    def request(self, method: str, path: str, body: Any = None,
                headers: dict[str, str] | None = None) -> tuple[int, Any]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            payload = None if body is None else json.dumps(body).encode("utf-8")
            head = dict(headers or {})
            if payload is not None:
                head.setdefault("Content-Type", "application/json")
            conn.request(method, path, body=payload, headers=head)
            response = conn.getresponse()
            raw = response.read().decode("utf-8")
            try:
                parsed: Any = json.loads(raw)
            except json.JSONDecodeError:
                parsed = raw
            return response.status, parsed
        finally:
            conn.close()

    # -- convenience ---------------------------------------------------------------
    def state(self) -> dict:
        status, payload = self.request("GET", "/api/state")
        check_eq(status, 200, "GET /api/state should return 200")
        return payload

    def index(self) -> str:
        """The served page and the script it loads, since the markup is built in app.js."""
        parts = []
        for path in ("/", "/app.js"):
            status, payload = self.request("GET", path)
            check_eq(status, 200, f"GET {path} should return 200")
            parts.append(payload if isinstance(payload, str) else json.dumps(payload))
        return "\n".join(parts)

    def answer(self, block_id: str, disposition: str, reviewer: str = "bglasner",
               role: str = "author", endorsed: bool = False, flagged: bool = False,
               meant: str = "", why: str = "", carried: Iterable[str] = (),
               expect_ok: bool | None = True) -> dict:
        payload = {
            "block_id": block_id,
            "disposition": disposition,
            "endorsed_prediction": endorsed,
            "flagged": flagged,
            "reviewer": reviewer,
            "reviewer_role": role,
            "author": {
                "meant_to_do": meant,
                "why_this_way": why,
                "assumptions_carried": list(carried),
            },
        }
        status, out = self.request("POST", "/api/answer", payload)
        check_eq(status, 200, f"POST /api/answer for {block_id} should return 200")
        if expect_ok is not None:
            check_eq(bool(out.get("ok")), expect_ok,
                     f"POST /api/answer for {block_id}: unexpected ok flag ({out})")
        return out

    def fast_forward(self, block_ids: Iterable[str], reviewer: str = "bglasner",
                     role: str = "author", expect_ok: bool | None = True) -> dict:
        payload = {"block_ids": list(block_ids), "reviewer": reviewer,
                   "reviewer_role": role}
        status, out = self.request("POST", "/api/fast-forward", payload)
        check_eq(status, 200, "POST /api/fast-forward should return 200")
        if expect_ok is not None:
            check_eq(bool(out.get("ok")), expect_ok,
                     f"POST /api/fast-forward: unexpected ok flag ({out})")
        return out

    def segment(self, op: str, block_id: str, at_line: int | None = None,
                reviewer: str = "bglasner", expect_ok: bool | None = True) -> dict:
        payload: dict[str, Any] = {"op": op, "block_id": block_id, "reviewer": reviewer}
        if at_line is not None:
            payload["at_line"] = at_line
        status, out = self.request("POST", "/api/segment", payload)
        check_eq(status, 200, "POST /api/segment should return 200")
        if expect_ok is not None:
            check_eq(bool(out.get("ok")), expect_ok,
                     f"POST /api/segment {op} {block_id}: unexpected ok flag ({out})")
        return out


_PORT_LINE = re.compile(r"http://127\.0\.0\.1:(\d+)/")


@contextmanager
def server(ledger: Path, project_root: Path | None = None, cwd: Path | None = None,
           extra: Iterable[str] = ()):
    """Start the app on an ephemeral port, hand back a client, and always kill it."""
    args: list[str] = [sys.executable, str(SERVER), "--ledger", str(ledger), "--port", "0",
                       "--no-browser", *extra]
    if project_root is not None:
        args += ["--project-root", str(project_root)]
    proc = subprocess.Popen(args, cwd=str(cwd or REPO), text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    port = None
    startup: list[str] = []
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            line = proc.stdout.readline() if proc.stdout else ""
            if not line:
                break
            startup.append(line)
            match = _PORT_LINE.search(line)
            if match:
                port = int(match.group(1))
                break
        if port is None:
            raise CaseFailure(
                f"the server never printed its port for {ledger}:\n{''.join(startup)}")
        yield Client(port)
    finally:
        proc.kill()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:  # pragma: no cover
            pass
        if proc.stdout:
            proc.stdout.close()


# =========================================================================== fixtures
def copy_project(name: str, into: Path, as_name: str | None = None) -> Path:
    """A writable copy of a fixture project. The fixtures themselves are never touched."""
    target = Path(into) / (as_name or name)
    shutil.copytree(FIXTURES / name, target)
    return target


def ledger_path(root: Path, project_id: str, script: str) -> Path:
    """The D1 location: `<war_rooms>/<project.id>--<script path with -- separators>/`."""
    return Path(root) / wr.slug_for(project_id, script) / "ledger.yaml"


def build_ledger(project: Path, script: str, out: Path, mode: str = "ordered",
                 finalize: bool = True, fill: bool = True) -> Path:
    """skeleton -> fill -> finalize, the sequence the skill instructs (D6)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    prep("skeleton", project / script, "--project-root", project, "--out", out,
         "--mode", mode, "--fixture")
    if fill:
        fill_predictions(out)
    if finalize:
        prep("finalize", out)
    return out


def fill_predictions(path: Path, density: str = "low", confidence: str = "medium") -> None:
    """Synthetic titles and predictions, for the cases that do not need fixture prose.

    Case 1 uses the committed fixture prediction set through `war_room_prep.py fill`;
    every other case only needs prep to be *complete*, so it is filled here rather than
    growing the fixtures directory for each new case.
    """
    led = wr.load_ledger(path)
    for block in led.get("blocks") or []:
        bid = block["block_id"]
        block["title"] = f"Synthetic block {bid}"
        block["density"] = density
        block["prediction"] = {
            "what_it_does": f"Synthetic fixture reading of {bid}. Not a real analysis.",
            "inferred_intent": f"Synthetic fixture intent for {bid}.",
            "assumptions": [f"Synthetic assumption recorded for {bid}."],
            "confidence": confidence,
        }
    wr.save_ledger(path, led)


def record_answer(path: Path, block_id: str, disposition: str, reviewer: str = "bglasner",
                  role: str = "author", endorsed: bool = False, meant: str = "",
                  why: str = "", carried: Iterable[str] = (), at: str | None = None) -> None:
    """Save one answer exactly as the server would, without starting one.

    The server is exercised directly by cases 1, 3, 4, 5 and 7. The remaining cases need
    a *dispositioned ledger* rather than a walkthrough, and paying for an HTTP round trip
    per block would buy nothing the other cases have not already proved.
    """
    led = wr.load_ledger(path)
    block = wr.find_block(led, block_id)
    check(block is not None, f"no block {block_id} in {path}")
    carried = [c for c in carried if c.strip()]
    has_text = bool(meant.strip() or why.strip() or carried)
    if has_text:
        endorsed = False
        block["author_account"] = {"meant_to_do": meant, "why_this_way": why,
                                   "assumptions_carried": list(carried)}
        block["discussed"] = True
    elif endorsed:
        block["author_account"] = None
        block["discussed"] = True
    now = at or wr.utc_now()
    block["endorsed_prediction"] = endorsed
    block["disposition"] = disposition
    block["reviewer"] = reviewer
    block["answered_at"] = now
    block.setdefault("divergence", {"match": None, "type": None, "detail": None})
    session = led.setdefault("session", {})
    reviewers = session.setdefault("reviewers", [])
    if not any(isinstance(r, dict) and r.get("id") == reviewer for r in reviewers):
        reviewers.append({"id": reviewer, "role": role})
    history = session.setdefault("history", [])
    if not any(isinstance(h, dict) and h.get("event") == "walkthrough"
               and h.get("by") == reviewer and str(h.get("at", ""))[:10] == now[:10]
               for h in history):
        history.append({"event": "walkthrough", "at": now, "by": reviewer})
    wr.save_ledger(path, led)


def set_divergence(path: Path, block_id: str, match: bool, type_: str, detail: str) -> None:
    """The agent's reconcile-phase classification, applied by the test as a fixture."""
    led = wr.load_ledger(path)
    block = wr.find_block(led, block_id)
    check(block is not None, f"no block {block_id} in {path}")
    block["divergence"] = {"match": match, "type": type_, "detail": detail}
    wr.save_ledger(path, led)


def predictions_of(path: Path) -> dict[str, Any]:
    """Every `prediction` mapping, keyed by block id (WR-P3, AC-A8)."""
    led = wr.load_ledger(path)
    return {b["block_id"]: b.get("prediction") for b in led.get("blocks") or []}


def non_blank_lines(path: Path) -> set[int]:
    return {i for i, line in enumerate(wr.wr_a1_lines(path), start=1) if line.strip()}


def coverage_of(led: dict) -> list[int]:
    covered: list[int] = []
    for block in led.get("blocks") or []:
        start, end = int(block["lines"][0]), int(block["lines"][1])
        covered.extend(range(start, end + 1))
    return covered


# =========================================================================== case 1
CASE1: dict[str, Any] = {}


def case_1_full_path(work: Path) -> None:
    """Prep, walkthrough, reconcile, render -- the whole path, lint green at every step.

    Covers AC-A1, AC-A2, AC-A4, AC-A5, AC-B1, AC-B2, AC-B4, AC-B5, AC-B6, AC-B7,
    AC-B11, AC-B12, AC-B13 (CV half), AC-C1, AC-C2, AC-C3, AC-C5, AC-C6, AC-D1, AC-D2,
    and the first half of the WR-P3 evidence AC-A8 checks in case 6.
    """
    project = copy_project("proj_a", work)
    war_rooms = work / "war_rooms"
    led_path = ledger_path(war_rooms, "proj_a", "code/sample.R")
    led_path.parent.mkdir(parents=True, exist_ok=True)

    # -- AC-A1: three skeletons of one script differ only in `session.created` ---------
    texts = []
    for i in range(3):
        out = work / f"determinism-{i}.yaml"
        prep("skeleton", project / "code/sample.R", "--project-root", project,
             "--out", out, "--fixture")
        texts.append(re.sub(r"(?m)^  created: .*$", "  created: <date>",
                            out.read_text(encoding="utf-8")))
    check_eq(len(set(texts)), 1,
             "AC-A1: three skeleton runs on one script must be byte-identical apart "
             "from session.created")

    # -- AC-A2: an LF copy and a CRLF copy hash identically ---------------------------
    # Both variants are built here from normalized bytes rather than from the checkout,
    # because the checkout's terminators depend on the machine: under
    # `core.autocrlf=true` the fixture arrives as CRLF, and converting that again would
    # produce `\r\r\n` instead of CRLF. Each variant is asserted to be what its name says,
    # so this check can never silently compare CRLF against CRLF.
    lf_bytes = (project / "code/sample.R").read_bytes().replace(b"\r\n", b"\n")
    crlf_bytes = lf_bytes.replace(b"\n", b"\r\n")
    check(b"\n" in lf_bytes and b"\r" not in lf_bytes,
          "AC-A2: the LF variant must contain LF terminators and no CR")
    check(crlf_bytes.count(b"\r\n") == lf_bytes.count(b"\n") and b"\r\r" not in crlf_bytes,
          "AC-A2: the CRLF variant must terminate every line with exactly one CRLF")
    variants: dict[str, dict] = {}
    for name, data in (("lf", lf_bytes), ("crlf", crlf_bytes)):
        variant_project = copy_project("proj_a", work / f"eol-{name}")
        variant_script = variant_project / "code/sample.R"
        variant_script.write_bytes(data)
        variant_out = work / f"eol-{name}.yaml"
        prep("skeleton", variant_script, "--project-root", variant_project,
             "--out", variant_out, "--fixture")
        variants[name] = wr.load_ledger(variant_out)
    lf_led, crlf_led = variants["lf"], variants["crlf"]
    check_eq([b["sha256"] for b in crlf_led["blocks"]],
             [b["sha256"] for b in lf_led["blocks"]],
             "AC-A2: block hashes must not depend on the line terminator")
    check_eq(crlf_led["script"]["sha256"], lf_led["script"]["sha256"],
             "AC-A2: the whole-file hash must not depend on the line terminator")
    # The checkout itself, whatever terminators it arrived with, hashes the same too.
    checkout_led = wr.load_ledger(work / "determinism-0.yaml")
    check_eq([b["sha256"] for b in checkout_led["blocks"]],
             [b["sha256"] for b in lf_led["blocks"]],
             "AC-A2: the checked-out fixture must hash like its LF form")

    # -- AC-A5: every fixture script segments cleanly and is typed correctly ----------
    for script, language in FIXTURE_SCRIPTS.items():
        out = work / f"lang-{Path(script).suffix.lstrip('.')}.yaml"
        prep("skeleton", project / script, "--project-root", project, "--out", out,
             "--fixture")
        led = wr.load_ledger(out)
        check_eq(led["script"]["language"], language,
                 f"AC-A5: {script} must be detected as {language}")
        covered = coverage_of(led)
        wanted = non_blank_lines(project / script)
        missing = sorted(wanted - set(covered))
        doubled = sorted({i for i in covered if covered.count(i) > 1} & wanted)
        check(not missing, f"AC-A5: {script} leaves non-blank line(s) {missing} in no block")
        check(not doubled, f"AC-A5: {script} covers line(s) {doubled} more than once")
        check(led["blocks"], f"AC-A5: {script} produced no blocks at all")

    # -- prep the real ledger ----------------------------------------------------------
    # WR-C2 / D5: batch confirmation is a fast-forward-mode act, and case 1 exercises it,
    # so the session it walks through is a fast-forward one. The block-map screen is
    # unconditional in both modes, which is what the `needs_block_map` checks below assert.
    prep("skeleton", project / "code/sample.R", "--project-root", project,
         "--out", led_path, "--mode", "fast-forward", "--fixture")
    lint_green(led_path, project, "on a fresh skeleton")
    prep("fill", led_path, FIXTURES / "predictions/proj_a--code--sample.R.yaml")
    lint_green(led_path, project, "on a filled skeleton")

    # -- AC-A4: finalize refuses an incomplete prep and stamps a complete one ----------
    incomplete = work / "incomplete.yaml"
    incomplete.write_bytes(led_path.read_bytes())
    broken = wr.load_ledger(incomplete)
    broken["blocks"][2]["prediction"]["what_it_does"] = ""
    wr.save_ledger(incomplete, broken)
    refused = prep("finalize", incomplete, expect=1)
    check_in("REFUSED", refused.text, "AC-A4: finalize must refuse an incomplete prep")
    check(not (wr.load_ledger(incomplete).get("session") or {}).get("prep_completed"),
          "AC-A4: a refused finalize must not stamp prep_completed")

    check(not (wr.load_ledger(led_path).get("session") or {}).get("prep_completed"),
          "AC-A4: prep_completed must be absent before finalize")
    prep("finalize", led_path)
    led = wr.load_ledger(led_path)
    check(led["session"].get("prep_completed"),
          "AC-A4: prep_completed must be present after finalize")
    history = led["session"]["history"]
    check_eq([h["event"] for h in history], ["prep"],
             "AC-A4/D10: finalize appends exactly one prep history entry")
    prep_completed = led["session"]["prep_completed"]
    lint_green(led_path, project, "on a finalized ledger")

    # -- AC-A3 (clean half): verify reproduces every hash -------------------------------
    verified = prep("verify", led_path, "--project-root", project)
    check_in("OK: every block hash reproduces", verified.text,
             "verify must be clean on a fresh ledger")

    CASE1["predictions_after_finalize"] = predictions_of(led_path)

    # -- the walkthrough ----------------------------------------------------------------
    with server(led_path, project) as app:
        # AC-B13 (CV half): the block map is markup in the served page and state.
        index = app.index()
        check_in('id: "block-map"', index, "AC-B13: the served page must build the block map")
        check_in("Begin walkthrough", index,
                 "AC-B13: the block map must offer a way into the walkthrough")
        check_in("needs_block_map", index,
                 "AC-B13: the page must read needs_block_map from state")
        state = app.state()
        check_eq(state["needs_block_map"], True,
                 "AC-B13: a ledger with no dispositions needs the block map")
        check_eq(state["session"]["mode"], "fast-forward",
                 "session.mode must reach the app")

        # AC-B6: fast-forward refuses high density and low confidence.
        refusal = app.fast_forward(["b004"], expect_ok=False)
        check_in("density is high", refusal["error"],
                 "AC-B6: a high-density block is never fast-forwarded (WR-C4)")
        refusal = app.fast_forward(["b006"], expect_ok=False)
        check_in("confidence is low", refusal["error"],
                 "AC-B6: a low-confidence block is never fast-forwarded (WR-C4)")

        # b001: a clean endorsement.
        app.answer("b001", "confirmed", endorsed=True)
        state = app.state()
        b001 = next(b for b in state["blocks"] if b["block_id"] == "b001")
        check_eq(b001["endorsed_prediction"], True,
                 "AC-B4: state must report an endorsed block as endorsed")

        # AC-B6: and it refuses a block that already carries a disposition.
        refusal = app.fast_forward(["b001"], expect_ok=False)
        check_in("already carries disposition", refusal["error"],
                 "AC-B6: a dispositioned block is never fast-forwarded")

        # AC-B1: endorsement paired with anything but `confirmed` is refused outright.
        before = led_path.read_bytes()
        rejected = app.answer("b002", "misread-by-agent", endorsed=True, expect_ok=False)
        check_in("WR-Q7", rejected["error"],
                 "AC-B1: the refusal must cite the endorsement rule")
        check_eq(led_path.read_bytes(), before,
                 "AC-B1: a refused endorsement must leave the ledger byte-identical")
        app.answer("b002", "confirmed", endorsed=True)

        # AC-B2: endorsement plus author text is stored as an account, not an endorsement.
        app.answer("b003", "confirmed", endorsed=True,
                   meant="Read the extract, but only the columns the codebook lists.",
                   why="The full file is too wide to read in one pass.")
        stored = wr.find_block(wr.load_ledger(led_path), "b003")
        check_eq(stored["endorsed_prediction"], False,
                 "AC-B2: author text clears the endorsement (WR-Q7)")
        check(stored["author_account"]["meant_to_do"],
              "AC-B2: the author's account must be stored")

        # The three dispositions that carry the session's substance.
        app.answer("b004", "needs-change",
                   meant="Restrict to prime-age workers, which we define as 25 to 54.",
                   why="We copied the lower bound from an older script and never added "
                       "the upper one.",
                   carried=["Downstream tabulations assume nobody under 25 remains."],
                   flagged=True)
        app.answer("b005", "misread-by-agent",
                   meant="The helper is a share, not a rate.",
                   why='Legacy naming. <script>alert("xss")</script> stayed in a comment.')
        app.answer("b006", "unresolved",
                   meant="Whether dropping missing wages is the intended treatment.",
                   why="The data codebook, which is not in the room.")
        app.answer("b007", "confirmed", endorsed=True, reviewer="rlee", role="fresh-eyes")

        # AC-B12: the exact payload the client sends back for an endorsed block.
        state = app.state()
        b001 = next(b for b in state["blocks"] if b["block_id"] == "b001")
        app.answer("b001", b001["disposition"], endorsed=b001["endorsed_prediction"],
                   flagged=not b001["flagged"], meant=b001["author"]["meant_to_do"],
                   why=b001["author"]["why_this_way"],
                   carried=b001["author"]["assumptions_carried"])
        stored = wr.find_block(wr.load_ledger(led_path), "b001")
        check_eq(stored["endorsed_prediction"], True,
                 "AC-B12: a round-tripped endorsement must survive unchanged")

        # WR-C2: the same batch on an ordered session is refused, and saves nothing.
        ordered_led = work / "ordered/ledger.yaml"
        build_ledger(project, "code/sample.R", ordered_led, mode="ordered")
        before = ordered_led.read_bytes()
        with server(ordered_led, project) as ordered_app:
            check_eq(ordered_app.state()["session"]["mode"], "ordered",
                     "the second ledger must be an ordered session")
            refusal = ordered_app.fast_forward(["b008"], expect_ok=False)
            check_in("fast-forward", refusal["error"],
                     "WR-C2: the refusal must say the session is not in fast-forward mode")
        check_eq(ordered_led.read_bytes(), before,
                 "WR-C2: a refused batch confirmation must save nothing")

        # AC-B6: the batch path, on the one block that qualifies.
        out = app.fast_forward(["b008"])
        check_eq(out.get("confirmed"), ["b008"], "AC-B6: b008 must batch-confirm")
        stored = wr.find_block(wr.load_ledger(led_path), "b008")
        check_eq(stored["discussed"], False,
                 "AC-B6: a fast-forwarded block is recorded as not discussed (WR-C3)")
        check_eq(stored["endorsed_prediction"], True,
                 "AC-B6: batch confirmation endorses the recorded prediction (WR-Q8)")

        state = app.state()
        check_eq(state["needs_block_map"], False,
                 "AC-B13: the block map is done once every block has a disposition")

    led = wr.load_ledger(led_path)
    # AC-B5: every answer is stamped, and after prep.
    for block in led["blocks"]:
        check(block["answered_at"] > prep_completed,
              f"AC-B5: {block['block_id']} answered_at must be later than prep_completed")
    # AC-B11 / D12: both reviewers are registered with their roles.
    check_eq(led["session"]["reviewers"],
             [{"id": "bglasner", "role": "author"}, {"id": "rlee", "role": "fresh-eyes"}],
             "AC-B11: session.reviewers[] carries one {id, role} per reviewer")
    check_eq([h["event"] for h in led["session"]["history"]],
             ["prep", "walkthrough", "walkthrough"],
             "D10: one walkthrough entry per reviewer per UTC date")
    lint_green(led_path, project, "after the walkthrough")
    CASE1["predictions_after_server"] = predictions_of(led_path)

    # -- reconcile: the needs-agent path, then the classification -----------------------
    first = reconcile(led_path, project, write=True)
    check_in("NEEDS AGENT JUDGMENT", first.text,
             "reconcile must hand the written accounts back for classification")
    check_in("Post-write lint: clean", first.text, "AC-D5: post-write lint must run and pass")
    led = wr.load_ledger(led_path)
    check(not led["session"].get("reconciled"),
          "AC-D5: session.reconciled stays unset while blocks need judgment")

    # AC-B7: a fast-forwarded block's assumptions are exported as confirmed (WR-Q8).
    exported = [a for a in led["assumption_export"] if a["block_id"] == "b008"]
    check(exported, "AC-B7: a fast-forwarded block must export its assumptions")
    for item in exported:
        check_eq((item["stated_by"], item["confirmed"]), ("agent", True),
                 "AC-B7: batch-endorsed assumptions are agent-stated and confirmed")

    # AC-D1 / AC-D2: the work order counts its items and cites no absolute path.
    work_order = (led_path.parent / "work-order.md").read_text(encoding="utf-8")
    check_in("**Items:** 1 actionable, 1 blocked", work_order,
             "AC-D1: the header counts are computed, not hard-coded")
    check_in("## Blocked Items", work_order, "AC-D1: an unresolved block gets a blocked row")
    check_in("| **Blocked on** |", work_order, "AC-D1: a blocked item carries its blocker")
    rules = "".join((REPO / "Infrastructure/rules" / name).read_text(encoding="utf-8")
                    for name in ("code-war-room-rules.md", "code-war-room-design.md"))
    check_eq(rules.count("rendered as `blocked`"), 1,
             "AC-D1: WR-O4 must state the blocked-item rule exactly once")
    absolute = re.compile(r"(^/|/Users/|/home/|[A-Z]:\\)", re.MULTILINE)
    hit = absolute.search(work_order)
    check(hit is None,
          f"AC-D2: the work order must carry no absolute path (found {hit.group(0) if hit else ''!r})")

    for bid, dtype, detail in (
        ("b003", "incomplete-intent", "The author reads a column subset the prediction "
                                      "did not mention."),
        ("b004", "wrong-intent", "The prediction missed the intended upper bound."),
        ("b005", "wrong-mechanics", "The agent read a rate where the author wrote a share."),
        ("b006", "author-uncertain", "The author could not say without the codebook."),
    ):
        set_divergence(led_path, bid, False, dtype, detail)
    second = reconcile(led_path, project, write=True)
    check_in("Post-write lint: clean", second.text, "the second reconcile must lint clean")
    led = wr.load_ledger(led_path)
    check(led["session"].get("reconciled"),
          "session.reconciled is set once every account is classified")
    check_eq([h["event"] for h in led["session"]["history"]].count("reconcile"), 1,
             "D10: exactly one reconcile history entry")
    lint_green(led_path, project, "after reconcile --write")
    CASE1["predictions_after_reconcile"] = predictions_of(led_path)

    # -- render -------------------------------------------------------------------------
    reports = project / "review-reports/war-room"
    before_listing = sorted(p.name for p in reports.iterdir()) if reports.is_dir() else []
    check_eq(before_listing, [],
             "WR-X4: the reviewed project must hold no war-room report before the render")
    md_path = led_path.parent / "ledger.md"
    html_path = reports / f"{wr.slug_for('proj_a', 'code/sample.R')}-war-room.html"
    render("md", led_path, md_path, project)
    render("html", led_path, html_path, project)
    md = md_path.read_text(encoding="utf-8")
    html = html_path.read_text(encoding="utf-8")

    # AC-C1: every block id in file order, every prediction verbatim.
    order = [b["block_id"] for b in led["blocks"]]
    positions = [md.index(f"### {bid} ") for bid in order]
    check_eq(positions, sorted(positions), "AC-C1: ledger.md lists blocks in file order")
    for block in led["blocks"]:
        check_in(block["prediction"]["what_it_does"], md,
                 f"AC-C1: {block['block_id']}'s prediction must render verbatim")

    # AC-C2: nothing unfilled, nothing unescaped, one card per block, prediction first.
    comment_free = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
    check("{{" not in comment_free, "AC-C2: no placeholder may survive into the report")
    check("BEGIN " not in html and "END " not in html,
          "AC-C2: the repeat markers must be stripped from the output")
    cards = html.count('<div class="block ')
    check_eq(cards, len(led["blocks"]), "AC-C2: one card per block")
    check_in("&lt;script&gt;", html, "AC-C2: author text must be HTML-escaped")
    check('<script>alert("xss")' not in html,
          "AC-C2: a script tag from an author field must never render live")
    discussed = {b["block_id"]: bool(b.get("discussed")) for b in led["blocks"]}
    for chunk in html.split('<div class="block ')[1:]:
        found = re.search(r'block-id">(b\d+[ab]?)<', chunk)
        check(found is not None, "AC-C2: every card must name its block")
        bid = found.group(1)
        has_pane = '<div class="pane account">' in chunk
        # WRR-2: the author pane is emitted for every *discussed* card -- including an
        # endorsed one, whose pane records the endorsement -- and only for those.
        check_eq(has_pane, discussed[bid],
                 f"AC-C2/WRR-2: {bid} is discussed={discussed[bid]}, so its card "
                 f"{'must' if discussed[bid] else 'must not'} carry an author pane")
        if has_pane:
            check(chunk.index('<div class="pane prediction">')
                  < chunk.index('<div class="pane account">'),
                  f"AC-C2/WRR-1: the prediction pane must precede the author pane ({bid})")

    # AC-C5: a fast-forwarded card has no author pane; empty sections keep an empty row.
    ff_card = next(c for c in html.split('<div class="block ')[1:]
                   if re.search(r'block-id">b008<', c))
    check('<div class="pane account">' not in ff_card,
          "AC-C5/WRR-2: a fast-forwarded block renders with the prediction pane only")
    endorsed_card = next(c for c in html.split('<div class="block ')[1:]
                         if re.search(r'block-id">b001<', c))
    check_in("WR-Q7", endorsed_card,
             "AC-C5/WRR-2: a discussed endorsement renders its pane, saying it was one")

    # AC-C5/WRR-4: a ledger with nothing to export still renders both sections.
    empty_md = work / "empty.md"
    empty_html = work / "empty.html"
    empty_ledger = FIXTURES / "ledgers/ordered/ledger.yaml"
    render("md", empty_ledger, empty_md, FIXTURES / "proj_a")
    render("html", empty_ledger, empty_html, FIXTURES / "proj_a")
    empty_md_text = empty_md.read_text(encoding="utf-8")
    for heading in ("## Assumptions Carried Forward", "## Open Questions", "## Drift"):
        section = empty_md_text.split(heading, 1)[1].split("\n## ", 1)[0]
        check(section.strip(), f"AC-C5/WRR-4: {heading} must keep an explicit empty state")
        check("None" in section,
              f"AC-C5/WRR-4: {heading} must say so rather than disappearing")
    empty_html_text = empty_html.read_text(encoding="utf-8")
    check_eq(empty_html_text.count("None recorded</td>"), 2,
             "AC-C5/WRR-4: the assumptions and open-questions tables each keep one "
             "empty-state row")

    # AC-C6: the markdown says what happened to each block, and files the leftovers.
    sections = md.split("\n### ")
    ff_section = next(s for s in sections if s.startswith("b008 "))
    check_in("fast-forwarded", ff_section,
             "AC-C6: a fast-forwarded block says so in its own section")
    check_in(wr.find_block(led, "b008")["prediction"]["what_it_does"], ff_section,
             "AC-C6: a fast-forwarded block still renders its prediction")
    open_questions = md.split("## Open Questions", 1)[1].split("\n## ", 1)[0]
    check_in("b006", open_questions,
             "AC-C6: every unresolved block appears under Open Questions")
    assumptions = md.split("## Assumptions Carried Forward", 1)[1].split("\n## ", 1)[0]
    for item in led["assumption_export"]:
        check_in(item["assumption"], assumptions,
                 "AC-C6: every exported assumption appears under Assumptions Carried Forward")

    # AC-C3: rendering twice is byte-identical.
    md_again = work / "ledger-again.md"
    html_again = work / "report-again.html"
    render("md", led_path, md_again, project)
    render("html", led_path, html_again, project)
    check_eq(md_again.read_bytes(), md_path.read_bytes(),
             "AC-C3: ledger.md must render deterministically")
    check_eq(html_again.read_bytes(), html_path.read_bytes(),
             "AC-C3: the HTML report must render deterministically")

    after_listing = sorted(p.name for p in reports.iterdir())
    check_eq(after_listing, [html_path.name],
             "D3/WR-X4: the rendered report is the only new entry in the reviewed project")

    CASE1.update({
        "project": project, "ledger": led_path, "md": md_path, "html": html_path,
        "reports": reports, "work_rooms": war_rooms,
    })


# =========================================================================== case 2
def case_2_divergence(work: Path) -> None:
    """The handoff: who needs agent judgment, what happens when it arrives.

    Covers AC-D3, AC-D4, AC-D5, AC-C4, and WL-09's positive half.
    """
    project = copy_project("proj_a", work)
    led_path = ledger_path(work / "war_rooms", "proj_a", "code/sample.R")
    build_ledger(project, "code/sample.R", led_path)

    # AC-D3: an unfinished walkthrough is not reconciled by accident.
    incomplete = reconcile(led_path, project, expect=3)
    check_in("INCOMPLETE: 8 blocks without a disposition", incomplete.text,
             "AC-D3: reconcile reports how many blocks are unanswered")
    check("no agent judgment" not in incomplete.text,
          "AC-D3: the 'no agent judgment' line is printed only for a complete ledger")

    # Exactly two blocks carry a written account; the rest are endorsements.
    texted = {"b003": ("We only read the columns the codebook lists.",
                       "The extract is wider than the analysis needs."),
              "b006": ("Whether dropping missing wages is intended.",
                       "The codebook, which is not in the room.")}
    for block in wr.load_ledger(led_path)["blocks"]:
        bid = block["block_id"]
        if bid in texted:
            meant, why = texted[bid]
            record_answer(led_path, bid, "needs-change" if bid == "b003" else "unresolved",
                          meant=meant, why=why)
        else:
            record_answer(led_path, bid, "confirmed", endorsed=True)
    lint_green(led_path, project, "on a fully dispositioned ledger")

    # AC-D5, first half.
    first = reconcile(led_path, project, write=True)
    needs = re.search(r"NEEDS AGENT JUDGMENT.*?\n\s*([^\n]+)\n", first.text, re.DOTALL)
    check(needs is not None, f"reconcile must name the blocks it hands back:\n{first.text}")
    check_eq(sorted(x.strip() for x in needs.group(1).split(",")), ["b003", "b006"],
             "the needs-agent list is exactly the blocks with a written account")
    check_in("Post-write lint: clean", first.text, "AC-D5: post-write lint runs and passes")
    led = wr.load_ledger(led_path)
    check(not led["session"].get("reconciled"),
          "AC-D5: session.reconciled stays unset until the classification exists")

    # The agent's classification, applied here as a fixture.
    set_divergence(led_path, "b003", False, "incomplete-intent",
                   "The prediction did not mention the column subset.")
    set_divergence(led_path, "b006", False, "author-uncertain",
                   "The author could not resolve the treatment of missing wages.")

    # AC-D5, second half.
    second = reconcile(led_path, project, write=True)
    check_in("Post-write lint: clean", second.text, "AC-D5: the rerun must lint clean")
    led = wr.load_ledger(led_path)
    check(led["session"].get("reconciled"),
          "AC-D5: the rerun sets session.reconciled once nothing needs judgment")
    check_eq([h["event"] for h in led["session"]["history"]].count("reconcile"), 1,
             "AC-D5: exactly one reconcile history entry, even across two writes")
    check_eq(lint_codes(led_path, project), set(),
             "WL-09 passes once every discussed block carries a divergence")

    # Silence is not agreement: a discussed block answered with a disposition and no
    # text still needs a classification before the ledger can be called reconciled.
    silent_dir = work / "silent"
    silent_dir.mkdir()
    silent = silent_dir / "ledger.yaml"
    silent.write_bytes(led_path.read_bytes())
    data = wr.load_ledger(silent)
    block = wr.find_block(data, "b005")
    block["disposition"] = "misread-by-agent"
    block["endorsed_prediction"] = False
    block["discussed"] = True
    block["divergence"] = {"match": None, "type": None, "detail": None}
    data["session"].pop("reconciled", None)
    wr.save_ledger(silent, data)
    dry = reconcile(silent, project)
    check_in("NEEDS AGENT JUDGMENT", dry.text,
             "a discussed block with no classification is handed back, text or not")
    check_in("b005", dry.text.split("NEEDS AGENT JUDGMENT", 1)[1],
             "the silently-dispositioned block is named in the needs-agent list")

    # AC-D4: endorsement plus author text is refused by lint, and reconcile writes nothing.
    broken_dir = work / "broken"
    broken_dir.mkdir()
    broken = broken_dir / "ledger.yaml"
    broken.write_bytes(led_path.read_bytes())
    data = wr.load_ledger(broken)
    block = wr.find_block(data, "b003")
    block["endorsed_prediction"] = True
    block["disposition"] = "confirmed"
    wr.save_ledger(broken, data)
    check_eq(lint_codes(broken, project), {"WL-05"},
             "AC-D4: endorsement plus author text is a WL-05 failure and nothing else")
    before = broken.read_bytes()
    refused = reconcile(broken, project, write=True, expect=1)
    check_in("LINT REFUSED", refused.text, "AC-D4: reconcile refuses a ledger that fails lint")
    check_eq(broken.read_bytes(), before, "AC-D4: a refused reconcile writes nothing")
    check(not (broken_dir / "work-order.md").exists(),
          "AC-D4: a refused reconcile writes no work order either")

    # AC-C4: the renderers refuse the same ledger, and write nothing.
    md_out = work / "should-not-exist.md"
    html_out = work / "should-not-exist.html"
    refused = render("md", broken, md_out, project, expect=1)
    check_in("LINT REFUSED", refused.text, "AC-C4: md rendering refuses a lint failure")
    check(not md_out.exists(), "AC-C4: a refused md render writes nothing")
    refused = render("html", broken, html_out, project, expect=1)
    check_in("LINT REFUSED", refused.text, "AC-C4: html rendering refuses a lint failure")
    check(not html_out.exists(), "AC-C4: a refused html render writes nothing")


# =========================================================================== case 3
def case_3_resume_and_namespace(work: Path) -> None:
    """Finding the ledger again, and refusing the wrong project.

    Covers AC-E4, AC-E5, AC-E10, AC-B14, AC-B15.
    """
    project_a = copy_project("proj_a", work)
    project_b = copy_project("proj_b", work)
    war_rooms = work / "war_rooms"

    # AC-E4: two scripts at different paths in one project never share a ledger.
    check_eq(wr.slug_for("proj_a", "a/clean.R"), "proj_a--a--clean.R",
             "AC-E4: the slug keeps the script's path")
    check_eq(wr.slug_for("proj_a", "b/clean.R"), "proj_a--b--clean.R",
             "AC-E4: the slug keeps the script's path")
    check(wr.slug_for("proj_a", "a/clean.R") != wr.slug_for("proj_a", "b/clean.R"),
          "AC-E4: two same-named scripts in one project produce different slugs")

    # AC-E10: the same script path under two projects never shares a ledger either.
    slug_a = wr.slug_for("proj_a", "code/sample.R")
    slug_b = wr.slug_for("proj_b", "code/sample.R")
    check(slug_a != slug_b,
          "AC-E10: two projects with the same script path produce distinct slugs")

    led_a = ledger_path(war_rooms, "proj_a", "code/sample.R")
    build_ledger(project_a, "code/sample.R", led_a)
    led_b = ledger_path(war_rooms, "proj_b", "code/sample.R")
    build_ledger(project_b, "code/sample.R", led_b)

    # -- the first session: one reviewer answers the first two blocks -------------------
    with server(led_a, project_a) as app:
        app.answer("b001", "confirmed", endorsed=True, reviewer="bglasner", role="author")
        app.answer("b002", "confirmed", endorsed=True, reviewer="bglasner", role="author")

    # -- AC-E5: the resume path the skill instructs -------------------------------------
    found = wr.locate_ledger(war_rooms, "proj_a", "code/sample.R")
    check_eq(found, led_a, "AC-E5: locate_ledger finds the ledger by slug")
    # D-17: the skill locates through a CLI, never by building the slug by hand.
    located = prep("locate", project_a / "code/sample.R", "--project-root", project_a,
                   "--war-rooms", war_rooms)
    check_eq(located.out.strip(), str(led_a.resolve()), "D-17: locate prints the M1 slug path")
    check_in("found", located.err, "D-17: locate says the ledger exists")
    fresh = prep("locate", project_a / "a/clean.R", "--project-root", project_a,
                 "--war-rooms", war_rooms)
    check_eq(fresh.out.strip(),
             str((war_rooms / "proj_a--a--clean.R" / "ledger.yaml").resolve()),
             "D-17: locate prints the path a new session writes to")
    check_in("no ledger yet", fresh.err, "D-17: a missing ledger is not an error")
    # Phase 2 Stage F: without --war-rooms, ledgers go to the repository's records/war_rooms/.
    default = prep("locate", project_a / "a/clean.R", "--project-root", project_a)
    check_eq(default.out.strip(),
             str((REPO / "records" / "war_rooms" / "proj_a--a--clean.R" / "ledger.yaml")
                 .resolve()),
             "Stage F: the default war_rooms directory is records/war_rooms/")
    squatter = war_rooms / "proj_a--a--clean.R" / "ledger.yaml"
    squatter.parent.mkdir()
    shutil.copyfile(led_b, squatter)
    refused = prep("locate", project_a / "a/clean.R", "--project-root", project_a,
                   "--war-rooms", war_rooms, expect=1)
    check_in("does not match", refused.text, "D-17: a ledger for another project is refused")
    check("ledger.yaml" not in refused.out, "D-17: a refused locate prints no path")
    shutil.rmtree(squatter.parent)
    resumed = wr.load_ledger(found)
    check_eq(resumed["project"]["id"], project_a.name,
             "AC-E5: the resumed ledger's project.id must match the project root")
    wr.check_project_id(project_a, resumed)  # raises on mismatch
    first_open = next(b["block_id"] for b in resumed["blocks"] if not b.get("disposition"))
    check_eq(first_open, "b003",
             "AC-E5: the resume reports the first block without a disposition")
    with server(led_a, project_a) as app:
        app.answer(first_open, "confirmed", endorsed=True, reviewer="rlee",
                   role="fresh-eyes")
    resumed = wr.load_ledger(led_a)
    walkthroughs = [h for h in resumed["session"]["history"] if h["event"] == "walkthrough"]
    check_eq([h["by"] for h in walkthroughs], ["bglasner", "rlee"],
             "AC-E5/D10: the resumed reviewer adds a second walkthrough entry")
    check_eq(wr.find_block(resumed, first_open)["reviewer"], "rlee",
             "AC-E5: the resumed answer is recorded under the second reviewer id")
    check_eq(resumed["session"]["reviewers"],
             [{"id": "bglasner", "role": "author"}, {"id": "rlee", "role": "fresh-eyes"}],
             "AC-E5: both reviewers are registered with their roles")
    lint_green(led_a, project_a, "after a resumed session")

    # -- AC-E10: project B's ledger under project A's root is a startup error -----------
    mismatch = run([sys.executable, SERVER, "--ledger", led_b,
                    "--project-root", project_a, "--port", "0"], expect=2)
    check_in("proj_a", mismatch.text, "AC-E10: the mismatch error names the resolved root")
    check_in("proj_b", mismatch.text, "AC-E10: the mismatch error names the ledger's project")
    check_in("does not match", mismatch.text, "AC-E10: the D1 guard must say what is wrong")

    # -- AC-B15: no flag, and the nearest PROJECT.md root is the wrong project ----------
    no_flag = run([sys.executable, SERVER, "--ledger", led_a, "--port", "0"],
                  cwd=REPO, expect=2)
    check_in(REPO.name, no_flag.text,
             "AC-B15: the error names the basename it resolved from the working directory")
    check_in("proj_a", no_flag.text, "AC-B15: the error names the ledger's project.id")
    check_in("--project-root", no_flag.text, "AC-B15: the error names the flag to pass")

    # -- AC-B14: an unresolvable script never falls back to a same-named decoy ----------
    hollow = work / "hollow" / "proj_a"
    hollow.mkdir(parents=True)
    (hollow / "PROJECT.md").write_text("# Fixture project A (no code)\n", encoding="utf-8", newline="\n")
    decoy_cwd = work / "decoy"
    (decoy_cwd / "code").mkdir(parents=True)
    (decoy_cwd / "code/sample.R").write_text("# decoy, never to be hashed\n",
                                             encoding="utf-8", newline="\n")
    missing = run([sys.executable, SERVER, "--ledger", led_a,
                   "--project-root", hollow, "--port", "0"], cwd=decoy_cwd, expect=2)
    check_in("--project-root", missing.text,
             "AC-B14: the error names the flag rather than guessing a file")
    check_in("code/sample.R", missing.text, "AC-B14: the error names the unresolved path")
    check(str(decoy_cwd) not in missing.text,
          "AC-B14: the decoy in the working directory must never be resolved")

    # -- K4: an explicit root is checked against project.id inside resolution itself -----
    # A root that holds PROJECT.md but names another project used to resolve, leaving the
    # id check to each caller; one caller that forgot would hash another project's file.
    other = work / "other" / "proj_z"
    shutil.copytree(project_a, other)
    try:
        wr.resolve_project_root(other, resumed)
    except wr.WarRoomError as exc:
        check_in("does not match", str(exc), "K4: the refusal says the id does not match")
        check_in("proj_z", str(exc), "K4: the refusal names the root it was given")
    else:
        raise CaseFailure("K4: resolve_project_root accepted an explicit root whose "
                          "basename is not the ledger's project.id")
    wrong = run([sys.executable, LINT, led_a, "--project-root", other], expect=1)
    check_in("does not match", wrong.text, "K4: lint refuses the wrong explicit root")


# =========================================================================== case 4
def case_4_drift(work: Path) -> None:
    """An edited source, before and after a disposition. Covers AC-A3, AC-A6, AC-B16."""
    project = copy_project("proj_a", work)
    script = project / "code/sample.R"
    led_path = ledger_path(work / "war_rooms", "proj_a", "code/sample.R")
    build_ledger(project, "code/sample.R", led_path)

    # -- AC-A3: verify is clean, then names exactly the block that changed --------------
    clean = prep("verify", led_path, "--project-root", project)
    check_in("OK: every block hash reproduces", clean.text, "AC-A3: verify starts clean")
    original = script.read_text(encoding="utf-8")
    edited = original.replace("filter(age >= 25)", "filter(age >= 30)")
    check(edited != original, "AC-A3: the fixture edit must actually change the file")
    script.write_text(edited, encoding="utf-8", newline="\n")
    drifted = prep("verify", led_path, "--project-root", project, expect=1)
    named = set(re.findall(r"DRIFT (b\d+)", drifted.text))
    check_eq(named, {"b004"}, "AC-A3: verify names only the block whose source changed")
    script.write_text(original, encoding="utf-8", newline="\n")

    # -- AC-A6: the same edit, after the block was dispositioned ------------------------
    for block in wr.load_ledger(led_path)["blocks"]:
        record_answer(led_path, block["block_id"], "confirmed", endorsed=True)
    lint_green(led_path, project, "before the post-disposition edit")
    script.write_text(edited, encoding="utf-8", newline="\n")
    persisted = prep("verify", led_path, "--project-root", project, "--write", expect=1)
    check_in("after disposition", persisted.text,
             "AC-A6: verify --write reports the WR-A4 regression signal")
    led = wr.load_ledger(led_path)
    for block in led["blocks"]:
        wanted = block["block_id"] == "b004"
        check_eq(bool(block.get("drift")), wanted,
                 f"AC-A6: drift must be set on b004 alone, not {block['block_id']}")
        check_eq(bool(block.get("drift_after_disposition")), wanted,
                 f"AC-A6: drift_after_disposition must be set on b004 alone, "
                 f"not {block['block_id']}")
    lint_green(led_path, project, "with a recorded drift (WL-13 accepts it)")
    dry = reconcile(led_path, project)
    check_in("b004 hash drift", dry.text, "AC-A6: reconcile's dry run prints the drift note")
    check_in("WR-A4 regression signal", dry.text,
             "AC-A6: the note says the change came after the disposition")

    # -- AC-B16, first variant: an in-place edit while the server is running ------------
    project2 = copy_project("proj_a", work, as_name="proj_a_live")
    # The project directory's basename is the ledger's project.id (D1), so the live copy
    # is renamed back to `proj_a` inside its own parent rather than carrying a new name.
    live_root = work / "live" / "proj_a"
    live_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(project2), str(live_root))
    live_script = live_root / "code/sample.R"
    led2 = ledger_path(work / "war_rooms_live", "proj_a", "code/sample.R")
    build_ledger(live_root, "code/sample.R", led2)
    record_answer(led2, "b004", "confirmed", endorsed=True)
    with server(led2, live_root) as app:
        live_script.write_text(edited, encoding="utf-8", newline="\n")
        app.answer("b005", "confirmed", endorsed=True)
    led = wr.load_ledger(led2)
    b004 = wr.find_block(led, "b004")
    check_eq(bool(b004.get("drift")), True,
             "AC-B16: the server persists drift for a block edited mid-session")
    check_eq(bool(b004.get("drift_after_disposition")), True,
             "AC-B16: and marks it as changed after its disposition (WR-A4)")
    check_eq(wr.find_block(led, "b005")["disposition"], "confirmed",
             "AC-B16: the answer to another block still saves")
    lint_green(led2, live_root, "after a mid-session edit")

    # -- AC-B16, second variant: a line inserted above is a relocation, not drift -------
    shifted_root = work / "shifted" / "proj_a"
    shifted_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(FIXTURES / "proj_a", shifted_root)
    shifted_script = shifted_root / "code/sample.R"
    led3 = ledger_path(work / "war_rooms_shifted", "proj_a", "code/sample.R")
    build_ledger(shifted_root, "code/sample.R", led3)
    record_answer(led3, "b004", "confirmed", endorsed=True)
    with server(led3, shifted_root) as app:
        lines = shifted_script.read_text(encoding="utf-8").split("\n")
        lines.insert(9, "# An inserted note that shifts everything below it.")
        shifted_script.write_text("\n".join(lines), encoding="utf-8", newline="\n")
        app.answer("b005", "confirmed", endorsed=True)
    led = wr.load_ledger(led3)
    b004 = wr.find_block(led, "b004")
    check_eq(b004.get("relocated_from"), [10, 13],
             "AC-B16: a shifted block records where it used to be (WR-A2)")
    check_eq(bool(b004.get("drift")), False,
             "AC-B16: re-anchoring by hash is not drift (D11)")
    check_eq(b004["lines"], [11, 14], "AC-B16: the block's range follows the shift")
    lint_green(led3, shifted_root, "after a relocation")


# =========================================================================== case 5
def case_5_merge_split(work: Path) -> None:
    """Re-segmentation through both doors: the prep CLI and the app's API (WR-S5)."""
    project = copy_project("proj_a", work)
    script_lines = wr.wr_a1_lines(project / "code/sample.R")
    led_path = ledger_path(work / "war_rooms", "proj_a", "code/sample.R")
    build_ledger(project, "code/sample.R", led_path)
    before = wr.load_ledger(led_path)
    b002_before = wr.find_block(before, "b002")
    b003_before = wr.find_block(before, "b003")

    # -- merge through the CLI ----------------------------------------------------------
    merged_out = prep("merge", led_path, "b002", "--project-root", project)
    check_in("Merged into b002", merged_out.text, "merge reports the surviving block")
    led = wr.load_ledger(led_path)
    check(wr.find_block(led, "b003") is None, "the merged-away block is gone")
    merged = wr.find_block(led, "b002")
    check_eq(merged["lines"], [b002_before["lines"][0], b003_before["lines"][1]],
             "the merged block spans both ranges")
    check_eq(merged["sha256"],
             wr.wr_a1_hash(script_lines, merged["lines"][0], merged["lines"][1]),
             "the merged block is rehashed from the source, never by hand")
    check_eq(merged["prediction"]["confidence"], "low",
             "WR-S5: a merged prediction is one step below the lower of the two")
    check_eq(merged["prediction"].get("merged_from"), ["b002", "b003"],
             "the merged prediction records what it came from")
    edits = led["session"]["segmentation_edits"]
    check_eq([e["action"] for e in edits], ["merge"], "the merge is recorded in the session")
    lint_green(led_path, project, "after a merge")

    # -- split through the API ----------------------------------------------------------
    with server(led_path, project) as app:
        app.segment("split", "b002", at_line=8)
        # A dispositioned block is never re-segmented.
        app.answer("b001", "confirmed", endorsed=True)
        refusal = app.segment("merge", "b001", expect_ok=False)
        check_in("already carries a disposition", refusal["error"],
                 "WR-S5: re-segmentation refuses a dispositioned block")
    led = wr.load_ledger(led_path)
    parts = [b for b in led["blocks"] if b["block_id"] in ("b002a", "b002b")]
    check_eq(len(parts), 2, "the split produced two halves")
    check_eq([p["lines"] for p in parts], [[4, 7], [8, 8]],
             "the halves divide the range at the requested line")
    for part in parts:
        check_eq(part["sha256"],
                 wr.wr_a1_hash(script_lines, part["lines"][0], part["lines"][1]),
                 f"{part['block_id']} is rehashed from the source")
        check_eq(part["prediction"]["confidence"], "low",
                 "WR-S5: an inherited prediction is never more confident than its parent")
        check_eq(part["prediction"].get("inherited_from"), "b002",
                 "an inherited prediction records its parent")
    check_eq([e["action"] for e in led["session"]["segmentation_edits"]],
             ["merge", "split"], "both edits are recorded, in order")
    lint_green(led_path, project, "after a split")

    # -- and the CLI refuses a dispositioned block too -----------------------------------
    refused = prep("merge", led_path, "b001", "--project-root", project, expect=1)
    check_in("already carries a disposition", refused.text,
             "WR-S5: the CLI refuses what the API refuses")

    # -- a drifted block is not re-segmented, and an unrelated edit leaves it alone ------
    # Re-segmenting a block whose recorded hash no longer describes the source would
    # rehash the drift away, quietly turning a recorded fact into a clean-looking range.
    drift_root = work / "drifted" / "proj_a"
    drift_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(FIXTURES / "proj_a", drift_root)
    drift_script = drift_root / "code/sample.R"
    drift_led = ledger_path(work / "war_rooms_drift", "proj_a", "code/sample.R")
    build_ledger(drift_root, "code/sample.R", drift_led)
    record_answer(drift_led, "b004", "confirmed", endorsed=True)
    source = drift_script.read_text(encoding="utf-8")
    source = source.replace("filter(age >= 25)", "filter(age >= 30)")       # b004, answered
    source = source.replace("mean(wage, na.rm = TRUE)", "mean(wage))  # ?")  # b006, unanswered
    drift_script.write_text(source, encoding="utf-8", newline="\n")
    prep("verify", drift_led, "--project-root", drift_root, "--write", expect=1)
    led = wr.load_ledger(drift_led)
    b004_before = dict(wr.find_block(led, "b004"))
    b006_before = dict(wr.find_block(led, "b006"))
    check_eq((bool(b004_before["drift"]), bool(b004_before["drift_after_disposition"])),
             (True, True), "the dispositioned block must carry both drift flags")
    check_eq(bool(b006_before["drift"]), True,
             "the unanswered block must carry drift before the refusal is meaningful")

    refused = prep("merge", drift_led, "b006", "--project-root", drift_root, expect=1)
    check_in("drift", refused.text,
             "WR-S5: the CLI refuses to re-segment a block carrying drift")
    refused = prep("split", drift_led, "b006", "--at", 22, "--project-root", drift_root,
                   expect=1)
    check_in("drift", refused.text, "WR-S5: and refuses to split one too")
    with server(drift_led, drift_root) as app:
        for op, at_line in (("merge", None), ("split", 22)):
            refusal = app.segment(op, "b006", at_line=at_line, expect_ok=False)
            check_in("drift", refusal["error"],
                     f"WR-S5: /api/segment must refuse to {op} a drifted block")

    # Merging two untouched blocks must not rehash, or re-flag, anything else.
    prep("merge", drift_led, "b001", "--project-root", drift_root)
    led = wr.load_ledger(drift_led)
    for bid, before_block in (("b004", b004_before), ("b006", b006_before)):
        after = wr.find_block(led, bid)
        for field in ("sha256", "lines", "drift", "drift_after_disposition"):
            check_eq(after.get(field), before_block.get(field),
                     f"an unrelated merge must leave {bid}.{field} exactly as it was")
    lint_green(drift_led, drift_root, "after merging around a drifted block")


# =========================================================================== case 6
WL_EXPECTED = (
    "WL-01", "WL-02", "WL-03", "WL-04", "WL-05", "WL-06", "WL-07",
    "WL-08", "WL-09", "WL-10", "WL-11", "WL-12", "WL-13", "WL-14",
)


def _mutate(led: dict, code: str, source_lines: list[str]) -> None:
    """One mutation per WL code, straight from the table in Workstream B.

    The base is case 1's own finished ledger: dispositioned, reconciled, and passing. Two
    rows of the plan's AC-B8 table name a block that would break a *second* check on a real
    reconciled ledger, so the runner substitutes an id and the mutation stays a singleton:

      - **WL-02** ("rename `b002`'s id to `b001`") renames `b001` here instead. `b002`'s
        prediction carries an assumption, so `assumption_export` names it; renaming it away
        would strand that export item and fire WL-11 as well. `b001` is the one block whose
        prediction carries no assumptions, so nothing points at it.
      - **WL-04** ("set `b001.disposition: maybe`") targets `b004` here instead. `b001` is
        an endorsed `confirmed` block, so changing its disposition would also break the
        endorsement pairing and fire WL-05. `b004` is `needs-change` and not endorsed, so
        only the closed-set check fires.

    WL-05 also targets `b004` for the same reason: it is dispositioned with `reviewer` and
    `answered_at`, and the endorsement it gains is the only thing wrong with it.
    """
    if code == "WL-01":
        led["schema_version"] = 1
    elif code == "WL-02":
        wr.find_block(led, "b001")["block_id"] = "b002"
    elif code == "WL-03":
        block = wr.find_block(led, "b002")
        block["lines"] = [2, block["lines"][1]]
        block["sha256"] = wr.wr_a1_hash(source_lines, 2, block["lines"][1])
    elif code == "WL-04":
        wr.find_block(led, "b004")["disposition"] = "maybe"
    elif code == "WL-05":
        wr.find_block(led, "b004")["endorsed_prediction"] = True
    elif code == "WL-06":
        wr.find_block(led, "b005")["answered_at"] = None
    elif code == "WL-07":
        wr.find_block(led, "b005")["answered_at"] = "2000-01-01T00:00:00.000000Z"
    elif code == "WL-08":
        led["script"]["path"] = "/Users/x/code/sample.R"
    elif code == "WL-09":
        led["session"]["reconciled"] = wr.utc_now()
        wr.find_block(led, "b004")["divergence"]["match"] = None
    elif code == "WL-10":
        wr.find_block(led, "b005")["reviewer"] = "nobody"
    elif code == "WL-11":
        led.setdefault("assumption_export", []).append(
            {"block_id": "b999", "assumption": "A block that is not in this ledger.",
             "stated_by": "agent", "confirmed": False})
    elif code == "WL-12":
        led["session"]["history"] = []
    elif code == "WL-13":
        block = wr.find_block(led, "b007")
        digest = block["sha256"]
        block["sha256"] = ("b" if digest[0] != "b" else "c") + digest[1:]
    elif code == "WL-14":
        wr.find_block(led, "b005")["dissent"] = [
            {"reviewer": "rlee", "disposition": "confirmed",
             "author_account": None, "endorsed_prediction": False}]
    else:  # pragma: no cover
        raise CaseFailure(f"no mutation defined for {code}")


def case_6_lint_matrix(work: Path) -> None:
    """One mutation per lint code, and the proof that predictions never changed.

    Covers AC-B8, AC-A8, AC-E2 (the lint half) and AC-E7.
    """
    base = CASE1.get("ledger")
    project = CASE1.get("project")
    check(base and Path(base).is_file(),
          "case 6 needs case 1's finished ledger; run the cases in order")

    # -- AC-A8: the prediction text never moved, from prep to the rendered report -------
    after_finalize = CASE1["predictions_after_finalize"]
    for stage in ("predictions_after_server", "predictions_after_reconcile"):
        check_eq(CASE1[stage], after_finalize,
                 f"AC-A8/WR-P3: predictions must be identical {stage.replace('_', ' ')}")
    md = Path(CASE1["md"]).read_text(encoding="utf-8")
    html = Path(CASE1["html"]).read_text(encoding="utf-8")
    for bid, pred in after_finalize.items():
        for field in ("what_it_does", "inferred_intent"):
            text = pred[field]
            check_in(text, md, f"AC-A8: {bid}.{field} must render verbatim in ledger.md")
            check_in(htmllib.escape(text, quote=True), html,
                     f"AC-A8: {bid}.{field} must render verbatim in the HTML report")
        for assumption in pred["assumptions"]:
            check_in(assumption, md,
                     f"AC-A8: {bid}'s assumption must render verbatim in ledger.md")
            check_in(htmllib.escape(assumption, quote=True), html,
                     f"AC-A8: {bid}'s assumption must render verbatim in the HTML report")

    # -- AC-B8: every code fires alone --------------------------------------------------
    source_lines = wr.wr_a1_lines(Path(project) / "code/sample.R")
    check_eq(lint_codes(Path(base), Path(project)), set(),
             "AC-B8: the mutation base must pass lint before anything is mutated")
    matrix_dir = work / "matrix"
    matrix_dir.mkdir()
    for code in WL_EXPECTED:
        target = matrix_dir / f"{code}.yaml"
        led = wr.load_ledger(Path(base))
        _mutate(led, code, source_lines)
        wr.save_ledger(target, led)
        check_eq(lint_codes(target, Path(project)), {code},
                 f"AC-B8: the {code} mutation must trigger {code} and nothing else")

    # -- AC-E2 (lint half): a stored project root is an absolute path -------------------
    rooted = work / "rooted.yaml"
    led = wr.load_ledger(Path(base))
    led["project"]["root"] = "/Users/x"
    wr.save_ledger(rooted, led)
    check_eq(lint_codes(rooted, Path(project)), {"WL-08"},
             "AC-E2: a stored absolute project root fails WL-08 and nothing else")
    unrooted = work / "unrooted.yaml"
    led = wr.load_ledger(Path(base))
    wr.save_ledger(unrooted, led)
    check_eq(lint_codes(unrooted, Path(project)), set(),
             "AC-E2: the same ledger without it passes")

    # -- AC-E7: the hand-merged two-reviewer fixture, and one duplicated id -------------
    two_reviewer = FIXTURES / "ledgers/two-reviewer/ledger.yaml"
    check_eq(lint_codes(two_reviewer, FIXTURES / "proj_a"), set(),
             "AC-E7: the two-reviewer fixture passes lint as committed")
    duplicated = work / "duplicated.yaml"
    led = wr.load_ledger(two_reviewer)
    # b003 is named by neither `assumption_export` nor `open_questions`, so duplicating
    # its id breaks uniqueness and nothing else.
    wr.find_block(led, "b003")["block_id"] = "b002"
    wr.save_ledger(duplicated, led)
    check_eq(lint_codes(duplicated, FIXTURES / "proj_a"), {"WL-02"},
             "AC-E7: a duplicated block_id fails WL-02 only (D4)")

    # -- D-14: a block_id outside the format prep writes fails WL-02 alone --------------
    for bad in ("b003');alert(1)//", "B003", "b3", "x001", "b003\n"):
        malformed = work / "malformed.yaml"
        led = wr.load_ledger(two_reviewer)
        wr.find_block(led, "b003")["block_id"] = bad
        wr.save_ledger(malformed, led)
        check_eq(lint_codes(malformed, FIXTURES / "proj_a"), {"WL-02"},
                 f"D-14: block_id {bad!r} fails WL-02 only")
    # `$` also matches before a final newline, so both formats are checked whole.
    led = wr.load_ledger(two_reviewer)
    block = wr.find_block(led, "b003")
    block["sha256"] = block["sha256"] + "\n"
    check("WL-02" in wl.lint(led, FIXTURES / "proj_a").codes,
          "a sha256 with a trailing newline fails WL-02")


# =========================================================================== case 7
def case_7_concurrency_and_origin(work: Path) -> None:
    """Twenty answers at once, and the four origin cases. Covers AC-B9 and AC-B10."""
    project = copy_project("proj_a", work)
    # A script with enough blocks to answer twenty at once. Generated here rather than
    # committed, because its only property that matters is its block count.
    many = project / "code/many.R"
    body = ["# Generated by the war-room test suite. Twenty-four independent statements.",
            ""]
    for i in range(24):
        body += [f"value_{i:02d} <- {i}", ""]
    many.write_text("\n".join(body), encoding="utf-8", newline="\n")
    led_path = ledger_path(work / "war_rooms", "proj_a", "code/many.R")
    build_ledger(project, "code/many.R", led_path)
    led = wr.load_ledger(led_path)
    ids = [b["block_id"] for b in led["blocks"]]
    check(len(ids) >= 21, f"AC-B9 needs at least 21 blocks, the generated script gave "
                          f"{len(ids)}")
    targets = ids[1:21]

    with server(led_path, project) as app:
        def answer(bid: str) -> dict:
            return app.answer(bid, "confirmed", endorsed=True, expect_ok=None)

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(answer, targets))
        for bid, out in zip(targets, results):
            check_eq(bool(out.get("ok")), True,
                     f"AC-B9: the concurrent answer to {bid} was rejected ({out})")
        saved = wr.load_ledger(led_path)
        for bid in targets:
            check_eq(wr.find_block(saved, bid)["disposition"], "confirmed",
                     f"AC-B9: {bid}'s answer did not survive the other nineteen")

        # AC-B10: the four origin cases, all against the same running server.
        spare = ids[21]
        payload = {"block_id": spare, "disposition": "confirmed",
                   "endorsed_prediction": True, "flagged": False,
                   "reviewer": "bglasner", "reviewer_role": "author",
                   "author": {"meant_to_do": "", "why_this_way": "",
                              "assumptions_carried": []}}
        status, _ = app.request("POST", "/api/answer", payload,
                                {"Origin": "http://evil.example"})
        check_eq(status, 403, "AC-B10: a cross-origin POST is forbidden")
        status, out = app.request("POST", "/api/answer", payload,
                                  {"Origin": f"http://localhost:{app.port}"})
        check_eq(status, 200, "AC-B10: a loopback Origin on the served port is allowed")
        check_eq(bool(out.get("ok")), True, "AC-B10: and the answer is saved")
        status, out = app.request("POST", "/api/answer", payload)
        check_eq(status, 200, "AC-B10: no Origin with the right Host is allowed")
        status, _ = app.request("POST", "/api/answer", payload,
                                {"Host": "evil.example"})
        check_eq(status, 403, "AC-B10: no Origin with a foreign Host is forbidden")

    lint_green(led_path, project, "after twenty concurrent answers")


# =========================================================================== case 8
def _check_partition(led: dict, script: Path, name: str) -> None:
    """Every non-blank line sits in exactly one block (WR-S7)."""
    check(led["blocks"], f"{name} must segment into at least one block")
    covered = coverage_of(led)
    wanted = non_blank_lines(script)
    check(not sorted(wanted - set(covered)), f"every non-blank line of {name} must sit in a block")
    check(not sorted({i for i in covered if covered.count(i) > 1} & wanted),
          f"no line of {name} may sit in two blocks")


def case_8_starter_pipeline(work: Path) -> str:
    """Segment the frozen starter copy; check only the partition of a live run_all.R."""
    project = work / "starter"
    (project / "code").mkdir(parents=True)
    (project / "PROJECT.md").write_text("# Starter-pipeline fixture\n", encoding="utf-8", newline="\n")
    script = project / "code" / "run_all.R"
    shutil.copyfile(STARTER, script)
    check_eq(wr.wr_a1_file_hash(wr.wr_a1_lines(script)), STARTER_SHA256,
             "the frozen starter copy must not change; add a new fixture instead")
    out = work / "run_all.yaml"
    prep("skeleton", script, "--project-root", project, "--out", out, "--fixture")
    led = wr.load_ledger(out)
    check_eq(led["script"]["path"], "code/run_all.R", "the ledger records the script path")
    check_eq(led["script"]["language"], "R", "run_all.R is R")
    check_eq(led["project"]["id"], "starter", "project.id is the project root's basename")
    check_eq([b["lines"] for b in led["blocks"]], STARTER_BLOCKS,
             "the starter copy segments into the pinned blocks")
    _check_partition(led, script, "the starter copy")

    # The live file belongs to the project, so only the WR-S7 partition is checked.
    live = REPO / "code/run_all.R"
    if not live.is_file():
        return f"frozen copy: {len(led['blocks'])} blocks; no live code/run_all.R"
    live_out = work / "live_run_all.yaml"
    prep("skeleton", live, "--project-root", REPO, "--out", live_out, "--fixture")
    live_led = wr.load_ledger(live_out)
    _check_partition(live_led, live, "the live code/run_all.R")
    return (f"frozen copy: {len(led['blocks'])} blocks; "
            f"live code/run_all.R: {len(live_led['blocks'])} blocks, partition checked")


# =========================================================================== case 9
# WR-A1 golden hashes, pinned from the implementation before any library change (I8 of
# the Phase 3D plan). A refactor of the reader or the hasher that moves one of these
# digests silently invalidates every committed ledger, so a change here is a defect,
# not an update.
_GOLDEN_LF = ('df <- read.csv("in.csv")\n# café: a UTF-8 comment\n\nout <- df |>\n'
              '  subset(age >= 25)\n').encode("utf-8")
_GOLDEN_FIVE_LINES = {
    "lines": 5,
    "file": "0320cff2234d33a3c3c750c1606bb63fe2794e62a33875914e407bcaa225c138",
    (1, 1): "7044cd0f4b7369736ded05f8ec2673efd360cbbe6ab43cec8eb5e30bb242a899",
    (1, 2): "4de7cc6b6eeddd51f2941981385e0ae8b1fc151e0f607fa06a55436ccbcaea00",
    (4, 5): "5683a2b222b73fc98d245e3cb6bd9d6def30db4888f851277226a221e85564c4",
}
# A lone `\r` is not a line break under WR-A1 step 2, so lines 1 and 2 fuse into one.
_GOLDEN_LONE_CR = {
    "lines": 4,
    "file": "ad7d993040143e2ab52edb9367537f70ff638248dff5779a4fe9aa87db94fb8b",
    (1, 1): "88f84b99dc07fb2eab93c528fd46e66bc4467fdcf9f0277862d24251762a65c7",
    (1, 2): "620ea7a6e4feb5ee12a7479eec2351caeab203184591091212c136cf646bb53a",
    (3, 4): "5683a2b222b73fc98d245e3cb6bd9d6def30db4888f851277226a221e85564c4",
}
GOLDEN_WR_A1 = {
    "lf": (_GOLDEN_LF, _GOLDEN_FIVE_LINES),
    "crlf": (_GOLDEN_LF.replace(b"\n", b"\r\n"), _GOLDEN_FIVE_LINES),
    "no-final-newline": (_GOLDEN_LF[:-1], _GOLDEN_FIVE_LINES),
    "lone-cr": (_GOLDEN_LF.replace(b"\n# caf", b"\r# caf"), _GOLDEN_LONE_CR),
}


def case_9_wr_a1_golden(work: Path) -> None:
    """WR-A1 digests for LF, CRLF, a lone `\\r`, and a missing final newline (I8)."""
    project = work / "golden"
    (project / "code").mkdir(parents=True)
    (project / "PROJECT.md").write_text("# Golden-hash fixture\n", encoding="utf-8", newline="\n")
    for name, (data, golden) in GOLDEN_WR_A1.items():
        script = project / "code" / f"{name}.R"
        script.write_bytes(data)
        lines = wr.wr_a1_lines(script)
        check_eq(len(lines), golden["lines"], f"WR-A1 {name}: line count")
        check_eq(wr.wr_a1_file_hash(lines), golden["file"], f"WR-A1 {name}: file hash")
        for key, digest in golden.items():
            if isinstance(key, tuple):
                check_eq(wr.wr_a1_hash(lines, *key), digest,
                         f"WR-A1 {name}: hash of lines {key[0]}-{key[1]}")
        # The prep CLI records the same digest, so the pin covers the path a ledger takes.
        out = work / f"{name}.yaml"
        prep("skeleton", script, "--project-root", project, "--out", out, "--fixture")
        recorded = wr.load_ledger(out)["script"]
        check_eq(recorded["sha256"], golden["file"], f"WR-A1 {name}: skeleton script.sha256")
        check_eq(recorded["line_count"], golden["lines"], f"WR-A1 {name}: skeleton line_count")


# =========================================================================== case 10
# Four one-line blocks; b002 and b004 hold the same line (census D-10).
DUPLICATE_SCRIPT = ("x <- read_data()\n\nprint(summary(x))\n\nx <- clean(x)\n\n"
                    "print(summary(x))\n")


def _duplicate_project(parent: Path, text: str) -> tuple[Path, Path]:
    """A one-script project whose basename is its project.id, plus its dispositioned ledger."""
    project = parent / "proj_d"
    (project / "code").mkdir(parents=True)
    (project / "PROJECT.md").write_text("# Duplicate-content fixture\n", encoding="utf-8", newline="\n")
    (project / "code/dup.R").write_text(text, encoding="utf-8", newline="\n")
    led_path = ledger_path(parent / "war_rooms", "proj_d", "code/dup.R")
    build_ledger(project, "code/dup.R", led_path)
    for block in wr.load_ledger(led_path)["blocks"]:
        record_answer(led_path, block["block_id"], "confirmed", endorsed=True)
    return project, led_path


def _overlapping_lines(led: dict) -> list[int]:
    covered = coverage_of(led)
    return sorted({i for i in covered if covered.count(i) > 1})


def _overlap_probe(led_path: Path, project: Path, probe: Path) -> set[str]:
    """Copy the ledger, stretch b001 over b002's first line (rehashed), and lint it."""
    led = wr.load_ledger(led_path)
    lines = wr.wr_a1_lines(project / led["script"]["path"])
    first, second = led["blocks"][0], led["blocks"][1]
    first["lines"] = [first["lines"][0], second["lines"][0]]
    wr.rehash_block(first, lines)
    wr.save_ledger(probe, led)
    return lint_codes(probe, project)


def case_10_duplicate_content_drift(work: Path) -> None:
    """Re-anchoring never lands on another block, ambiguity is drift, accept restores lint."""
    # -- D-10: a line inserted above two identical blocks makes both ambiguous ----------
    project, led_path = _duplicate_project(work / "ambiguous", DUPLICATE_SCRIPT)
    check_eq([b["lines"] for b in wr.load_ledger(led_path)["blocks"]],
             [[1, 1], [3, 3], [5, 5], [7, 7]], "the fixture segments as four one-line blocks")
    (project / "code/dup.R").write_text("# A new header line.\n" + DUPLICATE_SCRIPT,
                                        encoding="utf-8", newline="\n")
    ambiguous = prep("verify", led_path, "--project-root", project, "--write", expect=1)
    led = wr.load_ledger(led_path)
    check_eq(_overlapping_lines(led), [],
             "D-10: no block may be re-anchored onto another block's range")
    check_eq({b["block_id"] for b in led["blocks"] if b.get("drift")}, {"b002", "b004"},
             "D-10: a hash found at two free ranges is drift, not a guess (I11)")
    for bid in ("b002", "b004"):
        check_eq(bool(wr.find_block(led, bid).get("drift_after_disposition")), True,
                 f"D-10: {bid} changed after its disposition (WR-A4)")
    check_eq(wr.find_block(led, "b001")["lines"], [2, 2], "D-10: a unique match still moves")
    check_eq(wr.find_block(led, "b003")["lines"], [6, 6], "D-10: a unique match still moves")
    check_in("ambiguous", ambiguous.text, "D-10: verify says why the block was not moved")

    # -- D-10: two blocks whose only free match is the same range are both drift, in any
    # block order (I11). Old file a,p,c,p,d; new file z,z,a,c,p,d; one line per block. --
    old = ["a <- 1", "", "p <- 2", "", "c <- 3", "", "p <- 2", "", "d <- 4"]
    new = ["z <- 0", "", "z <- 0", "", "a <- 1", "", "c <- 3", "", "p <- 2", "", "d <- 4"]
    for order in ("forward", "reversed"):
        blocks = [{"block_id": f"b00{i + 1}", "lines": [n, n], "sha256": wr.wr_a1_hash(old, n, n)}
                  for i, n in enumerate((1, 3, 5, 7, 9))]
        led = {"blocks": blocks if order == "forward" else blocks[::-1]}
        wr.recompute_drift(led, new)
        got = {b["block_id"]: (b["lines"], b["drift"]) for b in led["blocks"]}
        check_eq(got, {"b001": ([5, 5], False), "b002": ([3, 3], True), "b003": ([7, 7], False),
                       "b004": ([7, 7], True), "b005": ([11, 11], False)},
                 f"D-10: contested claims are drift, not first-come ({order} block order)")

    # -- D-10: a hash found only inside another block's current range is drift -----------
    project2, led2 = _duplicate_project(work / "owned", DUPLICATE_SCRIPT)
    edited = DUPLICATE_SCRIPT[:DUPLICATE_SCRIPT.rindex("x))")] + "y))\n"
    (project2 / "code/dup.R").write_text(edited, encoding="utf-8", newline="\n")
    prep("verify", led2, "--project-root", project2, "--write", expect=1)
    led = wr.load_ledger(led2)
    check_eq(_overlapping_lines(led), [],
             "D-10: an edited block never re-anchors onto a block that still matches")
    check_eq(wr.find_block(led, "b004")["lines"], [7, 7], "D-10: a drifted block keeps its lines")
    check_eq(bool(wr.find_block(led, "b004").get("drift")), True, "D-10: b004 is drift")

    # -- D-11: accepting relocations clears relocated_from and makes lint strict again ----
    accept_root = work / "accept" / "proj_a"
    accept_root.parent.mkdir(parents=True)
    shutil.copytree(FIXTURES / "proj_a", accept_root)
    accept_script = accept_root / "code/sample.R"
    led3 = ledger_path(work / "war_rooms_accept", "proj_a", "code/sample.R")
    build_ledger(accept_root, "code/sample.R", led3)
    accept_script.write_text("\n" + accept_script.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    moved = prep("verify", led3, "--project-root", accept_root, "--write")
    check_in("RELOCATED b001", moved.text, "a blank line on top relocates every block")
    check("WL-03" not in _overlap_probe(led3, accept_root, work / "probe_before.yaml"),
          "before accepting, a relocated ledger reports WL-03 overlap as a warning only")
    before = led3.read_bytes()
    prep("verify", led3, "--project-root", accept_root, "--accept-relocations")
    led = wr.load_ledger(led3)
    check(led3.read_bytes() != before, "D-11: --accept-relocations writes the ledger")
    check_eq([b.get("relocated_from") for b in led["blocks"]], [None] * len(led["blocks"]),
             "D-11: accepting clears every relocated_from")
    check_eq(led["script"]["sha256"], wr.wr_a1_file_hash(wr.wr_a1_lines(accept_script)),
             "D-11: accepting re-stamps script.sha256 from the current file")
    clean = lint(led3, accept_root)
    check_eq(clean.err.strip(), "", "D-11: an accepted ledger lints with no degraded warnings")
    check("WL-03" in _overlap_probe(led3, accept_root, work / "probe_after.yaml"),
          "D-11: after accepting, a WL-03 overlap is a failure again")

    # -- the refusals: drift must be resolved first, and lint gates the write (I2) --------
    drifted_bytes = led_path.read_bytes()
    refused = prep("verify", led_path, "--project-root", project, "--accept-relocations",
                   expect=1)
    check_in("REFUSED", refused.text, "accepting over a drifted block is refused")
    check_eq(led_path.read_bytes(), drifted_bytes, "a refused accept leaves the bytes alone")
    gap_root = work / "gap" / "proj_a"
    gap_root.parent.mkdir(parents=True)
    shutil.copytree(FIXTURES / "proj_a", gap_root)
    led4 = ledger_path(work / "war_rooms_gap", "proj_a", "code/sample.R")
    build_ledger(gap_root, "code/sample.R", led4)
    gap_script = gap_root / "code/sample.R"
    gap_script.write_text("# An inserted note.\n" + gap_script.read_text(encoding="utf-8"),
                          encoding="utf-8", newline="\n")
    prep("verify", led4, "--project-root", gap_root, "--write")
    gap_bytes = led4.read_bytes()
    gated = prep("verify", led4, "--project-root", gap_root, "--accept-relocations", expect=1)
    check_in("WL-03", gated.text, "an accept that would leave a line uncovered fails lint")
    check_eq(led4.read_bytes(), gap_bytes, "a lint-refused accept leaves the bytes alone")


# =========================================================================== case 11
# A blank line inside an open construct stays in its block (WR-S7 as amended, census
# D-12 and D-13). Each entry is (name, dialect, source, expected block ranges).
OPEN_CONSTRUCTS: list[tuple[str, str, str, list[tuple[int, int]]]] = [
    ("R function with a blank line in its body", "R",
     "f <- function(x) {\n  a <- 1\n\n  a + x\n}\n\ny <- f(2)\n",
     [(1, 5), (7, 7)]),
    ("R multi-line SQL string with a blank line", "R",
     'q <- "SELECT id\n\nFROM t"\n\nres <- run(q)\n',
     [(1, 3), (5, 5)]),
    ("Python docstring with a blank line", "Python",
     'def f():\n    """Summary.\n\n    Detail.\n    """\n    return 1\n\n\nprint(f())\n',
     [(1, 6), (9, 9)]),
    ("Python function body with a blank line", "Python",
     "def f():\n    x = 1\n\n    # then\n    return x\n\n\ny = f()\n",
     [(1, 5), (8, 8)]),
    ("Python multi-line SQL string with a blank line", "Python",
     'SQL = """\nSELECT id\n\nFROM t\n"""\n\nrun(SQL)\n',
     [(1, 5), (7, 7)]),
    ("Python class methods split at each def, not at the blank", "Python",
     "class A:\n    def f(self):\n        return 1\n\n    def g(self):\n        return 2\n",
     [(1, 1), (2, 3), (5, 6)]),
    ("Stata preserve/restore across a blank line", "Stata",
     "preserve\nkeep if x > 0\n\ncollapse (mean) y\nrestore\n\ngen z = 1\n",
     [(1, 5), (7, 7)]),
    ("Stata preserve/restore is never cut at a header", "Stata",
     "capture preserve\nkeep if x > 0\n* --- Summary ---\ncollapse (mean) y\nrestore\n"
     "* --- Next ---\ngen z = 1\n",
     [(1, 5), (6, 7)]),
    ("Stata brace inside a block comment", "Stata",
     "gen a = 1 /* opens { here */\n* --- Section ---\ngen b = 2\n",
     [(1, 1), (2, 3)]),
    ("Stata block comment across a blank line", "Stata",
     "/* Header.\n\n   More header. */\n\ngen x = 1\n\ngen y = 2\n",
     [(1, 3), (5, 5), (7, 7)]),
    ("Stata #delimit ; region", "Stata",
     "#delimit ;\nregress y x1\n  x2 ;\n\n* --- Section --- ;\ngen z = 1 ;\n#delimit cr\n"
     "\ngen w = 2\n",
     [(1, 7), (9, 9)]),
    ("Stata #delimit; with no space opens the region", "Stata",
     "#delimit;\nregress y x1\n\n  x2;\n#delimit cr\n\ngen w = 2\n",
     [(1, 5), (7, 7)]),
    ("Stata restore, preserve keeps it open", "Stata",
     "preserve\nkeep if x\nrestore, preserve\n\ngen z = 1\nrestore\n", [(1, 6)]),
]

# Unchanged behaviour the fix must keep: a blank line at depth zero is still a boundary.
CLOSED_CONSTRUCTS: list[tuple[str, str, str, list[tuple[int, int]]]] = [
    ("R apostrophe in a trailing comment opens no string", "R",
     "x <- 1 # it's fine\n\ny <- 2\n", [(1, 1), (3, 3)]),
    ("Python blank line then a top-level statement", "Python",
     "def f():\n    return 1\n\nx = f()\n", [(1, 2), (4, 4)]),
    ("R backtick name holding an apostrophe opens no string", "R",
     "`it's` <- 1\n\ny <- 2\n", [(1, 1), (3, 3)]),
    ("Python decorated def after a body with a blank line", "Python",
     "def f():\n    x = 1\n\n    return x\n\n@dec\ndef g():\n    pass\n",
     [(1, 4), (6, 8)]),
    ("Python apostrophe in a one-line string", "Python",
     "s = \"it's\"\n\nt = 2\n", [(1, 1), (3, 3)]),
    ("Stata restore closes the region", "Stata",
     "preserve\nkeep if x\nrestore\n\ngen z = 1\n", [(1, 3), (5, 5)]),
    ("Stata #delimit cr; closes the region", "Stata",
     "#delimit ;\nregress y x1\n  x2 ;\n#delimit cr;\n\ngen w = 2\n",
     [(1, 4), (6, 6)]),
    ("Stata program end closes an unrestored preserve", "Stata",
     "program define p\n    preserve\n    keep if x\nend\n\ngen z = 1\n",
     [(1, 4), (6, 6)]),
    ("Stata // comment line opens no block comment", "Stata",
     "// see /* here\ngen a = 1\n\ngen b = 2\n", [(1, 2), (4, 4)]),
    ("Stata block comment attaches to the program below it", "Stata",
     "gen a = 1\n/* Doc for p.\n   Two lines. */\nprogram define p\n    display 1\nend\n",
     [(1, 1), (2, 6)]),
    ("Rmd prose apostrophe and bracket carry nothing", "Rmd",
     "The author's note (see below.\n\n```{r}\nx <- 1\n```\n", [(1, 1), (3, 5)]),
]

# The starter copy as the pre-amendment segmenter cut it. A ledger written then must
# still lint and verify: re-segmentation changes new skeletons, never old ledgers.
STARTER_BLOCKS_BEFORE_WR_S7_AMENDMENT = [
    [1, 4], [6, 8], [10, 12], [14, 17], [19, 24], [26, 28], [30, 32], [34, 38], [40, 50],
    [52, 53], [55, 57], [59, 72], [74, 77], [79, 82], [84, 86], [88, 89], [91, 93],
    [95, 97], [99, 103], [105, 111], [113, 115], [117, 130], [132, 137], [139, 145],
    [147, 147], [149, 152], [154, 159], [161, 169], [171, 175], [177, 198],
]


def _algorithm_steps(text: str) -> list[str]:
    """The numbered steps, from `1. Read the file` through the WR-S7 closing sentence."""
    start = text.index("1. Read the file as UTF-8")
    end = text.index("only when it is inside one (WR-S7).", start)
    return [line.rstrip() for line in text[start:end].splitlines()]


def case_11_open_constructs(work: Path) -> str:
    """Blank lines inside a construct stay in its block; old ledgers stay valid (D-12, D-13)."""
    wrong = []
    for name, dialect, text, expected in OPEN_CONSTRUCTS + CLOSED_CONSTRUCTS:
        got = wr.segment(wr.split_lines(text), dialect)
        if got != expected:
            wrong.append(f"{name}: expected {expected}, got {got}")
    check(not wrong, "segmentation of open constructs:\n    " + "\n    ".join(wrong))

    # Partition still holds on every construct: no non-blank line outside a block.
    for name, dialect, text, _ in OPEN_CONSTRUCTS:
        lines = wr.split_lines(text)
        covered = [i for a, b in wr.segment(lines, dialect) for i in range(a, b + 1)]
        wanted = {i for i, line in enumerate(lines, start=1) if line.strip()}
        check(wanted <= set(covered) and len(covered) == len(set(covered)),
              f"{name}: every non-blank line sits in exactly one block (WR-S7)")

    # An old ledger stays valid: the starter copy under its pre-amendment ranges.
    project = work / "starter"
    (project / "code").mkdir(parents=True)
    (project / "PROJECT.md").write_text("# Starter-pipeline fixture\n", encoding="utf-8", newline="\n")
    script = project / "code" / "run_all.R"
    shutil.copyfile(STARTER, script)
    out = work / "old.yaml"
    prep("skeleton", script, "--project-root", project, "--out", out, "--fixture")
    led = wr.load_ledger(out)
    lines = wr.wr_a1_lines(script)
    template = led["blocks"][0]
    old_blocks = []
    for index, (start, end) in enumerate(STARTER_BLOCKS_BEFORE_WR_S7_AMENDMENT):
        block = json.loads(json.dumps(template))
        block["block_id"] = wr.block_id_for(index)
        block["lines"] = [start, end]
        block["evidence"]["sources"] = [f"code/run_all.R:{start}-{end}"]
        wr.rehash_block(block, lines)
        old_blocks.append(block)
    led["blocks"] = old_blocks
    wr.save_ledger(out, led)
    lint_green(out, project, "on a ledger segmented before the WR-S7 amendment")
    verified = prep("verify", out, "--project-root", project)
    check_in("OK: every block hash reproduces", verified.text,
             "a pre-amendment ledger verifies with no drift")

    # D-21: the library docstring and the segmentation reference state the same steps.
    reference = (REPO / "Infrastructure/rules/code-war-room-segmentation.md").read_text(
        encoding="utf-8")
    doc_steps = _algorithm_steps(wr.__doc__ or "")
    rule_steps = _algorithm_steps(reference)
    check_eq(doc_steps, rule_steps,
             "D-21: the war_room_lib docstring and code-war-room-segmentation.md must state "
             "the same segmentation steps")
    return (f"{len(OPEN_CONSTRUCTS)} open and {len(CLOSED_CONSTRUCTS)} closed constructs; "
            f"old ledger lints; docstring equals reference")


# =========================================================================== case 12
def _still_running(proc: subprocess.Popen, what: str) -> None:
    time.sleep(0.6)
    check(proc.poll() is None, f"D-15: {what} must wait while another process holds the "
                               f"ledger lock, but it finished (exit {proc.poll()})")


def case_12_ledger_lock(work: Path) -> str:
    """One lock around every ledger write, the file mode kept, and the bytes unchanged.

    Covers D-15 and D-18 (census 04) and I3/I8 of the Phase 3D plan.
    """
    from localapp import filelock  # the scripts directory is already on sys.path

    project = copy_project("proj_a", work)
    led_path = ledger_path(work / "war_rooms", "proj_a", "code/sample.R")
    build_ledger(project, "code/sample.R", led_path)

    # -- a CLI write waits for the holder, then applies its change on top of the holder's --
    # The test plays the server: it loads the ledger under the lock, lets the CLI start,
    # and saves its own change before releasing. Without a lock the CLI's merge would land
    # first and this save, made from the older load, would silently drop it.
    with filelock.locked(led_path):
        held = wr.load_ledger(led_path)
        cli = subprocess.Popen([sys.executable, str(PREP), "merge", str(led_path), "b003",
                                "--project-root", str(project)], cwd=str(REPO), text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            _still_running(cli, "`war_room_prep.py merge`")
        finally:
            wr.find_block(held, "b001")["flag_for_followup"] = True
            wr.save_ledger(led_path, held)
    out, _ = cli.communicate(timeout=30)
    check_eq(cli.returncode, 0, f"the merge runs once the lock is free:\n{out}")
    after = wr.load_ledger(led_path)
    check_eq(wr.find_block(after, "b001")["flag_for_followup"], True,
             "D-15: the holder's save survives the CLI's write")
    check(wr.find_block(after, "b004") is None and
          wr.find_block(after, "b003")["prediction"].get("merged_from") == ["b003", "b004"],
          "D-15: the CLI's merge survives the holder's save")
    check(filelock.lock_path(led_path).is_file(), "the lock file sits beside the ledger")

    # -- the server waits for a CLI that holds the lock ---------------------------------
    with server(led_path, project) as app:
        replies: list[dict] = []
        with filelock.locked(led_path):
            worker = threading.Thread(target=lambda: replies.append(
                app.answer("b002", "confirmed", endorsed=True, expect_ok=None)))
            worker.start()
            time.sleep(0.6)
            check(worker.is_alive() and not replies,
                  "D-15: the server must wait while a CLI holds the ledger lock")
        worker.join(timeout=30)
        check(replies and replies[0].get("ok"), f"the answer saves once the lock is free "
                                                f"({replies})")
    check_eq(wr.find_block(wr.load_ledger(led_path), "b002")["disposition"], "confirmed",
             "the server's answer reached the ledger")

    # -- a holder that never lets go: the refusal names its PID and what to do ----------
    release = threading.Event()
    taken = threading.Event()

    def hold() -> None:
        with filelock.locked(led_path):
            taken.set()
            release.wait(30)

    holder = threading.Thread(target=hold)
    holder.start()
    try:
        check(taken.wait(10), "the holder thread took the lock")
        try:
            with wr.locked_ledger(led_path, timeout=0.3):
                pass
        except wr.WarRoomError as exc:
            check_in(f"process {os.getpid()}", str(exc), "the timeout names the holder's PID")
            check_in("Stop the server", str(exc), "the timeout says what to do")
        else:
            raise CaseFailure("locked_ledger returned while another holder had the lock")
    finally:
        release.set()
        holder.join(timeout=30)

    # -- a save keeps the file's mode (mkstemp used to reset it to 0600) ----------------
    # Windows has no permission bits (any writable file reports 0o666), so D-18 is POSIX only.
    if sys.platform != "win32":
        os.chmod(led_path, 0o640)
        prep("verify", led_path, "--project-root", project, "--write")
        check_eq(oct(stat.S_IMODE(led_path.stat().st_mode)), oct(0o640),
                 "D-18: a save keeps the ledger's file mode")

    # -- ledger bytes are unchanged: every committed fixture ledger round-trips ---------
    for fixture in sorted((FIXTURES / "ledgers").rglob("ledger.yaml")):
        copy = work / "roundtrip" / fixture.parent.name / "ledger.yaml"
        copy.parent.mkdir(parents=True)
        wr.save_ledger(copy, wr.load_ledger(fixture))
        check_eq(copy.read_bytes(), fixture.read_bytes(),
                 f"I8: {fixture.relative_to(FIXTURES)} must round-trip byte for byte")
    return "CLI and server wait for the lock; timeout names the PID; mode kept; bytes kept"


# =========================================================================== case 13
APP = SCRIPTS / "war_room_app"
# Anything that turns a string into markup or script. The client builds every element with
# createElement and textContent, so none of these may appear in it (census D-14).
_UNSAFE_JS = re.compile(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|\beval\s*\(|"
                        r"new\s+Function|setTimeout\s*\(\s*[\"'`]")
_INLINE_HANDLER = re.compile(r"<[^>]*\son[a-z]+\s*=", re.IGNORECASE)
_INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>", re.IGNORECASE)


def _raw(port: int, method: str, path: str, headers: dict[str, str] | None = None,
         body: bytes | None = None) -> tuple[int, dict[str, str], bytes]:
    """One raw request: the caller sets every header, including Host."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for key, value in (headers or {}).items():
            conn.putheader(key, value)
        conn.endheaders(body)
        resp = conn.getresponse()
        return resp.status, {k.lower(): v for k, v in resp.getheaders()}, resp.read()
    finally:
        conn.close()


def case_13_app_security(work: Path) -> str:
    """The app on the shared kit: CSP everywhere, no inline script, origin, cap, routing.

    Covers D-14 and D-16 (census 04) and I1/I7 of the Phase 3D plan.
    """
    # -- static: no inline script or handler, and nothing that parses a string as HTML --
    index = (APP / "index.html").read_text(encoding="utf-8")
    check(not _INLINE_SCRIPT.search(index), "D-14: index.html carries no inline <script>")
    check(not _INLINE_HANDLER.search(index), "D-14: index.html carries no inline on*= handler")
    check_in('<script src="/app.js"></script>', index, "the behavior loads from app.js")
    app_js = (APP / "app.js").read_text(encoding="utf-8")
    found = sorted(set(_UNSAFE_JS.findall(app_js)))
    check(not found, f"D-14: app.js must not parse strings as markup or code: {found}")

    project = copy_project("proj_a", work)
    led_path = ledger_path(work / "war_rooms", "proj_a", "code/sample.R")
    build_ledger(project, "code/sample.R", led_path)
    # Ledger text is model-authored from untrusted comments: quotes, an apostrophe, and a
    # tag travel as data and are never interpreted.
    hostile = "it's \"quoted\" </script><img src=x onerror=alert(1)> ' onclick='x"
    led = wr.load_ledger(led_path)
    wr.find_block(led, "b001")["title"] = hostile
    wr.find_block(led, "b001")["prediction"]["what_it_does"] = hostile
    wr.save_ledger(led_path, led)

    with server(led_path, project, extra=["--open"]) as app:
        port = app.port
        good = {"Host": f"127.0.0.1:{port}"}
        responses = []

        def get(path: str, headers: dict[str, str] | None = None) -> tuple[int, dict, bytes]:
            out = _raw(port, "GET", path, headers if headers is not None else good)
            responses.append((f"GET {path}", out[1]))
            return out

        for path in ("/", "/index.html", "/app.js", "/api/state", "/api/state?x=1"):
            status, headers, _ = get(path)
            check_eq(status, 200, f"D-16: GET {path} is served (a query string still routes)")
        check(get("/app.js")[1]["content-type"].startswith("text/javascript"),
              "app.js is served as JavaScript")
        state = json.loads(get("/api/state")[2])
        check_eq(state["blocks"][0]["title"], hostile, "ledger text reaches the client verbatim")

        # -- I1: Host and Origin must name loopback on this very port ----------------------
        for label, headers in (
                ("a foreign Host", {"Host": "evil.example"}),
                ("a loopback Host on another port", {"Host": f"127.0.0.1:{port + 1}"}),
                ("a malformed Host port", {"Host": "127.0.0.1:abc"}),
                ("a foreign Origin", {**good, "Origin": "http://evil.example"}),
                ("a null Origin", {**good, "Origin": "null"}),
                ("an Origin on another port", {**good, "Origin": f"http://localhost:{port + 1}"})):
            check_eq(get("/api/state", headers)[0], 403, f"I1: GET with {label} is refused")
        payload = json.dumps({"block_id": "b002", "disposition": "confirmed",
                              "endorsed_prediction": True, "reviewer": "bglasner",
                              "reviewer_role": "author"}).encode("utf-8")
        post_head = {**good, "Content-Type": "application/json",
                     "Content-Length": str(len(payload))}
        status, headers, _ = _raw(port, "POST", "/api/answer",
                                  {**post_head, "Origin": "http://evil.example"}, payload)
        responses.append(("POST foreign origin", headers))
        check_eq(status, 403, "I1: a cross-origin POST is refused")

        # -- traversal and unknown paths -------------------------------------------------
        for path in ("/../war_room_server.py", "/%2e%2e/war_room_lib.py", "/app.js/../index.html",
                     "/war_room_app/app.js", "/ledger.yaml", "//etc/passwd"):
            status, headers, body = get(path)
            check(status in (400, 404), f"traversal: GET {path} is refused ({status})")
            check(b"import " not in body and b"schema_version" not in body,
                  f"traversal: GET {path} leaks no file")

        # -- the body cap, bad JSON, a non-object body, and a query string on POST --------
        big = b"x" * (64 * 1024 + 1)
        status, headers, _ = _raw(port, "POST", "/api/answer",
                                  {**good, "Content-Length": str(len(big))}, big)
        responses.append(("POST over cap", headers))
        check_eq(status, 413, "D-16: a body over the cap gets 413")
        for bad in (b"{not json", b"[1, 2]"):
            status, headers, _ = _raw(port, "POST", "/api/answer",
                                      {**post_head, "Content-Length": str(len(bad))}, bad)
            responses.append(("POST bad json", headers))
            check_eq(status, 400, f"a body of {bad!r} gets 400")
        status, headers, body = _raw(port, "POST", "/api/answer?from=test", post_head, payload)
        responses.append(("POST with query", headers))
        check_eq((status, json.loads(body).get("ok")), (200, True),
                 "D-16: a POST with a query string still routes")
        status, headers, _ = _raw(port, "HEAD", "/", good)
        responses.append(("HEAD /", headers))
        status, headers, _ = _raw(port, "PUT", "/api/answer", {**good, "Content-Length": "0"})
        responses.append(("PUT", headers))
        check_eq(status, 405, "PUT is refused")

        # -- I7: every response carries the CSP and the security headers ------------------
        for label, headers in responses:
            csp = headers.get("content-security-policy", "")
            check("script-src 'self'" in csp and "default-src 'none'" in csp
                  and "unsafe-inline" not in csp.split("script-src")[1].split(";")[0],
                  f"I7: {label} carries the CSP with no inline script ({csp!r})")
            check_eq(headers.get("x-content-type-options"), "nosniff", f"{label}: nosniff")
            check_eq(headers.get("x-frame-options"), "DENY", f"{label}: frame refusal")

        # -- D-16: a port already in use is a message, not a traceback ----------------------
        taken = run([sys.executable, SERVER, "--ledger", led_path, "--project-root", project,
                     "--port", str(port), "--no-browser"], expect=2)
        check_in("already in use", taken.text, "D-16: the port-in-use message")
        check("Traceback" not in taken.text, "D-16: no traceback for a port in use")

    # A browser that blocks (a BROWSER command, a text browser) must not stop the app
    # serving, and under CI no browser is started (the kit's open_browser_when_serving).
    from localapp import testkit
    testkit.probe_browser_open([sys.executable, str(SERVER), "--ledger", str(led_path),
                                "--project-root", str(project), "--port", "0"],
                               _PORT_LINE, work)

    usage = run([sys.executable, SERVER, "--help"])
    check_in("--no-browser", usage.text, "D-16: --no-browser is the opt-out, as on the board")
    check_in("--open", usage.text, "D-16: --open is still accepted")
    return f"{len(responses)} responses carry the CSP; origin, cap, traversal, routing"


# =========================================================================== runner
CASES: list[tuple[str, Callable[[Path], Any]]] = [
    ("case 1 — full path on sample.R", case_1_full_path),
    ("case 2 — divergence handoff", case_2_divergence),
    ("case 3 — resume and project namespace", case_3_resume_and_namespace),
    ("case 4 — drift and regression", case_4_drift),
    ("case 5 — merge and split", case_5_merge_split),
    ("case 6 — lint matrix and immutability", case_6_lint_matrix),
    ("case 7 — concurrency and origin", case_7_concurrency_and_origin),
    ("case 8 — starter pipeline", case_8_starter_pipeline),
    ("case 9 — WR-A1 golden hashes", case_9_wr_a1_golden),
    ("case 10 — duplicate content and accepted relocations", case_10_duplicate_content_drift),
    ("case 11 — open constructs and old ledgers", case_11_open_constructs),
    ("case 12 — ledger lock, file mode, and bytes", case_12_ledger_lock),
    ("case 13 — app security on the shared kit", case_13_app_security),
]


def assert_fixture_ledgers_labelled() -> None:
    """Completion rule 9: no fixture ledger may read as an agent's account of real code."""
    found = sorted((FIXTURES / "ledgers").rglob("ledger.yaml"))
    check(found, "the fixtures directory holds no ledgers")
    for path in found:
        led = wr.load_ledger(path)
        check_eq((led.get("session") or {}).get("fixture"), True,
                 f"{path.relative_to(REPO)} must carry session.fixture: true")
    # The fixtures are inputs to every other case, so their own validity belongs inside
    # the `war-room-tests` check rather than in whoever last edited them by hand.
    for path in found:
        result = wl.lint(wr.load_ledger(path), FIXTURES / "proj_a")
        check(result.ok,
              f"{path.relative_to(REPO)} does not pass lint:\n    "
              + "\n    ".join(f.line() for f in result.failures))
    modes = {(led_path.parent.name): (wr.load_ledger(led_path).get("session") or {}).get("mode")
             for led_path in found}
    check_eq(modes.get("ordered"), "ordered",
             "AC-B13: an `ordered` mode fixture ledger must exist")
    check_eq(modes.get("fast-forward"), "fast-forward",
             "AC-B13: a `fast-forward` mode fixture ledger must exist")


def repo_snapshot() -> dict[str, object]:
    """The repository state AC-T3 compares: the war-room ledgers and the status of `code/`.

    Taken before the cases run, because a project may hold its own ledgers and uncommitted
    edits to its scripts; the suite must leave both exactly as it found them.
    """
    war_rooms = REPO / "records/war_rooms"
    ledgers = tree_digest(war_rooms) if war_rooms.is_dir() else None
    status = subprocess.run(["git", "status", "--porcelain", "--", "code/"], cwd=str(REPO),
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return {"war_rooms": ledgers,
            "code_status": status.stdout.strip() if status.returncode == 0 else None}


def assert_nothing_escaped(work: Path, before: dict[str, object]) -> None:
    """AC-T3: the repository is exactly as the suite found it."""
    after = repo_snapshot()
    check_eq(after["war_rooms"], before["war_rooms"],
             "AC-T3: records/war_rooms/ must be byte-identical before and after a run")
    reports = CASE1.get("reports")
    if reports and Path(reports).is_dir():
        listing = sorted(p.name for p in Path(reports).iterdir())
        check_eq(listing, [Path(CASE1["html"]).name],
                 "AC-T3: the reviewed project holds only the rendered report")
    if before["code_status"] is not None and after["code_status"] is not None:
        check_eq(after["code_status"], before["code_status"],
                 "AC-T3: `git status --porcelain -- code/` must be unchanged by a run")


def main() -> int:
    started = time.monotonic()
    install_network_guard()
    try:
        self_test_network_guard()
    except CaseFailure as exc:
        print(f"FAIL network guard self-test: {exc}")
        return 1
    print("Network guard: a connect to a non-loopback address raises (AC-T4).")

    if not FIXTURES.is_dir():
        print(f"ENVIRONMENT: no fixtures at {FIXTURES}")
        return 2

    digest_before = tree_digest(FIXTURES)
    print(f"Fixtures digest (before): {digest_before}")

    failures = 0
    before = repo_snapshot()
    with tempfile.TemporaryDirectory(prefix="war-room-test-") as tmp:
        root = Path(tmp)
        try:
            assert_fixture_ledgers_labelled()
        except CaseFailure as exc:
            print(f"FAIL fixture labelling: {exc}")
            failures += 1

        for index, (name, func) in enumerate(CASES, start=1):
            work = root / f"case{index}"
            work.mkdir()
            case_started = time.monotonic()
            try:
                note = func(work)
            except Exception as exc:  # one failing case never stops the rest
                failures += 1
                print(f"FAIL {name}  ({time.monotonic() - case_started:.1f}s)")
                if isinstance(exc, CaseFailure):
                    print(f"  {exc}")
                else:
                    print("".join(traceback.format_exception(exc)).rstrip())
                continue
            suffix = f"  [{note}]" if isinstance(note, str) and note else ""
            print(f"PASS {name}  ({time.monotonic() - case_started:.1f}s){suffix}")

        try:
            assert_nothing_escaped(root, before)
        except CaseFailure as exc:
            print(f"FAIL repository cleanliness: {exc}")
            failures += 1

    digest_after = tree_digest(FIXTURES)
    print(f"Fixtures digest (after):  {digest_after}")
    if digest_after != digest_before:
        print("FAIL AC-T3: the run modified Infrastructure/scripts/war_room_fixtures/")
        failures += 1

    elapsed = time.monotonic() - started
    print(f"Elapsed: {elapsed:.1f}s (limit {TIME_LIMIT_SECONDS:.0f}s)")
    if elapsed > TIME_LIMIT_SECONDS:
        print(f"FAIL AC-T4: the suite took {elapsed:.1f}s, over its {TIME_LIMIT_SECONDS:.0f}s "
              f"budget; a maintenance check nobody waits for is a maintenance check nobody "
              f"runs")
        failures += 1

    if failures:
        print(f"FAILED: {failures} failure(s)")
        return 1
    print(f"OK: {len(CASES)} cases passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
