# Datawrapper Integration for R Pipelines

## Purpose
The governance contract for Datawrapper charts that R pipelines publish: which colors they may use, which palette mode, what each run records, and how CI enforces it. How the Datawrapper API itself behaves is in `Infrastructure/style/docs/datawrapper-api-notes.md`.

## Canonical Inputs

1. Tokens: `Infrastructure/style/tokens/eig-style-tokens.v1.json` (values listed in `Infrastructure/style/docs/_generated/tokens.md`).
2. Figure rules: `Infrastructure/style/docs/eig-figure-style.md`.
3. Legacy palette policy: `Infrastructure/style/docs/eig-legacy-palette-policy.md`.
4. API behavior: `Infrastructure/style/docs/datawrapper-api-notes.md`.
5. Validators: `Infrastructure/style/scripts/compliance/check_datawrapper_manifest.py` and `Infrastructure/style/scripts/compliance/check_legacy_metadata.py`.

## Required Integration Contract

### 1) Token loading and color selection
- Load Datawrapper colors from token IDs, not hardcoded hex values, because the manifest validator rejects any color that is not a token (§5).
- Preferred source is the JSON token file above; generated R tokens are acceptable only when they were synced from the same repo state.
- Persist `token_source_path` and token `meta.version` in publish manifests, and list the colors sent in `colors_sent`.

Example (token-derived color map, in the token file's series order):

```r
eig_load_datawrapper_colors <- function(
  token_json_path = "Infrastructure/style/tokens/eig-style-tokens.v1.json"
) {
  if (!requireNamespace("jsonlite", quietly = TRUE)) {
    stop("Package 'jsonlite' is required.", call. = FALSE)
  }
  token_doc <- jsonlite::read_json(token_json_path, simplifyVector = TRUE)
  brand_hex <- stats::setNames(token_doc$colors$brand$hex, token_doc$colors$brand$id)

  list(
    token_version = token_doc$meta$version,
    discrete = unname(brand_hex[token_doc$colors$discrete_order$token_ids])
  )
}
```

### 2) Palette policy gate (2022 primary by default)
- Set `palette_mode = "primary_2022"` for all new outputs unless a legacy exception is explicitly valid.
- Legacy semantic palettes are allowed only under `Infrastructure/style/docs/eig-legacy-palette-policy.md`.
- Never mix legacy semantic colors with 2022 categorical colors in the same legend without documented rationale.

### 3) Legacy metadata and validation
If `palette_mode = "legacy"`, metadata is mandatory:

1. `legacy_palette_used: true`
2. `legacy_set_id`
3. `legacy_palette_justification`
4. `approver`
5. `approval_date` (`YYYY-MM-DD`)

Template: `Infrastructure/style/docs/legacy-metadata.template.json`. Validate each sidecar:

```bash
python3 Infrastructure/style/scripts/compliance/check_legacy_metadata.py "<metadata_json_path>"
```

### 4) Datawrapper API behavior
The API guardrails are §4 of `Infrastructure/style/docs/datawrapper-api-notes.md`.

### 4.1) Known API behavior
The measured behavior tables (merge semantics, data orientation, keys that work, keys the export ignores, export geometry) are §4.1 of `Infrastructure/style/docs/datawrapper-api-notes.md`.

### 5) Chart identity and auditable manifests
- Publish manifests are mandatory for all Datawrapper R pipelines.
- Persist `figure_key -> chart_id` mapping so reruns update existing charts rather than creating replacements.
- Emit one publish manifest per run with at least:
  - `run_timestamp_utc`
  - `figure_key`
  - `chart_id`
  - `chart_url`
  - `rows_uploaded`
  - `palette_mode`
  - `token_source_path`
  - `token_version`
  - `legacy_metadata_path` (empty when primary palette is used)
- Also record `colors_sent`: every hex value the run sent to Datawrapper (`custom-colors`, `lines[].color`, and fills). The field is optional for the validator, but without it the "no net-new hex" rule goes unchecked.
- Pipelines that do not emit this required manifest schema are non-compliant with EIG style-system governance.

The validator enforces the schema. Besides field presence and format, it fails a row whose `token_version` differs from the token file's `meta.version` (read when it runs, so a token release needs no validator change), and a row whose `colors_sent` holds a color that is not a token, or a legacy token color when `palette_mode` is not `legacy`.

### 5.1) Required CI enforcement
- CI must fail if any Datawrapper publish manifest is missing required fields or contains invalid values.
- Required CI command (per manifest):

```bash
python3 Infrastructure/style/scripts/compliance/check_datawrapper_manifest.py "<manifest_path>"
```
- Reference workflow template to copy into downstream repositories: `Infrastructure/style/docs/ci/datawrapper-compliance.workflow.template.yml`.
- Default downstream workflow location/name (recommended standard): `.github/workflows/datawrapper-compliance.yml`.
- Exception rule: if a downstream repo cannot use the default path/name, it must document the alternate workflow path in that repo's README or CONTRIBUTING guide.

### 6) Applying token colors to Datawrapper line charts
Use token-derived colors when updating chart visualization settings. Do not set a numeric `width`: the export ignores it (`Infrastructure/style/docs/datawrapper-api-notes.md` §4.1).

```r
apply_eig_line_colors <- function(chart_id, series_names, series_colors) {
  line_config <- Map(
    f = function(label, color_hex) list(name = label, color = color_hex),
    label = series_names,
    color_hex = series_colors
  )
  DatawRappr::dw_edit_chart(
    chart_id = chart_id,
    visualize = list(lines = line_config)
  )
}
```

## Downstream Adoption

A repository created from this template has the validators and the token file at the paths above. Any other repository vendors `Infrastructure/style/scripts/compliance/` and `Infrastructure/style/tokens/` with the same layout, because the manifest validator finds the token file from its own location (or takes `--tokens <path>`).

1. Copy the workflow template to `.github/workflows/datawrapper-compliance.yml`.
2. Set `MANIFEST_GLOB` and `LEGACY_METADATA_GLOB` to the repository's manifest and sidecar paths.
3. Make the publish pipeline emit the §5 manifest fields, including `colors_sent`.
4. Load Datawrapper colors from the token file (§1).
5. Default to the 2022 palette and apply the legacy exception policy (§2).
6. If a legacy palette is used, write the metadata sidecar and validate it in CI (§3).
7. Confirm CI fails on a validator error, for example by committing a manifest with a stale `token_version` on a test branch.

## Pre-Publish Checklist (Required)
1. Tokens loaded from canonical source path.
2. `palette_mode` recorded for each chart.
3. Legacy exception justification and metadata captured (if applicable).
4. Legacy metadata validator passes (if applicable).
5. `figure_key -> chart_id` config updated and committed where required.
6. Publish manifest written with token and governance fields, and `colors_sent`.
7. Every visualize key the chart relies on is listed as working in `Infrastructure/style/docs/datawrapper-api-notes.md` §4.1 or was probed on a real export.
8. Manifest validator passes in CI: `python3 Infrastructure/style/scripts/compliance/check_datawrapper_manifest.py <manifest_path>`.

## Related Docs
- Theme quickstarts: [themes/README.md](../themes/README.md)
- API behavior: [datawrapper-api-notes.md](datawrapper-api-notes.md)
