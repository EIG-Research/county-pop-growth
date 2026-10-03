#!/usr/bin/env python3
"""Tests for the knowledge-store validators: the dataset registry and the literature catalog.

`python3 Infrastructure/scripts/test_knowledge_stores.py` from anywhere. One `PASS` line per
case. Each case plants a good or bad entry in a scratch copy and checks the validator's
verdict, so a validator that stops catching a planted defect fails here. The shipped stores
are validated too. Exit codes: 0 pass, 1 fail, 2 unusable environment.

Dependencies: Python 3.11+ and PyYAML.
"""

from __future__ import annotations

import contextlib
import copy
import fnmatch
import datetime as dt
import io
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any, Callable

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent.parent
sys.path.insert(0, str(SCRIPTS))

try:
    import check_catalog_staleness as ccs  # noqa: E402
    import validate_dataset_registry as vdr  # noqa: E402
    import validate_literature_catalog as vlc  # noqa: E402
except (ImportError, SystemExit) as exc:
    print(f"ENVIRONMENT: {exc}")
    raise SystemExit(2)

CASES: list[Callable[[], None]] = []


def case(fn: Callable[[], None]) -> Callable[[], None]:
    CASES.append(fn)
    return fn


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


# --------------------------------------------------------------------------- registry helpers
GOOD_DATASET: dict[str, Any] = {
    "id": "demo",
    "name": "Demo Survey",
    "layer": "template",
    "verification": "unverified",
    "kind": "survey",
    "agency": "Demo Agency",
    "identification": {"file_patterns": ["demo_*"], "loaders": [], "comments": ["Demo Survey"],
                       "signal_variables": ["DEMOWT"]},
    "known_variables": ["DEMOWT", "DEMO_ID", "R*WT"],
    "weights": [{"context": "Person-level", "source_name": "DEMOWT", "notes": "Person weight."}],
    "pitfalls": [],
    "currency": {"search_strategy": '"Demo Survey" latest release'},
    "vintages": [],
    "variables": [],
    "docs": [],
}


def registry(*datasets: dict[str, Any]) -> dict[str, Any]:
    return {"version": 2, "last_updated": "2026-09-29", "datasets": list(datasets)}


def dataset(**changes: Any) -> dict[str, Any]:
    ds = copy.deepcopy(GOOD_DATASET)
    for key, value in changes.items():
        if value is None:
            ds.pop(key, None)
        else:
            ds[key] = value
    return ds


def registry_verdict(doc: dict[str, Any], **overlay: Any) -> tuple[list[str], list[str]]:
    with tempfile.TemporaryDirectory() as tmp:
        errors, warnings, _ = vdr.validate_registry(doc, Path(tmp), **overlay)
    return errors, warnings


def assert_rejected(doc: dict[str, Any], fragment: str, **overlay: Any) -> None:
    errors, _ = registry_verdict(doc, **overlay)
    expect(any(fragment in e for e in errors),
           f"expected an error containing {fragment!r}; got {errors or 'no errors'}")


def assert_accepted(doc: dict[str, Any], **overlay: Any) -> list[str]:
    errors, warnings = registry_verdict(doc, **overlay)
    expect(not errors, f"expected no errors; got {errors}")
    return warnings


OVERLAY = {"overlay": True, "template_ids": frozenset({"cps"})}


SIGNATURE = {"sources": [{"title": "Demo codebook 2024", "url": "https://example.gov/codebook"}],
             "verified_by": "A. Reviewer", "verified_on": "2026-09-29"}


# --------------------------------------------------------------------------- registry cases
@case
def registry_shipped_file_passes() -> None:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        status = vdr.main([])
    expect(status == 0, f"the shipped registry fails validation:\n{out.getvalue()}")


@case
def registry_verification_independent_of_layer() -> None:
    for layer, where in (("template", {}), ("project", OVERLAY)):
        for status in ("unverified", "parsed"):
            assert_accepted(registry(dataset(layer=layer, verification=status)), **where)
        assert_accepted(registry(dataset(layer=layer, verification="verified", **SIGNATURE)),
                        **where)


