---
load: paths
paths:
  - "code/**"
  - "output/**"
  - "Infrastructure/style/**"
---

# Style Datawrapper Rules

Binding rules for Datawrapper publishing compliance under EIG style governance.

## Canonical Sources

- `Infrastructure/style/docs/datawrapper-integration.md` (including its Downstream Adoption section)
- `Infrastructure/style/docs/datawrapper-api-notes.md`
- `Infrastructure/style/docs/eig-legacy-palette-policy.md`
- `Infrastructure/style/scripts/compliance/check_datawrapper_manifest.py`
- `Infrastructure/style/scripts/compliance/check_legacy_metadata.py`

## Manifest Requirements

Every published chart has a publish manifest. `check_datawrapper_manifest.py` owns the required
fields and their formats, and `datawrapper-integration.md` §5 explains each one; neither list is
repeated here, so the two cannot drift.

## API Behavior

Before relying on any Datawrapper `visualize` setting, check the known-behavior tables in
`Infrastructure/style/docs/datawrapper-api-notes.md` §4.1. The API stores many keys the
export ignores, and edits merge rather than replace; probe any unlisted key on a scratch
chart and record the result there.

## Validation Commands

- `python3 Infrastructure/style/scripts/compliance/check_datawrapper_manifest.py <manifest_path>`
- `python3 Infrastructure/style/scripts/compliance/check_legacy_metadata.py <metadata_json_path>`

If `palette_mode=legacy`, metadata sidecar fields are mandatory per policy.
