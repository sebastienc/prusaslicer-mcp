---
status: accepted
date: 2026-11-14
decision-makers: Sebastien Coutu
---

# Centre plain 3MF files on the bed automatically

## Context and Problem Statement

A 3MF keeps the coordinates it was saved with. A file exported from CAD (a plain 3MF, with no PrusaSlicer settings
embedded) is usually modelled around the origin, so half of it sits off the bed and PrusaSlicer refuses it with
"All objects are outside of the print volume". `slice_model` had `center` defaulting to false, so the first call on
such a file failed and the caller had to retry with `center=true`. How should `center` default?

## Decision Drivers

* Remove a failed call that is almost always followed by the same fix.
* Do not move a model whose layout was chosen on purpose (a PrusaSlicer project).
* Do not turn a call that used to work into one that fails.
* Make any automatic behaviour visible to the caller.

## Considered Options

* Keep `center` false by default
* Centre everything by default
* Make `center` three-valued: automatic by default, centring plain 3MF files only

## Decision Outcome

Chosen option: "three-valued, automatic by default", because the data points one way. Slicing the 132 models in the
user's library: 15 were plain 3MF files, **13 of them were stored off the bed, and all 13 sliced as soon as they were
centred**. STL and OBJ files never needed it (PrusaSlicer places those itself), and none of the 61 PrusaSlicer
projects needed it, even the 7 that looked off-bed against a 180 mm bed, because their layout was intended.

* `center` is `true`, `false`, or omitted. Omitted means centre a **plain 3MF** (a `.3mf` with no PrusaSlicer
  settings embedded) and leave everything else alone. An explicit `true` or `false` is always honoured.
* In the automatic case centring is best effort: if the printer's bed cannot be looked up, the model is sliced
  without centring, as before. An explicit `center=true` still fails clearly in that case.
* The result reports `centered`, so the caller can see what happened.
* `inspect_model` says a plain 3MF will be centred automatically, and tells the caller of a project to pass
  `center=true`.

### Consequences

* Good, because 13 of the 15 plain 3MF files in the library no longer need a failed call.
* Good, because projects, STL and OBJ keep exactly the behaviour they had.
* Bad, because a plain 3MF that was already positioned correctly now moves to the middle of the bed. Pass
  `center=false` to keep its stored position.
* Bad, because the default now depends on the file type; the `centered` field and the parameter description are the
  mitigation.

### Confirmation

Unit tests for each file type with the default, `true` and `false`, and for the best-effort case; real-binary tests
that a plain 3MF modelled around the origin slices without any `center`, and that `center=false` restores the
refusal.

## Pros and Cons of the Options

### Keep `center` false by default

* Good, because nothing changes.
* Bad, because 13 of 15 plain 3MF files fail their first call.

### Centre everything by default

* Good, because it is simple.
* Bad, because it would move the layout of every project, which is wrong.

### Three-valued, automatic by default

* Good, because it fixes the common case and leaves the others alone.
* Bad, because of the consequences above.

## More Information

Found by slicing the whole library; see [ADR 0007](0007-slice-prusaslicer-projects-with-their-own-settings.md) for
projects and [ADR 0012](0012-transform-with-prusaslicers-own-flags.md) for the other transforms.
