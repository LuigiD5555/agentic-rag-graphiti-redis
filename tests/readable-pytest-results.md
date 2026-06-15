# Readable pytest run (March 9, 2026)

- **Command:** `podman exec f4b7e043e2c4 /bin/sh -c 'cd /app && readable pytest'`
- **Location:** `/app` inside container `f4b7e043e2c4`
- **Duration:** ~27.2 seconds
- **Summary:** 115 tests collected (115 passed, 0 failed, 0 skipped); 78 tests deselected by default selection criteria.
- **Warning:** `tests/test_pptx_conversion.py::test_pptx_conversion` returned `False`, triggering a `PytestReturnNotNoneWarning` (switch to `assert` to avoid returning a value).

Readable output (truncated) shows every decorated test with intent/steps/criteria metadata; the full stdout is captured in the command log if you need more details.
