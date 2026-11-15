---
status: accepted
date: 2026-11-14
decision-makers: Sebastien Coutu
---

# Measure support by slicing, on request

## Context and Problem Statement

[ADR 0018](0018-suggest-orientations-from-geometry.md) ranks orientations by overhang area, a geometric guess at how
much support a print will need. On the statue it picked the cheapest orientation but ordered the other two wrongly,
and it said nothing about print time. How much should the ranking be trusted, and can the real numbers be had?

## Decision Drivers

* Replace a guess with the real support filament, filament and time where it is worth the wait.
* Do not slow the default call: scoring takes under a second, slicing takes seconds to minutes.
* Never hide an orientation PrusaSlicer would refuse.
* Check the geometric score on more than one model before relying on it.

## Considered Options

* Keep the geometric score only
* Improve the geometric estimate (support volume under each overhang)
* Slice each option with supports and read the result, only when profiles are given
* Always slice

## Decision Outcome

Chosen option: "slice each option with supports, only when profiles are given". `suggest_orientation` takes the
three profile names (all or none, as `slice_model` does). With them, each option, at most six, is sliced once
through `slice_model` with `support_material=1` and `support_material_auto=1`, with its own `rotate_x` and
`rotate_y` and with `close_holes` if asked, into a temporary folder. The new `gcode.filament_by_feature` reads the
filament of each `;TYPE:` (arcs included, retractions and wipes excluded, start G-code left out) and
`support_g = filament_used_g * support / total`, where "support" is `Support material` plus
`Support material interface`. On the statue this equals the earlier "with supports minus without" figures exactly
(15.0, 21.6, 18.0 g) and its total equals PrusaSlicer's own filament length to the millimetre.

Each option gets `measured`: `support_g`, `filament_g`, `estimated_time` and `estimated_time_seconds`, or `refused`
with PrusaSlicer's first line when it would not slice (and then no numbers). The options are re-ranked: refused
last, then stable before unstable, then the least measured support, then the shortest print, with equal
measurements keeping their geometric order. `geometry_rank` keeps the geometric position.

### What the measurements showed

One slice with supports per candidate (top four plus as stored), on five of the user's models:

| Model | Predicted best | Measured best | Note |
|---|---|---|---|
| Statue (capped) | rank 1 (2,163 mm2) | rank 1 (15.0 g) | the others were swapped: 3,797 mm2 cost 21.6 g, 4,114 mm2 cost 18.0 g |
| `grimpeux-scan-1` (capped) | rank 1 (2 mm2) | rank 1 (0.0 g) | the next three measured 9.1, 9.3 and 12.5 g |
| `ElbowV0` | rank 1 (2,700 mm2) | **rank 3** | as stored cost 12.7 g and 44.1 g in all, against 22.2 g and 53.6 g for rank 1 |
| `my-hinge` | rank 1 (50 mm2) | rank 1 (0.06 g) | ranks 2 to 4 (107 to 118 mm2) measured 0.40, 0.40 and 0.19 g: the near-tie reordered |
| `2020 Extrusion Mount` | rank 1 (0 mm2) | rank 1 (0.0 g) | ranks 1 and 2 tied at 0 |

So the geometric winner was the measured winner on 4 of 5 models. The miss, `ElbowV0`, is the instructive one: its
as-stored orientation rests on 76 mm2 (flagged unstable) yet cost 9.5 g less filament overall. It stays ranked below
the stable options on purpose (a thin footprint can lift off the bed), but the numbers are now in front of whoever
decides. Orderings among near-equal scores did flip (the hinge, the statue), which supports the 10% tie rule in
ADR 0018. Print time varied as much as support: 7 h 46 m to 9 h 55 m for the statue, 29 min to 1 h 11 m for the
hinge, 3 h 34 m to 6 h 40 m for the scan, which is why time is reported and used as the tie-break.

### Consequences

* Good, because the real support filament, total filament and time replace a guess, and a refusal is visible.
* Good, because the default call is unchanged and fast; measuring is opt-in.
* Bad, because it is slow: one slice per option, typically 10 to 30 s each on these models, so up to about three
  minutes at the limit of six.
* Bad, because supports are forced on with automatic placement and the profile's own threshold, which may not be
  what the user will print with.
* Bad, because the stable-first rule still overrides a cheaper measured option, as with `ElbowV0`. The 5% line is a
  judgement.
* Bad, because the evidence is five models; the geometric score and the 10% rule should be rechecked on more.

### Confirmation

Unit tests with a faked `--export-gcode` whose support share depends on the rotation: the numbers, the profiles, the
forced supports and the rotation carried to each slice, support interface layers, re-ranking (including measurement
overturning the geometric order), stable before unstable, refusals ranked last, the time tie-break, no slicing
without profiles, partial profiles and counts over six refused before any slice, `close_holes` giving the capped copy
and no files left behind. Unit tests for the G-code reader (relative and absolute extrusion, arcs, retractions,
wipes, resets, start G-code). A real-binary test that a cone on its apex measures no support when stood on its base.

## Pros and Cons of the Options

### Keep the geometric score only

* Good, because it is instant.
* Bad, because it was wrong about the second and third statue orientations and gave no time.

### Improve the geometric estimate

* Good, because it would stay instant.
* Bad, because the column-volume estimate tried in ADR 0018 chose the wrong winner on the statue.

### Slice each option, on request

* Good, because of the decision outcome above.
* Bad, because of the consequences above.

### Always slice

* Good, because every answer would be measured.
* Bad, because every call would take minutes and need profiles.

## More Information

The per-feature reader is also what a future per-feature time or filament analysis would use (see the roadmap's
richer G-code analysis).
