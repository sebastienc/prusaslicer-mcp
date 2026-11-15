# Security policy

## Reporting a vulnerability

Please report it privately through GitHub: **Security → Report a vulnerability** on this repository. Do not open a
public issue for it. You should get an answer within a week. This is a hobby-scale project, so there is no bounty
and no guaranteed fix time, but a real problem will be taken seriously and credited if you wish.

## Supported versions

Only the latest release on PyPI is supported.

## What is in scope

The server runs on your machine with your permissions and is driven by an MCP client, which may be driven by a
language model reading untrusted text. These are the things that matter:

- Running PrusaSlicer is the only thing it executes, always as an argument list and never through a shell.
- A tool should not read or write outside the paths a user or the configured output folder implies. A way to make
  it overwrite arbitrary files, run something else, or leak file contents is a vulnerability.
- Model files (STL, OBJ, 3MF, STEP) and G-code are parsed. A crafted file that crashes or hangs the server is worth
  reporting; one that runs code is a vulnerability.

Problems in PrusaSlicer itself belong to [Prusa Research](https://github.com/prusa3d/PrusaSlicer/security).