@case
def registry_project_entries_live_in_the_overlay() -> None:
    assert_rejected(registry(dataset(layer="project")), "belongs in the project overlay")
    assert_rejected(registry(dataset()), "an overlay entry is `layer: project`", **OVERLAY)


@case
def registry_overlay_extends_without_curated_metadata() -> None:
    variable = {"name": "ASECWT", "vintage": "2024", "source": "IPUMS CPS ASECWT page",
                "verification": "parsed"}
    extension = {"id": "cps", "layer": "project", "verification": "parsed",
                 "variables": [variable], "docs": []}
    assert_accepted(registry(extension), **OVERLAY)
    assert_rejected(registry(dict(extension, pitfalls=[])), "may add only variables", **OVERLAY)
    unknown = dict(extension, id="not_in_template")
    assert_rejected(registry(unknown), "missing required keys: name", **OVERLAY)


@case
def registry_overlay_checked_from_project_root() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "data/docs").mkdir(parents=True)
        (root / "data/docs/cps_2024.md").write_text("# CPS 2024\n", encoding="utf-8", newline="\n")
        good = ("version: 2\nlast_updated: 2026-09-29\ndatasets:\n"
                "  - id: cps\n    layer: project\n    verification: parsed\n"
                "    docs: [data/docs/cps_2024.md]\n")
        (root / vdr.PROJECT_OVERLAY).write_text(good, encoding="utf-8", newline="\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            ok = vdr.main(["--project-root", tmp])
            (root / vdr.PROJECT_OVERLAY).write_text(good.replace("cps_2024.md", "missing.md"),
                                                    encoding="utf-8", newline="\n")
            bad = vdr.main(["--project-root", tmp])
        expect(ok == 0, f"a valid overlay failed:\n{out.getvalue()}")
        expect(bad == 1, "an overlay doc path that does not exist was accepted")


@case
def registry_rejects_unsigned_verified() -> None:
    assert_rejected(registry(dataset(verification="verified")), "`verified` requires `sources`")
    partial = {k: v for k, v in SIGNATURE.items() if k != "verified_by"}
    assert_rejected(registry(dataset(verification="verified", **partial)),
                    "`verified` requires `sources`")


@case
def registry_shipped_entries_unsigned_are_unverified() -> None:
    doc = vdr.load_registry(REPO / "Infrastructure/references/datasets/registry.yaml")
    unsigned = [d["id"] for d in doc["datasets"]
                if d.get("verification") == "verified" and not d.get("verified_by")]
    expect(not unsigned, f"unsigned entries marked verified: {unsigned}")


def shipped_datasets() -> dict[str, dict[str, Any]]:
    doc = vdr.load_registry(REPO / "Infrastructure/references/datasets/registry.yaml")
    return {d["id"]: d for d in doc["datasets"]}


@case
def registry_f30_corrections_hold() -> None:
    """Census F30: placeholders out, public-use names and variance guidance corrected."""
    ds = shipped_datasets()
    names = {i: set(d.get("known_variables", [])) for i, d in ds.items()}
    for placeholder in ("implession", "imputation", "WGT_P"):
        expect(placeholder not in names["scf"], f"SCF still lists {placeholder!r}")
    expect(not any(" " in n for n in names["psid"] | names["nlsy"]),
           "PSID or NLSY still lists a descriptive placeholder as a variable name")
    asec_household = next(w for w in ds["cps"]["weights"] if w["context"] == "ASEC supplement (household)")
    expect(asec_household.get("source_name") == "HSUP_WGT", "ASEC household weight is not HSUP_WGT")
    acs_pitfall = next(p for p in ds["acs"]["pitfalls"] if p["id"] == "acs-no-replicate-weights")
    expect("svydesign" not in acs_pitfall["what_to_check"], "ACS still accepts a svydesign declaration")
    expect("STRATA and CLUSTER" in acs_pitfall["what_to_check"],
           "ACS no longer accepts a design declared with the IPUMS STRATA and CLUSTER variables")
    for ds_id, name in (("acs", "PWGTP37"), ("acs", "REPWT12"), ("scf", "WT1B500"), ("scf", "MM17")):
        expect(any(fnmatch.fnmatchcase(name.lower(), k.lower()) for k in names[ds_id]),
               f"{ds_id} known_variables miss the replicate name {name}")
    expect(not {"WGT", "Y1"} & set(ds["scf"]["identification"]["signal_variables"]),
           "SCF signals include a generic name (WGT or Y1)")
    scf_pitfalls = {p["id"] for p in ds["scf"]["pitfalls"]}
    expect({"scf-pooled-weight-scaling", "scf-no-replicate-weights"} <= scf_pitfalls,
           "SCF lacks the implicate-pooling or replicate-weight pitfall")


@case
def registry_rejects_placeholder_known_variable() -> None:
    assert_rejected(registry(dataset(known_variables=["DEMOWT", "ER prefix variables"])),
                    "is not a variable name")


@case
def registry_signals_are_distinctive_known_names() -> None:
    ident = dict(GOOD_DATASET["identification"], signal_variables=["DEMOWT", "employment"])
    assert_rejected(registry(dataset(identification=ident,
                                     known_variables=["DEMOWT", "employment"])),
                    "too generic to identify a dataset")
    ident = dict(GOOD_DATASET["identification"], signal_variables=["DEMOWT", "WGT"])
    assert_rejected(registry(dataset(identification=ident, known_variables=["DEMOWT", "WGT"])),
                    "too generic to identify a dataset")
    ident = dict(GOOD_DATASET["identification"], signal_variables=["DEMOWT", "OTHERWT"])
    assert_rejected(registry(dataset(identification=ident)), "is not in `known_variables`")


@case
def registry_rejects_retired_keys() -> None:
    ident = dict(GOOD_DATASET["identification"], variable_names=["DEMOWT"])
    assert_rejected(registry(dataset(identification=ident)), "`identification.variable_names` is retired")
    weights = [{"context": "Person-level", "census_name": "DEMOWT"}]
    assert_rejected(registry(dataset(weights=weights)), "unknown keys census_name")


@case
def registry_rejects_unknown_verification() -> None:
    assert_rejected(registry(dataset(verification="checked")), "`verification` must be one of")


@case
def registry_signature_only_on_verified() -> None:
    assert_rejected(registry(dataset(verified_by="A. Reviewer", verified_on="2026-09-29")),
                    "a signature belongs only on a `verified` entry")


@case
def registry_rejects_bad_source() -> None:
    assert_rejected(registry(dataset(sources=[{"title": "Codebook", "url": "ftp://x"}])),
                    "`url` must start with")
    assert_rejected(registry(dataset(sources=[{"url": "https://example.gov"}])),
                    "`title` must be a non-empty string")
    assert_rejected(registry(dataset(verification="verified", sources=SIGNATURE["sources"],
                                     verified_by="A. Reviewer", verified_on="29/09/2026")),
                    "`verified_on` must be an ISO date")


@case
def registry_rejects_variable_without_vintage() -> None:
    bad = dataset(variables=[{"name": "DEMOWT", "source": "Demo codebook"}])
    assert_rejected(registry(bad), "`vintage` is required")
    good = dataset(variables=[{"name": "DEMOWT", "source": "Demo codebook",
                               "vintage": "[unverified: release year not stated]"}])
    assert_accepted(registry(good))


# --------------------------------------------------------------------------- literature catalog
TODAY = dt.date(2026, 9, 29)
GOOD_ENTRY: dict[str, Any] = {
    "id": "2015-solon-what-are-we-weighting-for",
    "title": "What Are We Weighting For?",
    "authors": ["Solon, Gary", "Haider, Steven J.", "Wooldridge, Jeffrey M."],
    "year": 2015,
    "type": "paper",
    "topic_tags": ["methods", "survey-weights"],
    "path": "paper.pdf",
    "source_url": "https://example.org/paper",
    "doi": "10.3368/jhr.50.2.301",
    "added_on": "2026-09-01",
    "status": "parsed",
    "relevance_note": "When to weight regressions on survey data.",
}


def catalog_errors(*entries: dict[str, Any]) -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "paper.pdf").write_bytes(b"%PDF-1.4\n")
        doc = {"version": 2, "last_updated": "2026-09-29", "entries": list(entries)}
        errors, _, _ = vlc.validate_catalog(doc, Path(tmp), TODAY)
    return errors


