# Third-party code with no license

`u3d-rhadobe-mesh.js` was copied unchanged from
[tommyjarvis-a/pdf-3d-extractor](https://github.com/tommyjarvis-a/pdf-3d-extractor), commit
`18db1c81d32b69b7c8b0f2ea34f8f662d552a142`, on 2026-11-06.

| | |
|---|---|
| SHA-256 | `466c461f0d47e65b3636f5ed4cf0886855bbd63d077bf5c5d17de9413e2d388b` |
| Purpose | Decodes Adobe's private U3D mesh ("RHAdobeMeshResource"), which the ECMA-363 standard doesn't define |
| Used by | `../rhadobe.py`, which runs it in PySide6's JavaScript engine |

**This file has no license.** The project states none, so its author keeps all rights. It was copied in for internal
use only, at Wagner Machine Co.'s own decision and risk, knowing this. Don't distribute SolidSmurfs with this file in it
unless the author grants a license.

One thing to raise if the author is ever asked: the project's `prc-brep.js` says in its header "Part of pdf-3d-extractor (MIT)",
but the project has no license file, and this file doesn't say the same. That isn't enough to rely on.

Removing it is safe. `rhadobe.py` then reports these meshes as unreadable, as before.

This is the only file of that project in SolidSmurfs. Its PRC exact-geometry code was tried and not used: run here it took
up to 14 minutes on a model and ran past 7 on most CAD files, and it needs uv curves on edges, which at least 98% of the edges
in the sample files don't have. `../../prc/brep.py` and `brepmesh.py` are our own, and contain none of its code.

The decoder says itself that it doesn't decode the U3D arithmetic-coded encodings (8 and 9); files that use them stay
unreadable. It was written from Adobe's Acrobat SDK 8.1 document "U3D Supported Elements", chapter 2 and appendix A.
