# EIG Style System

Shared style-system assets for producing EIG-consistent writing, figures, tables, and Datawrapper outputs.

## What lives here

- Canonical visual tokens: `tokens/eig-style-tokens.v1.json`
- Theme helpers:
  - Python: `themes/python/`
  - R: `themes/r/`
  - Stata: `themes/stata/`
- Datawrapper compliance checks: `scripts/compliance/`
- Font install/check utilities: `scripts/fonts/`
- Source style guides: `sources/`
- Examples: `examples/`
- Editorial and figure style docs: `docs/eig-*.md`
- Canonical skill bodies: `skills/`

## Quickstart (from repo root)

1. Install style Python dependencies:
```bash
python3 -m pip install -r Infrastructure/style/requirements.txt
```

2. Sync language token files:
```bash
python3 Infrastructure/style/scripts/sync_tokens.py --write
```

3. Install fonts and validate:
```bash
python3 Infrastructure/style/scripts/fonts/check-fonts.py --allow-fallback
```

## Datawrapper compliance

- Manifest check:
```bash
python3 Infrastructure/style/scripts/compliance/check_datawrapper_manifest.py <manifest_path>
```

- Legacy metadata check:
```bash
python3 Infrastructure/style/scripts/compliance/check_legacy_metadata.py <metadata_json_path>
```

## AI integration

- Canonical style agents, workflows, rules, and templates are under `Infrastructure/`.
- `make brain-sync` generates Claude runtime files, Codex native wrappers/configuration, and repo-local skills.
- Invokable dedicated style skills are in `.claude/skills/` (Claude) and `.agents/skills/` (Codex).

## Primary docs index

- `Infrastructure/style/docs/README.md`