def entry(**changes: Any) -> dict[str, Any]:
    e = copy.deepcopy(GOOD_ENTRY)
    for key, value in changes.items():
        if value is None:
            e.pop(key, None)
        else:
            e[key] = value
    return e


def assert_catalog_rejects(bad: dict[str, Any], fragment: str) -> None:
    errors = catalog_errors(bad)
    expect(any(fragment in e for e in errors),
           f"expected a catalog error containing {fragment!r}; got {errors or 'no errors'}")


@case
def catalog_shipped_file_passes() -> None:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        status = vlc.main([])
    expect(status == 0, f"the shipped catalog fails validation:\n{out.getvalue()}")


@case
def catalog_accepts_the_documented_schema() -> None:
    expect(catalog_errors(GOOD_ENTRY) == [], f"good entry rejected: {catalog_errors(GOOD_ENTRY)}")
    signed = entry(status="verified", last_verified_on="2026-09-20", doi=None)
    signed["source_url"] = None  # null is allowed when no URL exists
    expect(catalog_errors(signed) == [], f"verified entry rejected: {catalog_errors(signed)}")


@case
def catalog_requires_authors_and_year() -> None:
    assert_catalog_rejects(entry(authors=None), "missing required keys: authors")
    assert_catalog_rejects(entry(authors=[]), "`authors` must be a non-empty list")
    assert_catalog_rejects(entry(year="2015"), "`year` must be a four-digit publication year")


