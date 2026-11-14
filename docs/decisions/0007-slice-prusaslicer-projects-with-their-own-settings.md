---
status: accepted
date: 2026-11-14
decision-makers: Sebastien Coutu
---

# Slice PrusaSlicer projects with their own settings

## Context and Problem Statement

`slice_model` always passed `--printer-profile`, `--print-profile` and `--material-profile`. A 3MF saved from
PrusaSlicer is a *project*: it embeds the full configuration, including changes made on top of the profiles
(supports, brim, infill, seam position, ...). We found, slicing a real project from the user's library, that
passing profile flags makes PrusaSlicer 2.9.7 use the plain profile values and silently ignore everything saved in
the project: the project had supports on, a 5 mm brim and 20% infill, and the server sliced it with none of them
(36 g and 3h 20m against 42 g and 4h 08m). A print that was set up with supports would come out without.
How should `slice_model` treat a project?

## Decision Drivers

* Slicing a project must produce what the user saved, not a silently different print.
* Choosing other profiles for a project (e.g. a different quality) must stay possible.
* The failure mode must be visible to the caller, not silent.
* Keep the tool surface small; avoid a second slicing tool the model might pick wrongly.

## Considered Options

* Keep always passing profiles (status quo), and document the caveat
* Make the three profiles optional: none means "use the project's own settings"
* Add a separate `slice_project` tool

## Decision Outcome

Chosen option: "Make the three profiles optional", because it removes the silent difference with one rule the
model can follow, and keeps one slicing tool.

* Give **all three** profiles, or **none**. Some but not all is refused: a partial set would mix profile values with
  the project's in a way nobody asked for.
* None is allowed only for a PrusaSlicer project (a `.3mf` that embeds `Metadata/Slic3r_PE.config`). For any other
  model, profiles are required, as before.
* The result reports `settings_from` (`"project"` or `"profiles"`), so the caller can see which applied.
* `inspect_model` reports a `project` block for such files: the stored profile names and the settings that shape a
  print (layer height, infill, shells, brim, supports), so a caller can see what a plain-profile slice would drop.
* `center=true` without profiles uses the printer profile stored in the project to find the bed.
* Overrides still apply on top of either source. The server still forces `--binary-gcode=0` (ADR 0005).

### Consequences

* Good, because slicing a saved project reproduces the GUI result (verified: 4h 07m 32s and 41.94 g against the
  GUI's 4h 13m and 41.62 g, the small gap being an older PrusaSlicer version).
* Good, because passing profiles is still the way to deliberately replace a project's settings, and the tool
  descriptions say so.
* Bad, because the same call now means different things depending on whether profiles are present; the
  `settings_from` field and the descriptions are the mitigation.
* Bad, because project detection depends on PrusaSlicer's 3MF layout (`Metadata/Slic3r_PE.config`); an unrecognised
  layout falls back to "not a project" and profiles are required, which fails loudly and safely.

### Confirmation

`tests/test_project.py`, the project cases in `tests/test_slice_model.py` and `tests/test_inspect_model.py`, and the
real-binary tests `test_slice_applies_a_projects_saved_settings_when_no_profiles_are_given` and
`test_slice_with_profiles_ignores_a_projects_saved_settings` in `tests/test_server.py`.

## Pros and Cons of the Options

### Keep always passing profiles, document the caveat

* Good, because it changes nothing.
* Bad, because the default is the surprising behaviour: users and the model expect a saved project to slice as saved.

### Make the three profiles optional

* Good, because it fixes the default and needs no new tool.
* Bad, because one parameter set has two modes (see consequences).

### Add a separate `slice_project` tool

* Good, because each tool does one obvious thing.
* Bad, because the model must choose between two near-identical slicing tools and can pick the lossy one, which is
  the problem we are fixing.

## More Information

Found while dogfooding on `SucculentPot/Pot-MK3S-MMU2S-Single.3mf`. Related: [ADR 0002](0002-wrap-the-prusaslicer-2-9-cli.md),
[ADR 0005](0005-always-slice-to-text-gcode.md). Revisit if PrusaSlicer changes how the CLI combines profile flags
with embedded configuration.
