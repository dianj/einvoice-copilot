# Security

This is a portfolio demo that runs locally (the app and LM Studio on 127.0.0.1). It has no production deployment and
no supported release line; the `main` branch is the only version.

## Reporting a problem

Please open a GitHub issue, or, for anything that should not be public, use GitHub's private vulnerability report
("Security" tab → "Report a vulnerability").

## Dependencies

- `requirements.txt` lists the direct dependencies with version ranges. `requirements.lock` pins every package, direct
  and indirect, with its SHA-256 hashes. CI and the Docker image install from the lock with `--require-hashes`, so a
  changed or swapped file on the index fails the install.
- Regenerate the lock after changing `requirements.txt`:

  ```
  uv pip compile requirements.txt --universal --python-version 3.12 --generate-hashes -o requirements.lock
  ```

  `tests/test_supply_chain.py` fails while a requirement is missing from the lock or pinned outside its range.
- Dependabot opens weekly pull requests for Python packages and GitHub Actions.
- CI runs `pip-audit` on the lock and fails on any known vulnerability that is not listed below.

## Known advisories that do not apply

| Advisory | Package | Why it does not apply here |
|---|---|---|
| PYSEC-2026-311 (CVE-2026-45829, GHSA-f4j7-r4q5-qw2c) | chromadb 1.5.9 | Code injection through Chroma's **HTTP server** (a request with a model repository and `trust_remote_code`). The app uses Chroma embedded in its own process (`PersistentClient`, `copilot/kb/store.py`); no Chroma server runs and no Chroma endpoint is exposed. Embeddings come from the app's own ONNX embedder, not from a model named in a request. |
| PYSEC-2026-3814 (CVE-2026-45833, GHSA-36p7-vc44-83pf) | chromadb 1.5.9 | The same, for authenticated requests to the server's `/api/v2/tenants/...` endpoints. No server, no endpoints. |
| PYSEC-2026-3815 (CVE-2026-45831, GHSA-xph7-9rjv-w5fr) | chromadb 1.5.9 | The server's `SimpleRBACAuthorizationProvider` does not check the tenant a permission applies to. No server, no Chroma authentication or tenants in use. |
| PYSEC-2026-3813 (CVE-2026-45830, GHSA-2wm9-hf6c-p5cr) | chromadb 1.5.9 | Missing tenant checks for authenticated users of the server. No server, one local collection. |

No fixed version exists yet for these four. Review them again when chromadb publishes one, or before running Chroma
as a server.

## What the app does about its own risks

The threat model and the controls (XML hardening, citations checked in code, approval before any ticket, threads bound
to the browser that created them, size limits before a body is read) are described in the README and in
`docs/DECISIONS.md`.
