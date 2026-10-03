"""Shared local-app kit for the code war room and the review board.

Both tools serve a local app, save YAML records atomically, resolve a project root, lint
before every write, and test themselves the same way. The kit holds that common layer once:

- `yamlio`: the timestamp-free loader, flow markers, key reordering, the dumper, and the
  atomic, mode-keeping save.
- `filelock`: the advisory lock held around load, mutate, lint, and save.
- `projroot`: project-root resolution and the project-id check.
- `server`: the loopback server and the request handler base (origin, CSP, body cap).
- `lint`: the finding and result types.
- `testkit`: the network guard, the fixture digest, assertions, and an HTTP client.

Anything that knows ledger, board, or manifest semantics stays with its tool: schemas,
lint rules, hashing, status, rendering, and segmentation. Callers put the scripts
directory on `sys.path` and import `localapp.<module>`. Tested by
`Infrastructure/scripts/test_localapp.py`.

Dependencies: Python 3.11+ and PyYAML.
"""
