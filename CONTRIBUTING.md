# Contributing

Thanks for helping. Bug reports, model files that slice badly, and pull requests are all welcome.

## Reporting a problem

Open an issue and include: the PrusaSlicer version (this project targets **2.9.x**), your operating system, what you
asked for, and what you got. For a slicing problem, the tool call and the `warnings` it returned are the most useful
thing. If the model itself is the problem and you can share it, attach it; if it is not yours to share, say so and
describe it (size, format, where it came from). Do not paste anything private: profile names are fine, but check
paths and any API tokens first.

Report a security problem privately, as described in [SECURITY.md](SECURITY.md).

## Setting up

You need Python 3.12+, [uv](https://docs.astral.sh/uv/), and, for the integration tests, PrusaSlicer 2.9.x.

```bash
git clone https://github.com/sebastienc/prusaslicer-mcp && cd prusaslicer-mcp
uv sync
cp .env.example .env          # only if PrusaSlicer is not found automatically
uv run poe check              # lint, format, types, unit tests: what CI runs, minus integration tests
uv run poe test-integration   # needs a real PrusaSlicer; skips itself when there is none
```

`uv run poe` lists every task. The unit tests need no PrusaSlicer: its command line is faked.

## Making a change

- **Tests first.** Write the failing test, then the code. `uv run poe check` must pass.
- **Branch and pull request.** Work on a branch (`feat/short-name`, `fix/short-name`) and open a pull request to
  `main`. The single required check is `ci`.
- **Conventional Commits.** `feat: add x`, `fix: handle y`; lower-case subject, header at most 72 characters. CI
  rejects anything else, and [Release Please](https://github.com/googleapis/release-please) builds releases and the
  changelog from them, so please do not edit `CHANGELOG.md` or the version by hand.
- **Docs move with the code.** A new or changed tool updates the tool table in `README.md` and
  `docs/architecture/README.md`. A choice that is hard to reverse gets an ADR in `docs/decisions/`
  (copy `adr-template.md`).
- Never print to stdout from the server: it is the MCP transport. Log to stderr.

Conventions in more detail are in `.claude/rules/`; they are written for Claude Code but read fine as a style guide.

## Releases

Maintainers only. Merging the release pull request that Release Please keeps open tags the release and publishes it
to PyPI ([ADR 0020](docs/decisions/0020-open-source-and-publish-to-pypi.md)). Publishing uses PyPI trusted
publishing, so no token is stored. To set it up once, register a *pending publisher* on PyPI for owner
`sebastienc`, repository `prusaslicer-mcp`, workflow `release-please.yml`, environment `pypi`, and create a `pypi`
environment in the repository settings.
