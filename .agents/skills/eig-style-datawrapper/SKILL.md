---
name: eig-style-datawrapper
description: >-
  Checks a Datawrapper chart pipeline against EIG governance (token colors, palette mode, publish manifest, legacy metadata) with the vendored validators, and reports what fails. Use when an R pipeline publishes or updates Datawrapper charts, or when setting up Datawrapper compliance CI in a downstream repository.
---

# EIG Style Datawrapper Compliance

Check that a Datawrapper pipeline sends only token colors and records an auditable manifest for
each published chart.

Done when the manifest validator (and, for `palette_mode=legacy`, the metadata validator) has
run on every manifest in scope, and the reply lists each failure with its fix, or states that
all passed.

## Sources

1. `Infrastructure/style/docs/datawrapper-integration.md`: the contract, including its
   Downstream Adoption section.
2. `Infrastructure/style/docs/datawrapper-api-notes.md`: measured API behavior.
3. `Infrastructure/style/docs/eig-legacy-palette-policy.md` and
   `Infrastructure/style/docs/legacy-metadata.template.json`: only for legacy palettes.

## Workflow

1. Confirm the pipeline takes its colors from `Infrastructure/style/tokens/eig-style-tokens.v1.json`.
   Before relying on a `visualize` setting, check the known-behavior tables in
   `Infrastructure/style/docs/datawrapper-api-notes.md` §4.1: the API accepts many keys the
   export ignores. For an unlisted key, probe it on a scratch chart if the session is
   interactive and the owner approves; otherwise report the key as unverified.
2. Validate each publish manifest. The validator owns the required fields, so read its error
   output for anything missing:
   - `python3 Infrastructure/style/scripts/compliance/check_datawrapper_manifest.py <manifest_path>`
3. If `palette_mode=legacy`, validate the metadata sidecar:
   - `python3 Infrastructure/style/scripts/compliance/check_legacy_metadata.py <metadata_json_path>`
4. For downstream CI, start from
   `Infrastructure/style/docs/ci/datawrapper-compliance.workflow.template.yml`.
