---
status: accepted
date: 2026-11-14
decision-makers: Sebastien Coutu
---

# Render previews ourselves with numpy and Pillow

## Context and Problem Statement

The server returns numbers (size, time, filament, layers) but the model cannot *see* anything. That cost us when
slicing a scanned statue: the statistics looked healthy while the print was broken, and it took reading G-code to
learn the scan was Y-up and had been sliced lying on its side. A picture of the mesh shows that at a glance, and a
picture of what was actually printed shows the empty stretches. How should the server produce images?

## Decision Drivers

* Must work headless: no display, no GPU, no OpenGL, on a developer machine and on a CI runner.
* Fast enough for a tool call, including a 200,000-triangle scan.
* A small dependency footprint; Pillow is acceptable, a plotting library is not.
* Tests must be able to check the pictures deterministically.
* Readable by a model, not only pretty.

## Considered Options

* numpy and Pillow: a software renderer for meshes, and our own G-code parser for toolpaths
* matplotlib
* trimesh's scene renderer or pyrender (OpenGL)
* PrusaSlicer's own thumbnails embedded in the G-code
* No images; text summaries only

## Decision Outcome

Chosen option: "numpy and Pillow". A prototype showed it is fast and the output is readable.

* **Model**: sample points on the surface (area-weighted), project them orthographically, keep the nearest per pixel
  (z-buffer) and shade by the surface normal, two-sided so open meshes still read. About 0.5 s for 206,000 triangles.
* **Sliced G-code**: parse `G1` moves that extrude, using the `;LAYER_CHANGE`, `;Z:` and `;TYPE:` comments PrusaSlicer
  writes. Two pictures: one layer's toolpaths coloured by feature (with the previous layer as a faint ghost), and a
  front and side silhouette of everything printed, which makes empty stretches obvious. About 0.5 s to parse 330,000
  segments.
* **Two read-only tools** return a PNG plus a text caption through the SDK's `Image` helper: `preview_model` and
  `preview_gcode`. Image size is capped (128 to 1024 px, default 640) to bound the cost of reading it.

### Consequences

* Good, because it needs only Pillow, runs anywhere, and is deterministic, so tests assert on pixels.
* Good, because it showed the real cause of a broken slice that statistics and warnings had not.
* Bad, because it is our own renderer: orthographic only, no perspective, no textures, and the shading is simple.
* Bad, because arcs (`G2`/`G3`, when the printer profile enables arc fitting) are not drawn, and only text G-code is
  read (ADR 0005 already forces text).
* Bad, because parsing is plain Python, roughly 2 s per million segments and done twice; a very large G-code is slow.

### Confirmation

Unit tests on synthetic meshes and G-code (silhouette sizes, hole filling, layer selection), stdio tests that a real
client receives `image/png` content, and the real-binary slices used while prototyping.

## Pros and Cons of the Options

### numpy and Pillow

* Good, because of the drivers above.
* Bad, because of the constraints above.

### matplotlib

* Good, because it draws anything.
* Bad, because it is a large dependency, slow for 200,000 triangles, and gives no better picture for this purpose.

### trimesh scene renderer or pyrender

* Good, because it is real 3D rendering.
* Bad, because it needs OpenGL or EGL, which is fragile on headless machines and CI.

### PrusaSlicer's own thumbnails

* Good, because it is exactly PrusaSlicer's look.
* Bad, because it is unreliable headless: a slice with a profile asking for four thumbnail sizes contained none.

### No images

* Good, because it adds nothing.
* Bad, because it leaves the model blind to the problem that motivated this.

## More Information

Related: [ADR 0005](0005-always-slice-to-text-gcode.md), which makes G-code readable here.
