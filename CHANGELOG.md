# Changelog

## [0.3.1](https://github.com/sebastienc/prusaslicer-mcp/compare/prusaslicer-mcp-v0.3.0...prusaslicer-mcp-v0.3.1) (2026-11-15)


### Bug Fixes

* draw G2/G3 arcs in preview_gcode ([77b27c4](https://github.com/sebastienc/prusaslicer-mcp/commit/77b27c4a816225d390af67aedca3e7d28e0a7556))

## [0.3.0](https://github.com/sebastienc/prusaslicer-mcp/compare/prusaslicer-mcp-v0.2.0...prusaslicer-mcp-v0.3.0) (2026-11-15)


### Features

* draw the bed in model previews ([22c09e0](https://github.com/sebastienc/prusaslicer-mcp/commit/22c09e0cf8a9aa676f1b662d2f8f7d2222d61e86))
* measure real support when suggesting orientations ([aee76ed](https://github.com/sebastienc/prusaslicer-mcp/commit/aee76edf10eb4a7c03458ad07e38e77638bdefe9))

## [0.2.0](https://github.com/sebastienc/prusaslicer-mcp/compare/prusaslicer-mcp-v0.1.1...prusaslicer-mcp-v0.2.0) (2026-11-15)


### Features

* add a finder and capper for holes in meshes ([5c22cc1](https://github.com/sebastienc/prusaslicer-mcp/commit/5c22cc1f4cdc1f0f099e2e8cf429bb7fdfadb5b0))
* add a preview_gcode tool for layers and printed silhouettes ([1d20cfa](https://github.com/sebastienc/prusaslicer-mcp/commit/1d20cfa636ae09527b4599ce4645fe13bb325c25))
* add a preview_model tool that draws a model as a PNG ([ad913f4](https://github.com/sebastienc/prusaslicer-mcp/commit/ad913f4f90aafa67bdb27726a551d337f49aafcb))
* add rotation, scaling, split and copies to slice_model ([6ef462e](https://github.com/sebastienc/prusaslicer-mcp/commit/6ef462e2c483481628d67233892ae9230d403d14))
* add suggest_orientation to rank ways to stand a model ([6d63b9c](https://github.com/sebastienc/prusaslicer-mcp/commit/6d63b9c52b8daed81070ecc46dbd3843addf26c1))
* cap flat holes in inspect_model and slice_model ([22dd107](https://github.com/sebastienc/prusaslicer-mcp/commit/22dd107516f8fa22f9eff5993a19a35924950351))
* centre plain 3MF files on the bed automatically ([37cd0db](https://github.com/sebastienc/prusaslicer-mcp/commit/37cd0db7d5d8bf2dd37f87fe5c6e6d9dcafa3095))
* preview a model with rotate, scale and close_holes ([7669670](https://github.com/sebastienc/prusaslicer-mcp/commit/7669670c22e7ef8c74b273c02d5610c97db4c5b6))
* read STEP files through PrusaSlicer ([2c44eab](https://github.com/sebastienc/prusaslicer-mcp/commit/2c44eab7c52a0922f9571e47bb2b48b5fa7f3520))
* say close orientation scores are ties and hint at the tool ([65cb162](https://github.com/sebastienc/prusaslicer-mcp/commit/65cb162876f6cd330925c44e8b3fce2c099abf0f))
* say how to fix a slice that PrusaSlicer refuses ([d825305](https://github.com/sebastienc/prusaslicer-mcp/commit/d825305f4666b792a230e4e01c17be96b398dfdb))
* score orientations in the dogfood sweep ([9c59289](https://github.com/sebastienc/prusaslicer-mcp/commit/9c592893bd123f162d38d83bdd492a4ea165612f))
* warn when a slice prints nothing over part of the model's height ([6dd486d](https://github.com/sebastienc/prusaslicer-mcp/commit/6dd486db521c6c6155e5e4ea383f787255314933))


### Bug Fixes

* close a hole with a flat base instead of a bumpy one ([b11bddc](https://github.com/sebastienc/prusaslicer-mcp/commit/b11bddc3994059ea6696dc0054f08d2f96ec1f02))
* never report a refused slice as a success using an old file ([248a872](https://github.com/sebastienc/prusaslicer-mcp/commit/248a8726972671d6210e1aa12ae8805dba0e8bb6))
* return the whole PrusaSlicer warning, not just its first line ([4ecbb79](https://github.com/sebastienc/prusaslicer-mcp/commit/4ecbb7955dde5684f445b0787d91a700ea326e39))
* suggest rotating a model before repairing it for missing layers ([6e4602b](https://github.com/sebastienc/prusaslicer-mcp/commit/6e4602bd7ac1f32291118a3ab7057d54db47a508))

## [0.1.1](https://github.com/sebastienc/prusaslicer-mcp/compare/prusaslicer-mcp-v0.1.0...prusaslicer-mcp-v0.1.1) (2026-11-14)


### Documentation

* record the commit convention and the quality gates ([3df38ab](https://github.com/sebastienc/prusaslicer-mcp/commit/3df38ab118abac9400753d6e8d7f440b56f2c95f))
