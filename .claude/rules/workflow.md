---
description: Repo hygiene, secrets, configuration and commits
---

# Workflow

- **Secrets and machine config never get committed.** `.env` is git-ignored; `.env.example` is the committed template. Do not put paths, tokens, or credentials in source, tests, or docs.
- Adding an environment variable means: read it in `config.py`, document it in `.env.example` (commented, with default), and add it to the configuration table in `README.md`.
- Local environment is managed by **direnv** (`.envrc` loads `.env`). Do not run `direnv allow` on the user's behalf; it is the user's trust decision.
- The repository is **public** and published to PyPI (ADR 0020). Pushing is fine on request. A release is made only by merging the Release Please pull request, which publishes; never upload a package by hand, and do not change the repository's visibility or settings without being asked.
- **Changes land through pull requests.** Work on a branch (`type/short-name`, e.g. `ci/quality-gates`), open a PR to `main`, and merge it once CI is green. Do not push to `main` directly. Merge with a merge commit or rebase, not a squash, so each Conventional Commit survives for Release Please; a PR title is also written as a Conventional Commit.
- Commits are **Conventional Commits** (ADR 0008): `type(optional scope): lower-case subject`, header <= 72 chars, body explains *why*. Types: `feat` (new behaviour, minor release), `fix` (bug fix, patch release), `perf`, `revert`; these are the only ones that appear in release notes or can trigger a release. `docs`, `test`, `refactor`, `build`, `ci`, `chore` and `style` are hidden from releases (`changelog-sections` in `release-please-config.json`), so a history of only those opens no release pull request. Mark a breaking change with `!` (`feat!:`) and a `BREAKING CHANGE:` footer. One logical change per commit. Include the attribution trailer the session specifies.
- CI (`.github/workflows/ci.yml`) must be green; the single required status check is the `ci` job, which gathers all the others, so add any new job to its `needs`: `uv run poe check` locally covers lint, format, types and unit tests; integration tests run in CI on macOS.
- **GitHub Actions are pinned to a full commit SHA** with the version in a trailing comment (`uses: owner/repo@<sha> # v1.2.3`), never to a tag: a tag can be moved. Dependabot (`.github/dependabot.yml`) updates them weekly in one grouped pull request. The repository setting that requires SHA pinning is on, so an unpinned `uses:` fails the run.
- Do not edit `CHANGELOG.md`, the version in `pyproject.toml`, or `.release-please-manifest.json` by hand; Release Please owns them.
- Do not commit generated output (`output/`, `*.gcode`, `*.bgcode`, `.venv/`).
- Third-party reference code (e.g. the cloned `Noosbai/PrusaMCP`) lives **outside** this repo. Reading it is fine; copy only with attribution and license compatibility (it is MIT).
- Do not run untrusted third-party code from reference clones.
