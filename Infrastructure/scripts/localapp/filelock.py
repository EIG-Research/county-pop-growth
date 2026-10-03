"""Advisory lock on a sibling `<file>.lock`, held around load, mutate, lint, and save.

A server and a CLI can both write one record. Without a lock across processes, each can
load the same version and the second save silently drops the first one's change. The lock
file holds the holder's PID so a waiter can name it; it is gitignored and skipped by
`testkit.tree_digest`, and it is never deleted, because deleting it would let a second
process lock a new file while the first still holds the old one.

POSIX uses `fcntl.flock`; Windows uses `msvcrt.locking` on one byte far past the PID, so a
waiter can still read who holds it. Both locks are released when the holder exits. Only where
neither exists are writers serialized within this process alone, with a warning.
"""

from __future__ import annotations

import os
import stat
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]
try:
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None  # type: ignore[assignment]

# Windows locks byte ranges, and a locked range cannot be read by other processes. Locking one
# byte past any content leaves the PID at offset 0 readable. Locking beyond EOF is allowed and
# does not grow the file.
_WIN_LOCK_OFFSET = 0x7FFFFFF0

DEFAULT_TIMEOUT = 10.0
POLL_SECONDS = 0.05


class LockError(Exception):
    """The lock could not be taken safely."""


class LockTimeout(LockError):
    """The lock stayed held for the whole timeout."""


_held = threading.local()           # per thread: lock file identity -> depth, for nesting
_fallback_guard = threading.Lock()
_fallback_locks: dict[tuple[int, int], threading.Lock] = {}
_warned = False


def lock_path(path: Path) -> Path:
    path = Path(path)
    return path.with_name(path.name + ".lock")


def _holder(lock: Path) -> str:
    try:
        pid = lock.read_text(encoding="utf-8").strip()
    except OSError:
        pid = ""
    return f"process {pid}" if pid.isdigit() else "another process"


def _timeout(path: Path, lock: Path, timeout: float) -> LockTimeout:
    return LockTimeout(
        f"{Path(path).name} is locked by {_holder(lock)} (lock file {lock}); waited "
        f"{timeout:g} s. Stop the server that holds it, or retry when it is idle.")


@contextmanager
def locked(path: Path, timeout: float = DEFAULT_TIMEOUT) -> Iterator[None]:
    """Hold the lock for `path`, waiting up to `timeout` seconds; raise `LockTimeout`."""
    lock = lock_path(path)
    fd = _open_lock(lock)
    st = os.fstat(fd)
    key = (st.st_dev, st.st_ino)  # the same file however its path is spelled
    depth = getattr(_held, "depth", None)
    if depth is None:
        depth = _held.depth = {}
    if depth.get(key):
        os.close(fd)
        depth[key] += 1
        try:
            yield
        finally:
            depth[key] -= 1
        return
    if fcntl is not None:
        release = _acquire_flock(path, lock, fd, timeout)
    elif msvcrt is not None:
        release = _acquire_msvcrt(path, lock, fd, timeout)
    else:
        os.close(fd)
        release = _acquire_fallback(path, lock, key, timeout)
    depth[key] = 1
    try:
        yield
    finally:
        depth[key] = 0
        release()


def _open_lock(lock: Path) -> int:
    """Open the lock file, refusing a symlink, a hard link, or anything not a regular file.
    The lock is truncated to write the PID, so any link would empty the file it names; the
    check runs before anything is written."""
    try:
        if hasattr(os, "O_NOFOLLOW"):
            fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o666)
        else:
            fd = _open_lock_without_nofollow(lock)
    except LockError:
        raise
    except OSError as exc:
        raise LockError(f"cannot open lock file {lock} ({exc}); remove it if it is a "
                        f"symlink or not a regular file") from None
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        os.close(fd)
        raise LockError(f"lock file {lock} is not a regular file with one link; remove it "
                        f"and retry")
    return fd


def _open_lock_without_nofollow(lock: Path) -> int:
    """Windows has no O_NOFOLLOW. Create the lock exclusively when it is new; otherwise refuse
    a symlink or reparse point by lstat and confirm the opened file is the one inspected, so a
    link swapped in between is caught."""
    try:
        return os.open(lock, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o666)
    except FileExistsError:
        pass
    before = os.lstat(lock)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if stat.S_ISLNK(before.st_mode) or getattr(before, "st_file_attributes", 0) & reparse:
        raise LockError(f"lock file {lock} is a symlink or reparse point; remove it and retry")
    fd = os.open(lock, os.O_RDWR)
    after = os.fstat(fd)
    if (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino):
        os.close(fd)
        raise LockError(f"lock file {lock} changed while it was opened; remove it and retry")
    return fd


def _acquire_msvcrt(path: Path, lock: Path, fd: int, timeout: float):
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.lseek(fd, _WIN_LOCK_OFFSET, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            break
        except OSError:
            if time.monotonic() >= deadline:
                os.close(fd)
                raise _timeout(path, lock, timeout) from None
            time.sleep(POLL_SECONDS)

    def release() -> None:
        try:
            os.ftruncate(fd, 0)
            os.lseek(fd, _WIN_LOCK_OFFSET, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        finally:
            os.close(fd)

    try:
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, f"{os.getpid()}\n".encode("ascii"))
    except BaseException:
        release()
        raise
    return release


def _acquire_flock(path: Path, lock: Path, fd: int, timeout: float):
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.monotonic() >= deadline:
                os.close(fd)
                raise _timeout(path, lock, timeout) from None
            time.sleep(POLL_SECONDS)

    def release() -> None:
        try:
            os.ftruncate(fd, 0)
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    try:
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode("ascii"))
    except BaseException:
        release()
        raise
    return release


def _acquire_fallback(path: Path, lock: Path, key: tuple[int, int], timeout: float):
    global _warned
    if not _warned:
        _warned = True
        print("warning: neither fcntl nor msvcrt is available, so only writers in this process are "
              "serialized; stop the server before running a CLI that writes", file=sys.stderr)
    with _fallback_guard:
        inner = _fallback_locks.setdefault(key, threading.Lock())
    if not inner.acquire(timeout=timeout):
        raise _timeout(path, lock, timeout)
    return inner.release
