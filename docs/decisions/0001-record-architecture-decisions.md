---
status: accepted
date: 2026-11-14
decision-makers: Sebastien Coutu
---

# Record architecture decisions

## Context and Problem Statement

This project is built collaboratively with an AI assistant across many sessions. The reasoning behind
choices (why the CLI, why Python, what we rejected) is easily lost between sessions and is not
recoverable from code or git history alone. How do we keep that reasoning available to future us?

## Considered Options

* Record decisions as MADR files in the repository
* Rely on commit messages and the README
* Keep notes outside the repository

## Decision Outcome

Chosen option: "Record decisions as MADR files in the repository", because they are versioned with the
code, are read by both humans and the assistant, and MADR is a small, well-known format.

### Consequences

* Good, because the "why" survives context loss and is reviewable in pull requests.
* Bad, because it is a small recurring writing cost; `.claude/rules/docs-and-decisions.md` says when it is worth paying.

## More Information

Template: [`adr-template.md`](adr-template.md). MADR: <https://adr.github.io/madr/>.
