"""YAML load and save for local-app records.

The caller decides key order and which values render inline; this module only supplies the
pieces, so each tool's files keep the exact bytes they have today.
"""

from __future__ import annotations

import os
import secrets
import stat
import time
from pathlib import Path
from typing import Any, Sequence

try:
    import yaml
except ImportError:  # pragma: no cover
    raise SystemExit("PyYAML is required: python -m pip install pyyaml")


class Loader(yaml.SafeLoader):
    """SafeLoader without the timestamp resolver, so every timestamp stays a string."""


Loader.yaml_implicit_resolvers = {
    key: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


class FlowList(list):
    """A list rendered inline: `lines: [42, 51]`."""


class FlowMap(dict):
    """A mapping rendered inline: `text_floor: {result: pass, smallest_pt: 8.8}`."""


class _Dumper(yaml.SafeDumper):
    pass


_Dumper.add_representer(
    FlowList, lambda d, v: d.represent_sequence("tag:yaml.org,2002:seq", v, flow_style=True))
_Dumper.add_representer(
    FlowMap, lambda d, v: d.represent_mapping("tag:yaml.org,2002:map", v.items(),
                                              flow_style=True))


class _LiteralDumper(_Dumper):
    pass


def _represent_str(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    """Multi-line text as a literal block, so notes read verbatim. PyYAML falls back to a
    quoted scalar when a literal block cannot hold the string exactly."""
    return dumper.represent_scalar("tag:yaml.org,2002:str", value,
                                   style="|" if "\n" in value else None)


_LiteralDumper.add_representer(str, _represent_str)


def reorder(mapping: Any, order: Sequence[str]) -> Any:
    """Known keys in `order`, then any other keys as they were. Non-dicts pass through."""
    if not isinstance(mapping, dict):
        return mapping
    out = {k: mapping[k] for k in order if k in mapping}
    out.update({k: v for k, v in mapping.items() if k not in out})
    return out


def dump_yaml(data: Any, *, literal_multiline: bool) -> str:
    """Block-style YAML in the caller's key order, 100 columns, Unicode kept."""
    return yaml.dump(data, Dumper=_LiteralDumper if literal_multiline else _Dumper,
                     sort_keys=False, allow_unicode=True, default_flow_style=False, width=100)


REPLACE_ATTEMPTS = 20
REPLACE_WAIT_SECONDS = 0.05


def _temp_beside(path: Path) -> tuple[int, Path]:
    """A new file next to `path`, created with the umask's mode rather than mkstemp's 0600."""
    while True:
        tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
        try:
            return os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666), tmp
        except FileExistsError:
            continue


def atomic_write_text(path: Path, text: str) -> None:
    """Write through a temporary file in the same directory, then replace, with LF endings.

    A half-written record would lose a session, so the target is only ever replaced whole.
    An existing file keeps its mode. On Windows a replace fails while another process has
    the file open; that is transient, so the replace is retried for up to a second.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode: int | None = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        mode = None
    fd, tmp = _temp_beside(path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            if mode is not None:
                if hasattr(os, "fchmod"):
                    os.fchmod(fh.fileno(), mode)
                else:  # pragma: no cover - Windows
                    os.chmod(tmp, mode)
            os.fsync(fh.fileno())  # the bytes are on disk before the rename publishes them
        for attempt in range(REPLACE_ATTEMPTS):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == REPLACE_ATTEMPTS - 1:
                    raise
                time.sleep(REPLACE_WAIT_SECONDS)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    _fsync_dir(path.parent)


def _fsync_dir(directory: Path) -> None:
    """Persist the rename itself where the OS allows fsync on a directory (not Windows)."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)
