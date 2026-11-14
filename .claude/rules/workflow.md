---
description: Repo hygiene, secrets, configuration and commits
---

# Workflow

- **Secrets and machine config never get committed.** `.env` is git-ignored; `.env.example` is the committed template. Do not put paths, tokens, or credentials in source, tests, or docs.
- Adding an environment variable means: read it in `config.py`, document it in `.env.example` (commented, with default), and add it to the configuration table in `README.md`.
- Local environment is managed by **direnv** (`.envrc` loads `.env`). Do not run `direnv allow` on the user's behalf; it is the user's trust decision.
- The repository is **private**. Pushing is fine on request; do not change visibility or publish packages without being asked.
- Commits: imperative subject line (<= 72 chars), body explains *why*. One logical change per commit. Include the attribution trailer the session specifies.
- Do not commit generated output (`output/`, `*.gcode`, `*.bgcode`, `.venv/`).
- Third-party reference code (e.g. the cloned `Noosbai/PrusaMCP`) lives **outside** this repo. Reading it is fine; copy only with attribution and license compatibility (it is MIT).
- Do not run untrusted third-party code from reference clones.
