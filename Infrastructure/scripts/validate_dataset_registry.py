#!/usr/bin/env python3
"""Validate the dataset registry: structure, provenance, and verification status.

The registry (Infrastructure/references/datasets/registry.yaml) is read by the review
agents and extended by the data-dictionary agent. The field reference is
Infrastructure/references/datasets/README.md; this script is the check.

`verification` records how far an entry has been checked, independent of `layer`:

  - `unverified` -> nobody has signed it against a source; a lead, not an authority.
  - `parsed`     -> an agent extracted it from a cited source; confirm before relying on it.
  - `verified`   -> a person checked it against `sources` and signed `verified_by` and
                    `verified_on`.

`layer` says where an entry lives. `template` entries ship in the template registry;
`project` entries live in the project's overlay, `data/docs/dataset-registry.yaml` (census
F32, owner default O10), so upstream template updates never collide with project edits. An
overlay entry whose `id` names a template dataset extends it with variables, vintages, and
docs only; the curated metadata stays in the template. Per-variable entries carry their own
`verification`.

Tested by Infrastructure/scripts/test_knowledge_stores.py.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from localapp.yamlio import Loader  # noqa: E402  (exits with an install hint without PyYAML)

import yaml  # noqa: E402

DATASET_REQUIRED_FIELDS = {"id", "name", "layer", "verification"}
# An overlay entry that extends a template dataset may carry only these keys.
EXTENSION_KEYS = {"id", "layer", "verification", "sources", "verified_by", "verified_on",
                  "vintages", "variables", "docs", "notes"}
TEMPLATE_REGISTRY = "Infrastructure/references/datasets/registry.yaml"
PROJECT_OVERLAY = "data/docs/dataset-registry.yaml"
ALLOWED_LAYERS = {"template", "project"}
ALLOWED_VERIFICATION = {"unverified", "parsed", "verified"}
ALLOWED_KINDS = {"survey", "administrative", "aggregate"}
ALLOWED_SEVERITY = {"HIGH", "MEDIUM", "LOW"}
# Per-variable required fields. Vintage and source are mandatory because the
# registry's value over a plain codebook is that every documented variable is
# pinned to the vintage it describes and to an authoritative source. An
# unconfirmed value is recorded as a "[unverified: ...]" string, not omitted.
VARIABLE_REQUIRED_FIELDS = ("vintage", "source")
IDENTIFICATION_KEYS = {"file_patterns", "loaders", "comments", "signal_variables"}
WEIGHT_KEYS = {"context", "source_name", "ipums_name", "notes"}
# A known variable is one name as the codebook spells it, with at most one `*` standing for a
# wave or replicate number ("R*WTRESP"). Spaces mean a description, not a name.
VARIABLE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\*[A-Za-z0-9_]*)?$")
# Column names common enough to appear in any project; they cannot identify a dataset.
GENERIC_SIGNALS = {"age", "count", "county", "cpi", "emp", "employment", "gdp", "id", "income",
                   "race", "sex", "state", "total", "unemployment", "urate", "value", "wage",
                   "wages", "weight", "wgt", "wt", "y1", "year"}


def load_registry(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.load(fh, Loader=Loader)  # noqa: S506 - Loader is a SafeLoader subclass


def is_iso_date(value: Any) -> bool:
    if isinstance(value, dt.date):
        return True
    if not isinstance(value, str):
        return False
    try:
        dt.date.fromisoformat(value)
        return True
    except ValueError:
        return False


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_unverified(value: Any) -> bool:
    """A '[unverified: ...]' marker satisfies presence requirements."""
    return isinstance(value, str) and value.strip().lower().startswith("[unverified")


def validate_sources(label: str, sources: Any, errors: list[str]) -> None:
    if not isinstance(sources, list):
        errors.append(f"{label}: `sources` must be a list of {{title, url}} mappings.")
        return
    for s_index, source in enumerate(sources, start=1):
        s_label = f"{label} source #{s_index}"
        if not isinstance(source, dict):
            errors.append(f"{s_label}: each source must be a mapping with `title` and `url`.")
            continue
        if not _text(source.get("title")):
            errors.append(f"{s_label}: `title` must be a non-empty string.")
        url = source.get("url")
        if not (_text(url) and url.startswith(("http://", "https://"))):
            errors.append(f"{s_label}: `url` must start with `http://` or `https://`.")


def validate_provenance(label: str, entry: dict, errors: list[str]) -> None:
    """Provenance fields are optional, but a `verified` entry needs all three signed."""
    if "sources" in entry:
        validate_sources(label, entry["sources"], errors)
    if "verified_by" in entry and not _text(entry["verified_by"]):
        errors.append(f"{label}: `verified_by` must name the person who checked the entry.")
    if "verified_on" in entry and not is_iso_date(entry["verified_on"]):
        errors.append(f"{label}: `verified_on` must be an ISO date (`YYYY-MM-DD`).")
    if entry.get("verification") == "verified":
        signed = (isinstance(entry.get("sources"), list) and entry["sources"]
                  and _text(entry.get("verified_by")) and is_iso_date(entry.get("verified_on")))
        if not signed:
            errors.append(
                f"{label}: `verified` requires `sources`, `verified_by`, and `verified_on`; "
                f"sign it or mark it `unverified`."
            )
    elif "verified_by" in entry or "verified_on" in entry:
        errors.append(
            f"{label}: `verified_by`/`verified_on` are set but `verification` is "
            f"`{entry.get('verification')}`; a signature belongs only on a `verified` entry."
        )


def validate_weights(label: str, weights: Any, errors: list[str]) -> None:
    if weights == "not_applicable":
        return
    if not isinstance(weights, list):
        errors.append(
            f"{label}: `weights` must be a list of weight mappings or the string "
            f"`not_applicable`."
        )
        return
    for w_index, weight in enumerate(weights, start=1):
        w_label = f"{label} weight #{w_index}"
        if not isinstance(weight, dict):
            errors.append(f"{w_label}: each weight must be a mapping.")
            continue
        if not _text(weight.get("context")):
            errors.append(f"{w_label}: `context` must be a non-empty string.")
        unknown = set(weight) - WEIGHT_KEYS
        if unknown:
            errors.append(
                f"{w_label}: unknown keys {', '.join(sorted(unknown))}; a weight has `context`, "
                f"`source_name` (the publisher's name), `ipums_name`, and `notes`."
            )
        if not any(_text(weight.get(k)) for k in ("source_name", "ipums_name")):
            errors.append(f"{w_label}: must specify `source_name`, `ipums_name`, or both.")


def _string_list(label: str, key: str, value: Any, errors: list[str]) -> list[str]:
    if not isinstance(value, list) or not all(_text(v) for v in value):
        errors.append(f"{label}: `{key}` must be a list of non-empty strings (use [] if none).")
        return []
    return value


def validate_identification(label: str, ds: dict, errors: list[str]) -> None:
    """Signals identify a dataset in code; known variables confirm a name is real."""
    ident = ds.get("identification")
    if isinstance(ident, dict) and "variable_names" in ident:
        errors.append(
            f"{label}: `identification.variable_names` is retired; list real codebook names in "
            f"`known_variables` and the distinctive ones in `identification.signal_variables`."
        )
    known = _string_list(label, "known_variables", ds.get("known_variables", []), errors)
    for name in known:
        if not VARIABLE_NAME.match(name):
            errors.append(
                f"{label}: known variable `{name}` is not a variable name (letters, digits, `_`, "
                f"at most one `*`); record a description in `notes` or `[unverified: ...]` instead."
            )
    if ident is None:
        return
    if not isinstance(ident, dict):
        errors.append(f"{label}: `identification` must be a mapping.")
        return
    unknown = set(ident) - IDENTIFICATION_KEYS - {"variable_names"}
    if unknown:
        errors.append(
            f"{label}: unknown `identification` keys {', '.join(sorted(unknown))}; allowed: "
            f"{', '.join(sorted(IDENTIFICATION_KEYS))}."
        )
    for key in IDENTIFICATION_KEYS - {"signal_variables"}:
        if key in ident:
            _string_list(label, f"identification.{key}", ident[key], errors)
    signals = _string_list(label, "identification.signal_variables",
                           ident.get("signal_variables", []), errors)
    for name in signals:
        if name.lower() in GENERIC_SIGNALS:
            errors.append(
                f"{label}: `{name}` is too generic to identify a dataset; keep it in "
                f"`known_variables` only."
            )
        elif name not in known:
            errors.append(f"{label}: signal variable `{name}` is not in `known_variables`.")


def validate_pitfalls(label: str, pitfalls: Any, errors: list[str]) -> None:
    if not isinstance(pitfalls, list):
        errors.append(f"{label}: `pitfalls` must be a list (use [] if none).")
        return
    seen_ids: set[str] = set()
    for p_index, pitfall in enumerate(pitfalls, start=1):
        p_label = f"{label} pitfall #{p_index}"
        if not isinstance(pitfall, dict):
            errors.append(f"{p_label}: each pitfall must be a mapping.")
            continue
        pid = pitfall.get("id")
        if not _text(pid):
            errors.append(f"{p_label}: `id` must be a non-empty string.")
        else:
            if pid in seen_ids:
                errors.append(f"{p_label}: duplicate pitfall `id` `{pid}` within dataset.")
            seen_ids.add(pid)
        if not _text(pitfall.get("description")):
            errors.append(f"{p_label}: `description` must be a non-empty string.")
        if pitfall.get("severity") not in ALLOWED_SEVERITY:
            errors.append(
                f"{p_label}: `severity` must be one of: {', '.join(sorted(ALLOWED_SEVERITY))}."
            )


def validate_variables(label: str, variables: Any, errors: list[str]) -> None:
    if not isinstance(variables, list):
        errors.append(f"{label}: `variables` must be a list (use [] if none).")
        return
    seen_names: set[str] = set()
    for v_index, var in enumerate(variables, start=1):
        v_label = f"{label} variable #{v_index}"
        if not isinstance(var, dict):
            errors.append(f"{v_label}: each variable must be a mapping.")
            continue
        name = var.get("name")
        if not _text(name):
            errors.append(f"{v_label}: `name` must be a non-empty string.")
        else:
            if name in seen_names:
                errors.append(f"{v_label}: duplicate variable `name` `{name}` within dataset.")
            seen_names.add(name)
            v_label = f"{label} variable `{name}`"
        for field in VARIABLE_REQUIRED_FIELDS:
            value = var.get(field)
            if not (_text(value) or _is_unverified(value)):
                errors.append(
                    f"{v_label}: `{field}` is required (use a value or an explicit "
                    f"`[unverified: ...]` marker). Project variables must be vintage-pinned "
                    f"and sourced."
                )
        verification = var.get("verification", "parsed")
        if verification not in ALLOWED_VERIFICATION:
            errors.append(
                f"{v_label}: `verification` must be one of: "
                f"{', '.join(sorted(ALLOWED_VERIFICATION))} (default `parsed`)."
            )


def validate_docs(label: str, docs: Any, repo_root: Path, errors: list[str]) -> None:
    if not isinstance(docs, list):
        errors.append(f"{label}: `docs` must be a list of repository-relative file paths (use [] if none).")
        return
    for d_index, doc in enumerate(docs, start=1):
        d_label = f"{label} doc #{d_index}"
        if not _text(doc):
            errors.append(f"{d_label}: each doc path must be a non-empty string.")
            continue
        if doc.startswith("/"):
            errors.append(f"{d_label}: doc path must be repository-relative, not absolute: `{doc}`.")
            continue
        path_obj = (repo_root / doc).resolve()
        if not path_obj.exists():
            errors.append(f"{d_label}: doc path does not exist: `{doc}`.")
        elif path_obj.is_dir():
            errors.append(f"{d_label}: doc path points to a directory, expected a file: `{doc}`.")


def validate_registry(registry: Any, repo_root: Path, *, overlay: bool = False,
                      template_ids: frozenset[str] = frozenset()
                      ) -> tuple[list[str], list[str], int]:
    """Check one registry file. `overlay` marks a project overlay, whose entries are all
    `layer: project`; `template_ids` are the template datasets an overlay entry may extend.
    Doc paths resolve from `repo_root` (the project root for an overlay)."""
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(registry, dict):
        return ["Registry root must be a YAML mapping."], warnings, 0

    if not isinstance(registry.get("version"), int):
        errors.append("Top-level `version` must be an integer.")
    if not is_iso_date(registry.get("last_updated")):
        errors.append("Top-level `last_updated` must be an ISO date (`YYYY-MM-DD`).")

    datasets = registry.get("datasets")
    if datasets is None:
        errors.append("Top-level `datasets` key is missing.")
        return errors, warnings, 0
    if not isinstance(datasets, list):
        errors.append("Top-level `datasets` must be a list.")
        return errors, warnings, 0

    seen_ids: set[str] = set()

    for index, ds in enumerate(datasets, start=1):
        label = f"dataset #{index}"
        if not isinstance(ds, dict):
            errors.append(f"{label}: dataset must be a mapping.")
            continue

        ds_id = ds.get("id")
        extends = overlay and ds_id in template_ids
        missing = DATASET_REQUIRED_FIELDS - set(ds.keys()) - ({"name"} if extends else set())
        if missing:
            errors.append(f"{label}: missing required keys: {', '.join(sorted(missing))}.")

        if not _text(ds_id):
            errors.append(f"{label}: `id` must be a non-empty string.")
        else:
            if ds_id in seen_ids:
                errors.append(f"{label}: duplicate dataset `id` `{ds_id}`.")
            seen_ids.add(ds_id)
            label = f"dataset `{ds_id}`"

        if "name" in ds or not extends:
            if not _text(ds.get("name")):
                errors.append(f"{label}: `name` must be a non-empty string.")

        layer = ds.get("layer")
        if layer not in ALLOWED_LAYERS:
            errors.append(f"{label}: `layer` must be one of: {', '.join(sorted(ALLOWED_LAYERS))}.")
        elif overlay and layer != "project":
            errors.append(f"{label}: an overlay entry is `layer: project`; template entries live in "
                          f"`{TEMPLATE_REGISTRY}`.")
        elif not overlay and layer != "template":
            errors.append(f"{label}: a `project` entry belongs in the project overlay "
                          f"`{PROJECT_OVERLAY}`, not the template registry.")
        if extends:
            curated = set(ds) - EXTENSION_KEYS - {"name"}
            if curated:
                errors.append(
                    f"{label}: extends the template dataset `{ds_id}`, so it may add only "
                    f"variables, vintages, docs, and provenance; move "
                    f"{', '.join(sorted(curated))} to a template change."
                )
        if ds.get("verification") not in ALLOWED_VERIFICATION:
            errors.append(
                f"{label}: `verification` must be one of: {', '.join(sorted(ALLOWED_VERIFICATION))}."
            )
        validate_provenance(label, ds, errors)

        kind = ds.get("kind")
        if kind is not None and kind not in ALLOWED_KINDS:
            errors.append(f"{label}: `kind` (if present) must be one of: {', '.join(sorted(ALLOWED_KINDS))}.")

        validate_identification(label, ds, errors)
        if "weights" in ds:
            validate_weights(label, ds["weights"], errors)
        if "pitfalls" in ds:
            validate_pitfalls(label, ds["pitfalls"], errors)
        if "variables" in ds:
            validate_variables(label, ds["variables"], errors)
        if "docs" in ds:
            validate_docs(label, ds["docs"], repo_root, errors)

    if not datasets:
        warnings.append("Registry has no datasets yet.")

    return errors, warnings, len(datasets)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the template dataset registry and a project's overlay.")
    parser.add_argument("--registry", default=TEMPLATE_REGISTRY,
                        help="Template registry path, relative to --repo-root.")
    parser.add_argument("--repo-root", default=None,
                        help="Template repository root. Defaults to the script's repository.")
    parser.add_argument("--project-root", default=None,
                        help="Project whose overlay to check. Defaults to --repo-root.")
    parser.add_argument("--overlay", default=PROJECT_OVERLAY,
                        help="Overlay path, relative to --project-root; skipped when absent.")
    return parser.parse_args(argv)


def _load(path: Path, what: str) -> tuple[Any, str | None]:
    if not path.exists():
        return None, f"{what} file does not exist: {path}"
    try:
        return load_registry(path), None
    except yaml.YAMLError as exc:
        return None, f"{what} is not valid YAML: {exc}"


def _report(what: str, errors: list[str], warnings: list[str], count: int) -> None:
    stream = sys.stderr if errors else sys.stdout
    verdict = (f"failed with {len(errors)} error(s)" if errors
               else f"passed for {count} dataset{'' if count == 1 else 's'}")
    print(f"{what} validation {verdict} and {len(warnings)} warning(s).", file=stream)
    for err in errors:
        print(f"- ERROR: {err}", file=stream)
    for warn in warnings:
        print(f"- WARNING: {warn}", file=stream)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    script_root = Path(__file__).resolve().parents[2]
    repo_root = Path(args.repo_root).resolve() if args.repo_root else script_root
    project_root = Path(args.project_root).resolve() if args.project_root else repo_root

    registry, problem = _load((repo_root / args.registry).resolve(), "Dataset registry")
    if problem:
        print(f"ERROR: {problem}", file=sys.stderr)
        return 1
    errors, warnings, count = validate_registry(registry, repo_root)
    _report("Dataset registry", errors, warnings, count)
    failed = bool(errors)

    overlay_path = (project_root / args.overlay).resolve()
    if not overlay_path.exists():
        print(f"No project overlay at {args.overlay}; nothing to check there.")
        return 1 if failed else 0
    overlay, problem = _load(overlay_path, "Project overlay")
    if problem:
        print(f"ERROR: {problem}", file=sys.stderr)
        return 1
    template_ids = frozenset(d["id"] for d in registry.get("datasets") or []
                             if isinstance(d, dict) and isinstance(d.get("id"), str))
    errors, warnings, count = validate_registry(overlay, project_root, overlay=True,
                                                template_ids=template_ids)
    _report(f"Project overlay {args.overlay}", errors, warnings, count)
    return 1 if failed or errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