@case
def catalog_rejects_bad_doi_and_dates() -> None:
    assert_catalog_rejects(entry(doi="https://doi.org/10.3368/jhr.50.2.301"), "`doi` must be a bare DOI")
    assert_catalog_rejects(entry(last_verified_on="2027-01-01"), "`last_verified_on` is in the future")
    assert_catalog_rejects(entry(status="verified"), "a `verified` entry records `last_verified_on`")


@case
def catalog_rejects_retired_readme_fields() -> None:
    legacy = entry(tags=["methods"], added="2026-09-01")
    assert_catalog_rejects(legacy, "`tags` is retired; use `topic_tags`")
    assert_catalog_rejects(legacy, "`added` is retired; use `added_on`")
    assert_catalog_rejects(entry(extra_field="x"), "unknown keys extra_field")


@case
def catalog_paths_resolve_from_the_repository_root() -> None:
    assert_catalog_rejects(entry(path="papers/missing.pdf"), "`path` does not exist")
    assert_catalog_rejects(entry(path="/abs/paper.pdf"), "must be repository-relative")


@case
def staleness_reads_last_verified_on() -> None:
    fresh = entry(added_on="2020-01-01", last_verified_on="2026-09-01")
    stale = entry(id="old", added_on="2020-01-01", last_verified_on="2025-01-01")
    never = entry(id="never", added_on="2025-01-01")
    archived = entry(id="gone", added_on="2020-01-01", status="archived")
    warnings, _, checked = ccs.find_stale([fresh, stale, never, archived], TODAY, 180)
    expect(checked == 3, f"expected 3 checked entries, got {checked}")
    expect(len(warnings) == 2, f"expected 2 stale entries, got {warnings}")
    expect("last_verified_on=2025-01-01" in warnings[0] and "added_on=2025-01-01" in warnings[1],
           f"staleness did not date from the right field: {warnings}")


# --------------------------------------------------------------------------- driver
def main() -> int:
    failures = 0
    for fn in CASES:
        try:
            fn()
        except Exception:  # noqa: BLE001 - report every failing case
            failures += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc(limit=3)
            continue
        print(f"PASS {fn.__name__}")
    print(f"{len(CASES)} cases, {failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
