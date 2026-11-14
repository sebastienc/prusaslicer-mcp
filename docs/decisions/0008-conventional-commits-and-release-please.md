---
status: accepted
date: 2026-11-14
decision-makers: Sebastien Coutu
---

# Conventional Commits, enforced by commitlint, drive releases with Release Please

## Context and Problem Statement

The project had no releases, no version history beyond the number in `pyproject.toml`, and free-form commit
subjects ("imperative, at most 72 characters"). We want releases and a changelog without hand-editing versions.
How should versions, tags and the changelog be produced?

## Decision Drivers

* No manual version bumps or changelog writing.
* The release process must be reviewable (a pull request), not a side effect of a push.
* Nothing may be published to a package index without being asked (`.claude/rules/workflow.md`).
* `uv sync --locked` must keep working after a release.

## Considered Options

* Keep free-form commits and release by hand
* Conventional Commits, commitlint in CI, Release Please
* Conventional Commits with semantic-release or python-semantic-release

## Decision Outcome

Chosen option: "Conventional Commits, commitlint in CI, Release Please", because it turns the commit history into
versions and a changelog while keeping the release itself a pull request a person merges.

* **Commits** follow [Conventional Commits](https://www.conventionalcommits.org/): `type(scope): lower-case subject`,
  header at most 72 characters (`commitlint.config.mjs`, extending `@commitlint/config-conventional`). The
  `Co-Authored-By` trailer stays.
* **commitlint** runs in CI (`wagoid/commitlint-github-action`) on every push to `main` and every pull request.
* **Release Please** (`googleapis/release-please-action`, manifest mode, release type `python`) keeps a release pull
  request open. Merging it creates the tag, the GitHub release and `CHANGELOG.md`, and bumps the version in
  `pyproject.toml` **and `uv.lock`** (an `extra-files` entry), because a stale lockfile would fail `uv sync --locked`.
* **Before 1.0** a `feat` bumps the minor version, a `fix` the patch, and a breaking change also the minor
  (`bump-minor-pre-major`).
* `bootstrap-sha` marks the last commit that predates the convention, so the older free-form history is ignored.
* **No publishing.** Release Please creates a GitHub release only; nothing goes to PyPI.

### Consequences

* Good, because versions and the changelog come from the history and cannot drift from it.
* Good, because a bad commit message fails a check before it reaches `main`.
* Bad, because every commit message must now be conventional, including ones made with the help of tools, and a
  subject cannot start with a capital letter.
* Bad, because pull requests opened with the default `GITHUB_TOKEN` do not trigger other workflows, so the release
  pull request gets no CI until a `RELEASE_PLEASE_TOKEN` secret (a personal access token) is added. The repository
  setting "Allow GitHub Actions to create and approve pull requests" must also be on.
* Bad, because the `uv.lock` entry depends on how Release Please's TOML parser represents values. Its JSONPath has
  to compare `@.name.value`, not `@.name` (found by running the library's own updater on the real lockfile; a plain
  `@.name` silently matches nothing). Check the first release pull request's diff touches exactly one line of `uv.lock`.

### Confirmation

The `commitlint` job in `.github/workflows/ci.yml`; the `release-please` workflow; the first release pull request.

## Pros and Cons of the Options

### Free-form commits, manual releases

* Good, because there is nothing to learn or maintain.
* Bad, because versions, tags and the changelog depend on someone remembering them.

### Conventional Commits, commitlint, Release Please

* Good, because it is declarative, reviewable, and needs no Node toolchain in the project itself.
* Bad, because of the constraints above.

### semantic-release / python-semantic-release

* Good, because it releases without a pull request.
* Bad, because every merge can publish, which conflicts with "do not publish without being asked", and it is harder
  to review before it happens.

## More Information

Related: [ADR 0009](0009-quality-gate-toolchain.md) (CI), `.claude/rules/workflow.md` (commit rules).
