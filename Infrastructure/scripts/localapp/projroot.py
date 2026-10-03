"""Project-root resolution: which reviewed project a record belongs to.

The root is never stored in a record. A record stores the project id, the root's basename,
and every command checks the root it was given, or found, against that id. An explicit
`--project-root` is checked too, so a root pointed at the wrong project fails before any
file is read from it.
"""

from __future__ import annotations

from pathlib import Path


class ProjectRootError(Exception):
    """No acceptable project root; the message names the flag that fixes it."""


def _require_id(expected_id: str, record: str) -> str:
    pid = str(expected_id or "").strip()
    if not pid:
        raise ProjectRootError(f"{record} has no project.id; pass --project-root <dir>")
    return pid


def check_project_id(root: Path, expected_id: str, *, record: str = "the record") -> None:
    """The root's basename must equal the recorded project id."""
    pid = _require_id(expected_id, record)
    if Path(root).name != pid:
        raise ProjectRootError(
            f"project root basename {Path(root).name!r} does not match the project.id "
            f"{pid!r} in {record}; pass --project-root <dir> for the right project")


def resolve_project_root(explicit: str | Path | None, expected_id: str, *,
                         record: str = "the record") -> Path:
    """The flag wins; otherwise the nearest `PROJECT.md` root at or above the working
    directory, accepted only when its basename is the project id. The working directory is
    never a silent fallback."""
    pid = _require_id(expected_id, record)
    if explicit:
        root = Path(explicit).expanduser().resolve()
        if not (root / "PROJECT.md").is_file():
            raise ProjectRootError(f"--project-root {root} does not contain PROJECT.md")
        check_project_id(root, pid, record=record)
        return root
    here = Path.cwd().resolve()
    for candidate in (here, *here.parents):
        if (candidate / "PROJECT.md").is_file():
            if candidate.name == pid:
                return candidate
            raise ProjectRootError(
                f"nearest PROJECT.md root is {candidate} (basename {candidate.name!r}) but "
                f"{record} records project.id {pid!r}; pass --project-root <dir> to name the "
                f"reviewed project explicitly")
    raise ProjectRootError(f"no PROJECT.md found at or above {here}; pass --project-root "
                           f"<dir> to name the reviewed project explicitly")
