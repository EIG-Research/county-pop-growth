# EIG Legacy Palette Policy

## Objective
Define exactly when 2020 legacy semantic palettes are allowed versus disallowed.

## Default Rule
All new charts and tables use 2022 primary tokens from:
`tokens/eig-style-tokens.v1.json`

## Allowed Use Cases for Legacy Palettes
Legacy semantic palettes are allowed only if at least one condition is true:
1. The output is part of a recurring EIG series that has historical color semantics and comparability requirements.
2. A stakeholder contract/SOW explicitly requires continuity with prior 2020-style publications.
3. A model/dashboard compares new outputs directly against archived outputs that already use the legacy mapping.

## Disallowed Use Cases
Legacy semantic palettes are disallowed when:
1. The deliverable is a net-new publication/product line with no comparability requirement.
2. Colors are chosen by personal preference rather than semantic continuity.
3. Legacy colors are mixed with primary palette categories in the same legend without documented rationale.

## Required Metadata When Legacy Is Used
Every figure/table that uses legacy palettes must include:
1. `legacy_palette_used: true`
2. `legacy_set_id: <set_name>` (for example `dci_quintile`)
3. `legacy_palette_justification: <single sentence>`
4. `approver: <name>`
5. `approval_date: <YYYY-MM-DD>`

## Decision Tree
1. Is this output part of a historically color-semantic EIG series?
2. If `No`, use 2022 primary palette.
3. If `Yes`, is comparability explicitly required by brief or contract?
4. If `No`, use 2022 primary palette.
5. If `Yes`, use the corresponding legacy semantic set and record required metadata.

## Enforcement Guidance
- CI or pre-publish checks should fail when legacy palette colors are detected without required metadata fields.
- Theme helpers should expose legacy palettes behind explicit flags, not as default palettes.

## Datawrapper Pipeline Enforcement
- Datawrapper R publishers must implement this policy via:
`docs/datawrapper-integration.md`
- Repo link: [docs/datawrapper-integration.md](datawrapper-integration.md)
- For any Datawrapper chart using legacy semantic colors, store a metadata sidecar with all required fields from this policy.
- Validate each legacy metadata sidecar before publish with:
`python3 scripts/compliance/check_legacy_metadata.py <metadata_json_path>`
