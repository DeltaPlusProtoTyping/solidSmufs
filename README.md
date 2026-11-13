<img src="solidsmufs/web/img/icon-256.png" alt="SolidSmurfs logo" width="96">

# SolidSmurfs

**[Download SolidSmurfs](https://github.com/DeltaPlusProtoTyping/solidSmufs/releases/latest)** for Windows, macOS or
Linux. No Python needed. On Windows, unzip it and double-click `Install SolidSmurfs.cmd`. All versions are on the
[Releases page](https://github.com/DeltaPlusProtoTyping/solidSmufs/releases).

Wagner Machine Co.'s 3D part viewer for Windows. It looks and works like SolidWorks (menus,
CommandManager, FeatureManager tree, PropertyManager, heads-up view toolbar, Measure and Mass
Properties windows), and it opens STEP, IGES, SolidWorks parts, Parasolid and mesh files without
any CAD program installed.

## How it compares

How SolidSmurfs sits next to the other programs a shop uses to look at customer files (November 2026). SolidSmurfs'
times were measured on our PC; the others are typical times, not measured here. Prices are US list prices before tax
and vary by reseller.

| | Cost per seat | Starts in | Opens a file in | Files stay on the PC | Measure 3D | Print hover tips | Runs on |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **SolidSmurfs** | $0 | ≈2.5 s | ≈1–1.5 s (a part seen before: under 0.5 s) | Yes | Yes, with mass properties, holes, stock size | Fits (H/h), metric → inches, French → English, with OCR | Windows, macOS, Linux |
| SOLIDWORKS Standard | ≈$2,820/yr, or ≈$4,000–4,200 + ≈$1,295/yr | 20–60 s | 2–10 s | Yes | Yes (full CAD) | No | Windows |
| eDrawings Viewer | Free | 5–10 s | 2–5 s | Yes | Yes (no mass properties) | No | Windows, macOS |
| DraftSight Premium | ≈$599/yr (Professional ≈$299) | 5–10 s | 1–3 s | Yes | Some (2D CAD first) | No | Windows, macOS, Linux |
| Adobe Acrobat Pro | ≈$240/yr (Reader free) | 2–5 s | 1–3 s | Yes, unless saved to Adobe's cloud | Only in 3D PDFs | No (has OCR) | Windows, macOS |
| FreeCAD | Free | 5–15 s | 2–10 s | Yes | Yes (full CAD) | No | Windows, macOS, Linux |
| Autodesk Viewer | Free (Autodesk account) | a browser tab | ≈1–5 min, uploaded and converted first | **No: every file is uploaded to Autodesk's cloud** | Basic | No | Any browser |

What each one opens (✓ opens, ◐ partly, — no, ? not confirmed):

| File type | SolidSmurfs | SOLIDWORKS | eDrawings | DraftSight | Acrobat | FreeCAD | Autodesk Viewer |
| --- | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| STEP, IGES, BREP | ✓ | ✓ | ✓ | ? | — | ✓ | ✓ |
| SolidWorks parts and assemblies | ✓ | ✓ | ✓ | — | — | — | ✓ |
| SolidWorks drawings | ◐ preview picture | ✓ | ✓ | — | — | — | ? |
| Parasolid | ✓ | ✓ | ✓ | — | — | — | ✓ |
| Inventor, Creo, NX, CATIA | — | ◐ | ◐ Inventor, Solid Edge | — | — | — | ✓ |
| Meshes (STL, OBJ, PLY, 3MF, glTF) | ✓ | ◐ | ◐ STL | — | — | ✓ | ✓ |
| DXF and DWG | ✓ (DWG after a one-time converter set-up) | ✓ | ✓ | ✓ edits | — | ◐ | ✓ |
| PDF prints | ✓ with hover tips, OCR, markup, forms, signing and editing | — | — | ◐ underlay | ✓ with OCR and markup | — | ✓ |
| 3D PDFs (PRC, U3D) | ✓ measurable | — | — | — | ✓ | — | — |
| G-code | ✓ 3D toolpath per tool | — | — | — | — | ◐ CAM workbench | — |
| Plotter files and SVG | ✓ | — | — | ? | — | ◐ SVG | ? |
| eDrawings files | ◐ preview picture | ✓ | ✓ | — | — | — | ? |
| Scans and pictures | ✓ with OCR hover tips | — | — | ◐ | ◐ | — | ✓ |
| Zip files | ✓ | — | — | — | — | — | ✓ |

SOLIDWORKS is still what you need to model and change parts and make drawings; DraftSight for editing DWG. SolidSmurfs
is for looking, measuring and quoting, and it marks up, fills in, signs and edits PDFs (see [Editing PDFs](#editing-pdfs)).
What it doesn't do that Acrobat does: certificate (digital ID) signatures, radio-button and signature fields, OCR saved into the file,
comparing two versions, and editing whole paragraphs that reflow.

## Run it

Double-click the **SolidSmurfs** shortcut on the desktop (drop files on it to open them), or
`SolidSmufs.cmd` in this folder. To put the shortcut back on a desktop:
`powershell -ExecutionPolicy Bypass -File tools\make-shortcut.ps1`. To open a file directly:

```
SolidSmufs.cmd "C:\path\to\part.step"
```

You can also drag files onto the window. Opening another file while the viewer is running adds a
tab to the window that's already open.

**Right-click menu:** right-click any part in Explorer → **Open with SolidSmurfs** (select several to
open them as tabs). Double-click still opens files in SolidWorks or whatever owns them. It's set up
for the current Windows user (no admin); to add it on another PC, or take it out:

```
powershell -ExecutionPolicy Bypass -File tools\register-context-menu.ps1
powershell -ExecutionPolicy Bypass -File tools\register-context-menu.ps1 -Remove
```

## What it opens

| Format | Extensions | How |
| --- | --- | --- |
| STEP (AP203 / AP214 / AP242, parts and assemblies, colors) | `.step` `.stp` | OpenCASCADE (through gmsh) |
| IGES | `.igs` `.iges` | OpenCASCADE; loose surfaces are stitched into solids when they close |
| OpenCASCADE BREP | `.brep` `.brp` | OpenCASCADE |
| SolidWorks part (2001 and newer) | `.sldprt` | own reader: the Parasolid body inside the file, then OpenCASCADE |
| SolidWorks assembly (2015 and newer) | `.sldasm` | own reader: the component list and placements, then each part as above (needs the part files) |
| Parasolid | `.x_t` `.x_b` `.xmt_txt` `.xmt_bin` | own reader, then OpenCASCADE |
| Meshes | `.stl` `.obj` `.ply` `.off` `.3mf` `.glb` `.gltf` | own readers; faces split at sharp creases so flat faces and holes can be picked |
| PDF prints | `.pdf` | MuPDF (PyMuPDF) draws and edits them, PDFium (through Qt) reads their text: pages, find, select, thumbnails, password-protected files; hover tips for fits, inches and French, with Windows OCR |
| 3D PDFs and their models | `.pdf` `.prc` `.u3d` | own PRC and U3D readers (Adobe's private U3D mesh included) |
| DXF and DWG drawings | `.dxf` `.dwg` | own DXF reader: layers, blocks, dimensions, text; DWG through the free ODA File Converter, set up from inside the app |
| Plotter files and SVG | `.plt` `.hpgl` `.hgl` `.svg` | own readers, as drawings with layers |
| G-code | `.nc` `.tap` `.gcode` `.gc` `.ngc` `.cnc` `.eia` `.mpf` `.min` `.ptp` | own reader: the toolpath in 3D, a body per tool, arcs, drilling cycles, cutting time |
| Pictures and scans | `.png` `.jpg` `.bmp` `.gif` `.tif` (multi-page) `.webp` `.tga` | Qt, shown as pages, with OCR hover tips |
| SolidWorks drawings, eDrawings | `.slddrw` `.eprt` `.easm` `.edrw` (and the `x` versions) | the preview picture saved in the file |
| Zip files | `.zip` | pick a file inside; unpacked once, so an assembly finds its parts |

CAD files are measured on the exact geometry. Meshes are measured on their triangles.

**Colors, finishes and materials:** SolidWorks parts and assemblies open in their SolidWorks colors
(read from the part, per body and per face) with a realistic finish: chrome and polished metals
reflect, satin and cast metals are duller, glossy plastics have a clear coat, rubber is matte, and
see-through parts are see-through. The finish comes from the SolidWorks appearance's name ("satin
finish stainless steel", "matte rubber"), or from the material when there's no appearance
("AISI 304" shows as satin stainless steel). The part's material and density (stored in the file)
show in the FeatureManager tree and are used by Mass Properties, Stock Size and the Quote Summary;
an assembly weighs each part with its own material. Turn **RealView Graphics** off (heads-up view
settings, or View → Display) for plain shading. STEP and IGES colors show too; those formats rarely
carry a finish or material, so they keep the plain look until you pick a material.

**SolidWorks assemblies:** an assembly file holds no geometry; it lists its part files and where
each one sits. The viewer finds each part the way SolidWorks does (where it was saved, next to the
assembly, at the same relative place, then anywhere under the assembly's folder), uses the
configuration each component calls for (a LONG and a SHORT pin show as different lengths), and opens
sub-assemblies inside it. Suppressed components are left out (not shown, measured or weighed), and
components hidden in the saved display state open hidden (show them from the tree). Parts it can't find
are listed in a message, and the rest still open; a Pack and Go zip, unzipped, has everything. Not yet:
virtual parts (stored inside the assembly), mates, exploded views, switching display states, and a
few parts whose offset surfaces the translator can't yet hand to OpenCASCADE (two in the Mouse sample).
The first open translates every part, which can take a minute for parts with many fillets; after that
it opens from the cache.

**Configurations:** a SolidWorks part opens in its first configuration, named after the part in the
FeatureManager tree (`pin (LONG)`). Right-click the part name, or open the Configurations folder and
double-click one, to show another.

**Speed:** a file you've opened before shows instantly from a cache in
`%LOCALAPPDATA%\SolidSmufs\cache` (the exact geometry for measuring loads behind it in a second or
two). Each open file runs in its own process, so a file that crashes the geometry kernel only closes
its own tab. Starting the viewer on a cached part takes about 2 seconds; with the viewer already
open, a right-clicked part shows in under half a second (a spare geometry process is kept ready, and
the page's scripts and shaders are cached in `%LOCALAPPDATA%\SolidSmufs\web`). Each launch writes
`[timing]` lines to `%APPDATA%\SolidSmufs\log.txt`.

**Save As STEP** (File menu): saves the open part or assembly as a STEP file for anyone without
SolidWorks, with its colors and part names. An assembly is saved as one STEP assembly of its placed
parts. Meshes can't be saved as STEP.

## The workspace (SolidWorks layout)

- **Title bar:** Wagner logo menu, File / Edit / View / Tools / Window / Help, quick access toolbar,
  command search (`Ctrl+F`).
- **CommandManager** tabs: **View** (open, rebuild, zoom, orientation, normal to, section view,
  display style, hide/show, appearance, scenes, perspective, save picture), **Evaluate** (Measure,
  Mass Properties, Section Properties, Bounding Box, Statistics, Draft Analysis, Zebra Stripes,
  Curvature, Edit Material) and **Tools** (Stock Size, Hole Report, Quote Summary).
- **FeatureManager design tree:** History, Annotations, Solid / Surface / Graphics Bodies, Material,
  Front / Top / Right Plane, Origin, Imported1, or the component tree for assemblies. Hide, show,
  color and select from here; the filter box finds parts in big assemblies.
- **PropertyManager** (OK / Cancel) for Section View, Appearance, Bounding Box and the analyses;
  **DisplayManager** lists every body's appearance.
- **Heads-up view toolbar**, reference triad, optional view cube, **View Selector** cube (`Space`),
  **mouse gestures** (right-drag), **shortcut bar** (`S`), a **context toolbar** beside new
  selections, **Model / 3D Views** tabs for named views.
- **Task pane:** Wagner home page and recent files, **File Explorer** for browsing folders of parts,
  Appearances & Scenes, Custom Properties.
- **Status bar:** with nothing selected, the part's best-fit size (L × W × T), box volume and part
  volume, for sizing stock at a glance; otherwise a quick measurement of the selection, Editing Part / Assembly, and the unit system
  (MMGS, CGS, MKS, IPS) like SolidWorks.

Mouse buttons default to SolidWorks (middle-drag rotate, Ctrl+middle pan, Shift+middle zoom,
left-drag box select, right-drag gestures). As in SolidWorks, the view turns about the model's
center; middle-click a vertex, edge or face to turn about it instead (a straight edge becomes the
axis), and middle-click empty space to go back. Rolling the wheel toward you zooms in. Right-click ›
**Select Other** lists every face under the cursor, to pick one hidden behind another. On a laptop without a middle button, switch to
"Left-drag rotates" in Tools → Options → Mouse. Press `F1` for every shortcut.

## Measuring

- **Measure:** faces, edges, vertices, or any point on a face. One item gives its size; two give the
  distance, normal distance, angle and Delta X / Y / Z, drawn in the graphics area. When one of the
  two is a radius (an arc edge or a hole), a Close / Center / Far toggle for each radius picks its
  close tangent, centerline or far tangent. A radius and two or more other items give the distance
  from the radius to each of them; with two, the difference and how far off center the hole sits.
  Projected On (screen or a plane) and Measurement History as in SolidWorks.
- **Radius of a smooth bend:** click a curved face or edge that has no radius of its own in the file
  (a spline or swept surface, a fillet, a spline or elliptical edge) and it shows its radius, from the
  exact curvature: one Radius when it's constant, otherwise the radius where you clicked and the
  smallest and largest.
- **Threads:** click a tapped hole or a threaded shaft and the Measure box and status bar show its
  size (1/4-20 UNC, M6x1, 1/4-18 NPT), pitch, tap drill and thread length. Modelled threads are read
  off the helix, so the answer is definite; a plain hole (a cylinder at the tap drill or minor
  diameter, as Hole Wizard and cosmetic threads leave it) gets its most likely use and the other
  sizes it could be, unless the SolidWorks part's Hole Wizard says it has tapped holes of a size it fits, which then names it outright. Covers UNC / UNF #0 to 1", ISO metric coarse and common fine, and NPT.
- **Mass Properties:** pick a material (or a density); the report is in SolidWorks' format: mass,
  volume, surface area, center of mass, principal axes and moments, inertia at the center of mass
  and at the origin.
- **Section Properties** of flat faces, **Statistics**.
- **Bounding Box:** best fit (the smallest box, for stock), aligned to the Front / Top / Right planes,
  or aligned to selected faces: pick a flat or round face (or a straight edge) and the box stands on
  it, with length and width fitted as tight as they go; Ctrl+click a second face to set the length
  direction too. Sizes are exact, from the true surfaces.
- **Align Part:** pick a flat or round face (or a straight edge); a triad on it (its facing, the length across it, and the third) has X / Y / Z and Flip buttons on every arrow: set any two and the third follows (a second pick aims the length arrow). The other method chooses which view each pick faces (Top,
  Front, Right, ...); Ctrl+click a second pick to set the turn about it, or let the part's length run
  left to right. The geometry itself turns, exactly, so views, X / Y / Z, the bounding box, Stock Size,
  mass properties and Save As STEP all follow. The orientation is remembered for that file (it reopens turned, with a notice); Reset puts it back as modelled.
- **Stock Size:** smallest block (or one standing on picked faces, as in Bounding Box) or, with **Round bar**, the smallest bar around the part (along the best direction, or along a picked round face, edge or flat face), drawn in the view, with allowance and rounding,
  plus stock weight. **Hole Report:** every hole by diameter, count and depth, with modelled
  thread sizes, and the rest matched to tap drills, minor diameters, clearance holes and drills. **Quote Summary:** all of it in one copyable list.

## Geometric tolerances on hover

With **TP on hover** on (the PDF toolbar; on by default), hovering a feature control frame on a print shows what it
means in plain words, its zone in mm and inches, its datums, what Ⓜ or Ⓛ does, and a difficulty from 1 to 10 for
holding it and for measuring it. True position is the main one; flatness, perpendicularity, profile, runout and the
rest read the same way.

It reads every part of a frame: the 14 symbols, a Ø or spherical SØ zone, the circled modifiers after the tolerance
(Ⓜ Ⓛ Ⓢ, Ⓟ projected, Ⓕ free state, Ⓣ tangent plane, Ⓤ unequally disposed, ST, CF) and the ones on each datum
(A Ⓜ, A Ⓢ). Hole callout symbols explain themselves too: ⌴ counterbore, ⌵ countersink, ↧ depth.

A frame is read from the PDF's own text (the symbols themselves, or a CAD GD&T font's letters) or, on a scan, from
the picture. Windows OCR reads the numbers and datum letters but not the symbols (it gives a circled letter as "@"),
so `solidsmufs/kernel/gdtsee.py` looks at the pixels: the symbol in the frame's first cell and the letter in each
circle are matched by shape against how they're drawn. It only names one when it fits clearly better than the others
and sits in a drawn frame; otherwise the tip says the symbol couldn't be read (a Ø zone with datums is then taken as
position, and said to be a guess). Nothing leaves the computer. The scores are a first guess: they come from the
tables at the top of `solidsmufs/kernel/gdt.py` (the tolerance, then an amount per kind of tolerance and for Ⓜ).

**Part difficulty.** Once the print has been read, the far right of the command bar shows the whole part's difficulty
from 1 to 10, with a gauge; click it for what it's made of. Each geometric tolerance gives points from its two scores
(routine ones give none), some kinds count extra (a tapped hole's position ×1.5), and the points are totalled: 20 points
is a 5/10 part, 40 is 7.5. A part is never easier than its hardest callout less one. The multipliers are with the
other tables at the top of `solidsmufs/kernel/gdt.py`. Only geometric tolerances count so far.

**For a quoting system.** The same answer with no window, as JSON (the score, the points, the print's units, and each
callout with its two scores, multiplier and points):

```
python -m solidsmufs --difficulty print.pdf
SolidSmurfs.exe --difficulty print.pdf --out result.json     (the built app has no console to print to)
```

`--password word` opens a protected PDF and `--no-ocr` reads only the PDF's own text. The exit code is 0, or 2 with
`{"error": "..."}`. From Python: `solidsmufs.difficulty.read("print.pdf")`. The fields are listed at the top of
`solidsmufs/difficulty.py`.

## Ballooning a print and its inspection report

**Balloon** (the PDF toolbar, beside TP on hover) turns the PDF view into **Ballooning mode**, and back. Nothing else
of the app changes. In the mode, the PDF editor's toolbar gives way to the mode's own (Auto Balloon, Add, Sub-balloon,
Edit, Delete, Renumber, Multiply, Report, with Undo, Redo and Save), and the **Bill of Characteristics** is docked under the
pages. **Exit Ballooning** puts the view back as it was; the balloons stay on the print.

**Auto Balloon** reads the print and numbers everything on it there is to inspect: dimensions with their tolerances,
angles, chamfers, threads, surface finishes, feature control frames and the numbered notes. Each gets a red balloon
beside it, its callout is marked on the print (orange, then green once reviewed), and it gets a row in the list.
It asks first what to read, and remembers the answers:

- **Pages:** the current page, all of them, or the ones you name (`1, 3-5`). The balloons on the pages it doesn't read
  stay as they are, and the numbers then run through the sheets in order.
- **Do not balloon Basic / Reference / General Tolerance dimensions:** each left unticked is ballooned. A Reference size
  (in brackets, or with REF or STOCK beside or beneath it) and a Basic one (BSC, or drawn in a box of its own) have no
  limits and say so under Tol Type. A General Tolerance size is one with no tolerance of its own.
- **Surface finish detection**, **Numbered notes**, **Ignore title block.**
- **Flag note detection:** a note's number drawn in a triangle or flag by a feature is ballooned there as "Flag note
  2", with the note's words when the sheet has that numbered note. A number in a box is a basic size, not a flag.
- **Split sub-characteristics:** one callout's several characteristics share a number as 2.1, 2.2: what's written on
  one line (a counterbore's diameter and depth), or stacked right under one another (a size over its feature control
  frame).

- **The Bill of Characteristics:** a row for each balloon: Reviewed, Dim #, Dwg. Zone (the sheet and the border's zone,
  `S1-B4`), Type (Linear, Diameter, Radius, Angular, Thread…), Requirement, Mult, Nominal, Upper and Lower Tol, Lower
  and Upper Limit, Tol Type (General when it comes from the title block, Reference, Basic), Description, Gage and Note.
  - Click a row to find its balloon. The arrow keys move through the list, and Space ticks Reviewed.
  - Double-click a cell (or press Enter) to type into it in place. Enter goes on to the cell below, Tab to the next one
    along, Esc leaves it as it was.
  - The box in the Reviewed heading ticks every row shown. **Show** narrows the list to what's not reviewed, reviewed,
    or still without limits.
  - Right-click a row for Edit, Add sub-balloon, Mark as reviewed and Delete. Drag the list's top edge to resize it.

- **Where a balloon goes:** the nearest spot beside its callout that is clear of text, of other balloons, of the
  drawing's lines (part edges, dimension and leader lines) and of its pictures. On a crowded callout it takes the
  least bad spot, to drag where you want it.
- **Where the limits come from:** the tolerance on the callout (`±.005`, `+.005/-.000`, limits like `.2500-.2505`, a
  tolerance or limits stacked over two lines, `MAX` and `MIN`), or, for a size with none, the title block's table by
  the number of decimals (`.XXX ±.005`), or its one tolerance for every size (`Tolerances: ±.5mm unless noted`). The table read from the print shows above the list as **General tolerance**:
  correct it there and every size that uses it follows. Limits from the title block show in italics.
- **What's left out:** a size only told in a sentence, the zone numbers and letters around the border, a second
  value in square brackets, and what's in the title block.
  A count (`4X`, `3 PLACES`) is one balloon with that quantity (see Multiply).
- **On the print:** drag a balloon to move it; double-click it (or **Edit…**) for all of its details in one dialog.
  A changed nominal, tolerance, limits or count is written into the requirement too (`5.000 ±.005` becomes
  `5.000 ±.010`), in the print's own style, unless the requirement itself is typed.
- **Pages:** the balloons and views go with their pages when pages are moved, and go when their page is deleted. A
  copied page gets no balloons of its own, and nor do pages brought in from another file (another print's balloons
  aren't this one's).
  Delete removes it; **Renumber** closes the gaps. **Add** balloons something by hand: drag a box around a callout and its text is read
  or click a spot for an empty balloon. Everything is undone with Ctrl+Z.
- **Sub-numbers:** one callout with several things to check gets one number and sub-numbers: 2.1, 2.2, 2.3.
  **Sub-balloon** puts a new one under the selected balloon's number, and typing `2.2` as another balloon's Dim #
  moves it to be the second under 2. A plain number takes it out again. Renumber keeps them together.
- **Views:** **Views ▾ → Add view** and drag a box round one of the drawing's views. Its balloons are drawn in its
  color (on the print and in the saved PDF); click its name tag to rename it, change its color, give it a start
  number or delete it. **Renumber ▾** numbers the balloons in list order, by rows (across the sheet), by columns (down
  it) or clockwise round from twelve o'clock; with views, view by view in their order, each from its start number.
- **A new revision:** open the new revision's PDF, then **Auto Balloon ▾ → Carry over from the last revision…** and
  choose the last revision's ballooned PDF. This print is read again, and each characteristic found that the last
  revision had keeps its balloon number, description, gage and note: the same, or changed (its note says what it was,
  and it's left unreviewed). New ones are numbered after the last revision's highest; the numbers of those that are
  gone are left out (Renumber closes the gaps). A summary lists what changed, what's new and what's gone.
- **Results:** the dock's second tab. **+ Add part** adds a column for a part to inspect; double-click its heading
  to give it its serial number, right-click it to delete it. Type each measurement in, or P or F (Pass, Fail) for
  what isn't measured: Enter goes on down the part's column and on to the next part at its foot, Tab along the row,
  and the balloon being measured comes into view on the print. A result inside its limits is green, outside them
  red, and each row says Pass, Fail, or how many parts are still to measure. The parts and their results are kept
  with the balloons in the PDF; **New lot…** takes them out to inspect another lot. Reading the print again with Auto
  Balloon drops the results measured against the balloons it replaces.
  - **Sampling…** says which parts of a lot to inspect: every part, the first and last, the first, middle and last,
    1 in N (and the last), or a percentage spread through the lot. A part is added for each, named by its place in
    the lot (#1, #6, #11...), and the inspection sheet's Inspection Frequency says how they were chosen.
  - **Import…** reads results from a CMM's or a gage's export, or a spreadsheet: CSV, tab or semicolon separated text,
    or an Excel workbook (.xlsx). It guesses which column has the balloon numbers (5, #5, DIM 5, Char 2.1 all name
    balloon 5 or 2.1) and which have the measurements, and shows the file to check that before importing. A column
    for each part, or a row for each measurement with the part's serial number in a column, are both understood; a
    single measured column can go into a part already in the list. Rows naming no balloon here are listed. A gage
    that types into the computer (a USB or foot-switch gage) goes straight into the cell being typed into.
  - From two parts on, each row shows its **Mean**, **Range** and **Cpk** (green from 1.33), with the count, min,
    max, standard deviation and Cp on hover. The first article workbook gets a **Statistics** sheet that works them
    out from the measurements on its Inspection sheet, so it follows what's typed there.
- **Multiply:** a characteristic that applies in several places (`4X`, a count under Mult) is one balloon and one
  row. **Multiply** makes it a row for each place, 3.1 to 3.4, in the list and in the report, so each one is
  inspected; it stays one balloon, and the rows all say the same. **Detach** makes each place a balloon of its own,
  put around the callout to drag to its own feature, with its own description, gage and note. **Reset** puts a
  multiplied one back to one row. Each is for the selected balloon or for all of them.
- **Report…** writes an Excel workbook. It asks for the job first (part number and name, revision, customer, job
  number, inspection frequency, drawing number and revision, P.O. number, organization and supplier code, how many
  parts), which is kept with the balloons in the PDF; the organization and supplier code are remembered on the
  computer for the next job. What the parts measured is written in under each part, named by its serial number, and
  the rest of the part columns are left to fill in. Two layouts:
  - **Inspection sheet**, to print and fill in: the job across the top, then a table of every balloon (number,
    description, gage, nominal, lower and upper limit) with five blank part columns, and the table again for each
    further five parts. A characteristic with no limits shows what the print says across the three number columns. The
    footer lines (a form number, a policy note) are yours, remembered on the computer.
  - **First article**: a row for each balloon with its requirement and limits, a results column for each part and a
    Pass / Fail the workbook works out as results are typed in (type Pass or Fail for what isn't measured: Fail as
    soon as one part fails, Pass once every part's result is in, and "2 of 5" until then), with
    totals at the top; then the AS9102 forms: **Form 1** (part number accountability), filled in from the job's
    details with the rest to tick and sign, **Form 2** (materials, special processes and functional tests), with
    rows to type them into, and **Form 3**, the characteristics with the first part's results.

  The inspection sheet is also saved as a **PDF**, ready to print, beside the workbook under the same name, with the
  results measured so far (outside its limits, in red): the balloon numbers in red, the headings in blue, in Calibri and Cambria, a table kept whole on its page, on as many pages as the
  list takes.

  In both, a result typed in outside its limits turns red. A balloon's **Description** ("Overall Length") and **Gage**
  ("Calipers") are typed in the list; without a description the sheet says Dimension, Diameter, Radius and so on.
- **Saved in the PDF:** the balloons are real marks in the file, so the saved print shows and prints them in any PDF
  reader, and the list comes back with them when the file is opened here again.

It's a first pass by rules, to check against the print, not a finished inspection plan. What it doesn't do yet: read an ISO fit class into limits, read a CMM program's own report format (export it as
CSV or Excel), balloon a 3D model's PMI, let a report be laid out by hand, or balloon a picture (print it to a PDF first). A
scanned print is read by OCR, which misreads more: a degree sign as a 0, for one.

## Printing

**Print** (Ctrl+P, File menu or the quick access toolbar) prints what's on show. A PDF or a picture prints its pages,
all of them or a range, each fitted to the paper, with the paper turned to suit each page. A model prints as it's shown, on
white, without the view cube or triad. No Acrobat needed.

From a script or the command line, with no window (each run is a process of its own that ends once the job is with
Windows' spooler; exit code 0 when everything printed, 1 when anything didn't, 2 for a mistake in the command):

```
SolidSmurfs.exe --print drawing.pdf part.step --printer "\\server\KONICA MINOLTA" --copies 2 --pages 1-4,9
SolidSmurfs.exe --print-to out.pdf drawing.pdf        (to a PDF file instead of a printer)
SolidSmurfs.exe /t drawing.pdf "\\server\KONICA MINOLTA"    (Acrobat's form, so scripts written for it work)
SolidSmurfs.exe /p /h drawing.pdf                     (the default printer, no dialog)
SolidSmurfs.exe /p drawing.pdf                        (the print dialog first)
```

`SolidSmurfs.exe` is a window program, so cmd and PowerShell don't wait for it (Acrobat's the same). To wait for the job
and get the exit code, use `start /wait "" SolidSmurfs.exe ...` in cmd, or
`(Start-Process SolidSmurfs.exe -ArgumentList ... -Wait -PassThru).ExitCode` in PowerShell. When it ends, the job is in
the printer's queue.

Without `--printer` it uses the default printer. A printer is named in full (as `Get-Printer` lists it), never by part
of its name. `--pages` takes `1-4,9`, `7-` (to the end) or `-2` (the last two). Several files go out as one job.

## Editing PDFs

A PDF's pages have a second toolbar with Acrobat's tool sets. Everything is saved as standard PDF, so Acrobat and other
readers show it, and comments stay comments they can change.

- **Comment:** sticky notes, text boxes, highlight, underline, strikethrough and squiggly (drag across the words),
  freehand drawing, rectangles, ovals, revision clouds, lines, arrows and stamps (Approved, Draft, Confidential and the
  rest, or any picture). Pick a color, line width, opacity and text size for the next one or the selected one.
  **Select** a comment to drag it, size it by its handles, nudge it with the arrow keys, double-click to change its
  words, or Delete it. **Comments** lists them all by page, with author and date, to edit, reply to or delete.
- **Fill & Sign:** type into a form's fields (text, check boxes, lists). Where a form has no fields, add text, check
  marks, crosses, dots and today's date anywhere. **Sign** and **Initials**: draw or type them once (they're kept on
  this computer) and click or drag where they go. **Flatten** makes comments, signatures and filled-in fields part of
  the pages, so nobody can change them. A print's balloons stay balloons.
- **Prepare Form:** make any PDF fillable. **Detect fields** finds the blanks (rules to write on, boxes, a table's
  empty cells, squares to tick, runs of underscores; a scanned form's lines are found in its picture) and puts a field
  on each, named from the words beside it. The fields show as boxes: drag one to move it, its corner to size it,
  double-click for its name, tip, text size, choices, required or read-only; Delete removes it. Text fields, boxes of
  several lines, check boxes and drop-down lists can be drawn by hand too. The saved file fills in anywhere,
  Acrobat included.
- **Edit:** click a line of the page's own text to change it (the old words are taken out of the file and the new ones
  set in the nearest standard font), add new words, and select a picture to move, size or delete it, or add one.
- **Pages:** in the side bar, Ctrl+click or Shift+click to pick pages and drag them to reorder; right-click or use the
  toolbar to turn, delete, duplicate, insert blank pages, insert other PDFs or pictures (combining files), replace,
  extract to a new PDF, split into several PDFs, and crop (drag the part to keep) or uncrop.
- **Redact:** mark words, areas, or everything the Find box finds, then **Apply**: what's under the marks is taken out
  of the file for good (words, the covered parts of pictures and drawing, and form fields with what's filled into
  them: click a field with Mark text to mark all of it). **Fill** chooses what's left behind: black, or white for
  blank paper. **Strike through** puts a single line through words that should stay readable (a superseded
  note, an old revision); **Apply** draws it into the page too. **Remove hidden info** takes out the
  document's details, attachments, scripts and hidden text.

It works as Acrobat does, with some of the rough edges taken off:

- **Select** (V) does what's under the pointer: drag across words to select them, click a comment to grab it, drag bare
  paper to pan. Hold **Space** to pan with any tool. Right-click selected words or a comment for what can be done to it.
- Selected words get a small bar: copy, highlight, underline, strike through, highlight with a note, mark for redaction.
  A selected comment gets one too: quick colors, its words, duplicate, delete.
- A comment being dragged carries its picture along, and stops at the page's edge. A line has a handle on each end.
  A signature, stamp or picture about to be placed shows under the pointer at the size a click gives it.
- Comments copy and paste (Ctrl+C, Ctrl+V onto the page in view) and duplicate (Ctrl+D). Arrow keys nudge.
- One key picks a comment tool: V select, N note, T text box, H highlight, U underline, K strikethrough, D draw,
  B rectangle, E oval, C cloud, L line, A arrow. A tool that places one thing hands back to Select with the new
  comment selected; double-click its button to keep it on. The status bar says what the tool in hand does.
- Text boxes grow to fit what's typed into them.

Ctrl+Z and Ctrl+Y undo and redo anything, page changes too. **Save** (Ctrl+S, File menu) writes over the PDF (a
password-protected PDF keeps its password); **Save As** (Ctrl+Shift+S) saves a copy somewhere else, which then becomes the
open document. A tab with unsaved changes shows a dot, and closing it or the window asks first. A file dropped in from a
browser or opened from a zip is a copy, so it's saved with Save As.

## SpaceMouse

A 3Dconnexion SpaceMouse works without any extra software beyond its usual driver: the app reads the
device directly (Windows HID). The part follows the cap: slide to pan, pull toward you to zoom in, tilt,
twist and roll to turn it about its center (the entity you middle-clicked, or when zoomed in past the center, the part at the middle of the view; a dot shows where). System Options has a
part / camera switch and a reverse for each axis. Set `SOLIDSMURFS_SPACEMOUSE=off` to leave it to
3DxWare.

## How it's built

- `solidsmufs/app.py`: the Qt window (PySide6 WebEngine), file dialogs, dropped files, single instance.
- `solidsmufs/server.py`: local HTTP API on 127.0.0.1 with a per-session token.
- `solidsmufs/documents.py`: one worker process per open file.
- `solidsmufs/kernel/pdfdoc.py` and `pdfedit.py`: PDF pages and every PDF edit (PyMuPDF), with undo;
  `web/js/pdfview.js` and `pdfedit.js`: the page view and its tools.
- `solidsmufs/kernel/`: loading (`cad.py` via gmsh/OpenCASCADE, `meshio.py`), the cache and tools
  (`worker.py`), measuring (`measure.py`), thread sizes (`threads.py`), mass properties and
  bounding boxes (`massprops.py`).
- `solidsmufs/formats/parasolid/`: SolidWorks / Parasolid reader (Parasolid → STEP).
- `solidsmufs/formats/sldasm.py`: SolidWorks assembly reader (components, configurations, placements).
- `solidsmufs/formats/parasolid/appearance.py`: colors, material, density and appearances in a part;
  `solidsmufs/kernel/looks.py`: the finish each body gets from them.
- `tests/`: `smoke.py` opens every sample file; `test_measure.py` checks measuring, mass properties
  and bounding boxes on a block with known answers; `test_sldasm.py` the assembly reader;
  `test_looks.py` colors, materials and configurations; `test_threads.py` thread recognition on
  modelled M6 and 1/4-20 threads (`.venv\Scripts\python -m unittest discover -s tests`).
- `solidsmufs/web/`: the interface (three.js graphics, SolidWorks-style shell, Wagner theme).

Settings and recent files live in `%APPDATA%\SolidSmufs`.

### Setting up on another PC

```
py -3.15 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

### Prebuilt copies

The repository's Releases page has builds for Windows, macOS (Apple Silicon and Intel, 14 or newer) and Linux (x64,
glibc 2.35 or newer) that need no Python. Pushing a `v*` tag makes them (`.github/workflows/prebuilds.yml`, using
`tools/solidsmurfs.spec`), after `tools/check_prebuild.py` has opened a part in each. They aren't signed.
