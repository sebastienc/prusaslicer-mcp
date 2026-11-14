---
status: accepted
date: 2026-11-14
decision-makers: Sebastien Coutu
---

# Always slice to text G-code

## Context and Problem Statement

Recent Prusa printer profiles enable **binary G-code** (`.bgcode`, starts with the magic bytes `GCDE`);
we observed this with the MINI Input Shaper profile on 2.9.7. Print time, filament use and cost are available as
comments in text G-code but are not trivially readable from binary G-code. The server's value
includes returning those statistics. How should slicing output be produced?

## Decision Drivers

* Statistics must be reliably returned to the caller.
* No heavy dependency just to read a footer.
* Slicing must respect the user's chosen profile otherwise.

## Considered Options

* Force text G-code with `--binary-gcode=0`
* Produce binary G-code and decode it
* Honour the profile and return no statistics for binary output

## Decision Outcome

Chosen option: "Force text G-code with `--binary-gcode=0`", because it is a one-flag change that
makes statistics parseable with a few regular expressions, and it was verified against 2.9.7.

### Consequences

* Good, because `parse_gcode_stats` is tiny and dependency-free; it rejects `GCDE` input explicitly.
* Bad, because the produced file is larger and is not the format the printer's profile prefers; the user may need to re-export from the GUI, or convert with Prusa's `bgcode` tool, before printing from storage that expects `.bgcode`.

### Confirmation

`tests/test_gcode.py` (parser and binary rejection) and `tests/test_server.py::test_slice_model`.

## Pros and Cons of the Options

### Force text G-code

* Good, because it is simple and verified.
* Bad, because it deviates from the profile's output format.

### Produce binary G-code and decode it

* Good, because output matches what the printer expects.
* Bad, because it needs a bgcode reader (e.g. wrapping Prusa's `libbgcode` tool or building bindings) and we found no maintained Python library.

### Honour the profile and return no statistics for binary output

* Good, because behaviour is faithful to the profile.
* Bad, because it removes the main feedback loop for Claude on the printers the user actually owns.

## More Information

Revisit if we add a bgcode reader or a `convert_gcode` tool; then binary output could become an option.
