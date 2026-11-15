# Dogfooding sweep

Unit tests use small synthetic models. Real libraries are messier: scans with holes, CAD exports stored off the bed,
projects for printers you do not own, models bigger than the bed. The sweep runs every tool over a folder of real
models and reports what happened, so problems show up before a user meets them.

It is opt-in (it needs PrusaSlicer and a folder of models), it is not part of `poe check` or CI, and it lives in
`scripts/dogfood/`.

## Running it

```bash
uv run poe dogfood run <folder>                  # sweep a folder, then print the report
uv run poe dogfood run <folder> --match pot      # only paths containing "pot" (ignores case)
uv run poe dogfood run <folder> --limit 10       # a quick run over the first ten files
uv run poe dogfood report                        # print the report for the last sweep again
```

Other options: `--out DIR` (default `output/dogfood`, which is git-ignored), `--workers N` (files at once, default 3),
and `--printer-profile`, `--print-profile`, `--material-profile` for non-project models. By default it uses the first
installed printer with its first print profile and filament, so nothing machine-specific is configured anywhere.

Roughly 15 minutes for 130 models with the default workers. Cloud-synced folders may download each file as it is read.

## What it does per file

Four steps, each in its **own process with a timeout**, so a model that hangs or crashes the server cannot stop the
sweep:

1. `inspect_model` against the printer's bed.
2. `preview_model` as a four-view sheet (saved as `model.png`).
3. `suggest_orientation` (without `close_holes`). A PrusaSlicer project is skipped, since the tool refuses projects.
4. `slice_model`, then `preview_gcode` as the side silhouette (saved as `print.png`). A PrusaSlicer project is sliced
   with its own settings (no profiles); anything else with the chosen profiles. The G-code is deleted after use.

Results go to `<out>/results.jsonl`, one row per step, with a numbered folder per file for the pictures.

## Reading the report

The first two lines say how many files were swept and whether anything **crashed or timed out**. Those are bugs in
the server and the only reason the command exits non-zero. Look at them first.

| Section | What to look for |
|---|---|
| steps | The outcome of each step: `ok`, `refused` (a readable error), `timeout`, `crash`. |
| refused slices | Each refusal with its first line. Many are legitimate (a model really is bigger than the bed), but check that the advice in the message is right and the remedy works. |
| warnings | PrusaSlicer's warnings and the layer-gap warning, grouped with the numbers ignored. A new kind of warning is worth reading in full. |
| time per step | Median, 90th percentile and maximum seconds. A step far slower than the rest points at a performance problem. |
| inspect_model findings | How many files are not watertight, have several parts, exceed the bed, are 3MF files stored off the bed, or are projects. |
| suggest_orientation findings | How many plain models were scored, how many are better stood another way than as stored, how many rest on no real base as stored, and how many have no stable orientation at all. The projects are counted as skipped. |
| printed height | Files whose printed height is not about the model's height (outside 0.9 to 1.1). That means missing or extra layers, and a silent bad slice. |
| pictures | The emptiest model sheets and the faintest silhouettes. A blank picture usually means something went wrong; open the file. |

## When to run it

After a change to slicing, previewing, inspection or G-code parsing, and before a release. Run it on a library you did
not write the tests against.

## What the first sweep found

The first run, over 132 files (76 3MF, 53 STL, 3 OBJ), had no crashes or timeouts and sliced 128 of them. It found:

- A refused slice that was reported as a success, returning an older slice's statistics (PrusaSlicer exits 0 for some
  refusals and an old file was sitting at the output path). Fixed.
- A refusal hint that told the caller to centre a model that was simply bigger than the bed. Fixed, with advice that
  was verified on the real files.
- 13 of 15 plain 3MF files needing a retry with centring, which is now automatic ([ADR 0013](decisions/0013-centre-plain-3mf-files-automatically.md)).
- Both the "empty first layer" and the wipe-tower refusals lacking any advice. Fixed.
