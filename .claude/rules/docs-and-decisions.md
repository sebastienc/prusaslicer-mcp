---
description: When and how to record decisions and keep docs current
---

# Documentation and decisions

- Docs are in **English**.
- Record significant decisions as **MADR 4.0** ADRs in `docs/decisions/`. File name `NNNN-short-title-in-kebab-case.md`, numbered sequentially, never renumbered. Copy `docs/decisions/adr-template.md`.
- Write an ADR when a choice is hard to reverse or someone would later ask "why did we do it this way?": picking/replacing a dependency, the integration approach, a protocol or data-format choice, a security trade-off, dropping a feature.
- ADRs are **append-only history**. To change a decision, add a new ADR and set the old one's status to `superseded by ADR-NNNN`. Do not rewrite an accepted ADR's reasoning (fixing typos and links is fine).
- Add every new ADR to the index in `docs/decisions/README.md`.
- `docs/architecture/README.md` describes how the system works **now**. Update it in the same change whenever modules, tools, data flow, configuration, or known quirks change. If it disagrees with the code, the doc is a bug.
- `ROADMAP.md` lists planned work. When an item ships, move it to **Done**; when plans change, edit it. It is direction, not commitment, so keep it short and honest.
- Keep `README.md` (user-facing setup/usage) and `.env.example` consistent with any new configuration or tool.
