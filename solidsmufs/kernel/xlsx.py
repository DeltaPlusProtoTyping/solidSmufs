"""A small Excel workbook writer (no library needed): sheets of rows of cells, a few looks, column widths, formulas,
merged cells, cells colored by a rule, and how the sheet prints.

write(path, [{"name": "Sheet", "rows": [[cell, ...], ...], "widths": [12, 30, ...], "freeze": 4}, ...])
A cell is None, a number, a string, {"f": "SUM(A1:A3)"} (a formula, worked out when Excel opens the workbook), or
(value, look) with look one of "title", "head", "box", "num3", "num4", "label", "center", "status", "c3", "c4" (a
number centered, to three or four places).
A sheet may also have:
  "freeze": rows kept in view at the top
  "merge": ["A1:D1", ...]
  "color": [{"range": "E8:I20", "when": "E8<$C8", "as": "bad" | "good"}, ...]  (when: a formula written for the
           range's first cell, true where the color goes)
  "landscape": True, with the columns fitted to the paper's width
  "repeat": (first, last), the rows printed again at the top of every page (counted from 1)
"""

import zipfile
from xml.sax.saxutils import escape

LOOKS = {None: 0, "title": 1, "head": 2, "box": 3, "label": 4, "num3": 5, "num4": 6, "center": 7, "status": 8, "c3": 9, "c4": 10}
COLORS = {"bad": 0, "good": 1}

_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="2"><numFmt numFmtId="164" formatCode="0.000"/><numFmt numFmtId="165" formatCode="0.0000"/></numFmts>
<fonts count="3"><font><sz val="10"/><name val="Arial"/></font><font><b/><sz val="14"/><name val="Arial"/></font><font><b/><sz val="10"/><name val="Arial"/></font></fonts>
<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FFDCE6F1"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border><border><left style="thin"><color auto="1"/></left><right style="thin"><color auto="1"/></right><top style="thin"><color auto="1"/></top><bottom style="thin"><color auto="1"/></bottom><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="11">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="0" fontId="2" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1" applyAlignment="1"><alignment vertical="top"/></xf>
<xf numFmtId="165" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1" applyAlignment="1"><alignment vertical="top"/></xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="top" wrapText="1"/></xf>
<xf numFmtId="0" fontId="2" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="top"/></xf>
<xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="top"/></xf>
<xf numFmtId="165" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="top"/></xf>
</cellXfs>
<dxfs count="2">
<dxf><font><color rgb="FF9C0006"/></font><fill><patternFill><bgColor rgb="FFFFC7CE"/></patternFill></fill></dxf>
<dxf><font><color rgb="FF006100"/></font><fill><patternFill><bgColor rgb="FFC6EFCE"/></patternFill></fill></dxf>
</dxfs>
</styleSheet>"""


def col(i):
    """A column's letters: 0 is A."""
    return _col(i)


def _col(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _text(s):
    # (Excel refuses control characters)
    return escape("".join(ch for ch in str(s) if ch in "\t\n" or ord(ch) >= 32))


def _sheet(sheet):
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">']
    if sheet.get("landscape"):
        out.append('<sheetPr><pageSetUpPr fitToPage="1"/></sheetPr>')
    if sheet.get("freeze"):
        n = int(sheet["freeze"])
        out.append(f'<sheetViews><sheetView workbookViewId="0"><pane ySplit="{n}" topLeftCell="A{n + 1}" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>')
    if sheet.get("widths"):
        out.append("<cols>" + "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(sheet["widths"])) + "</cols>")
    out.append("<sheetData>")
    for r, row in enumerate(sheet["rows"], 1):
        cells = []
        for c, cell in enumerate(row):
            value, look = cell if isinstance(cell, tuple) else (cell, None)
            s = LOOKS.get(look, 0)
            ref = f"{_col(c)}{r}"
            if value is None or value == "":
                if s:
                    cells.append(f'<c r="{ref}" s="{s}"/>')
            elif isinstance(value, dict):
                cells.append(f'<c r="{ref}" s="{s}"><f>{_text(value["f"])}</f></c>')
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                cells.append(f'<c r="{ref}" s="{s}"><v>{value!r}</v></c>')
            else:
                cells.append(f'<c r="{ref}" s="{s}" t="inlineStr"><is><t xml:space="preserve">{_text(value)}</t></is></c>')
        out.append(f'<row r="{r}">{"".join(cells)}</row>')
    out.append("</sheetData>")
    if sheet.get("merge"):
        out.append(f'<mergeCells count="{len(sheet["merge"])}">' + "".join(f'<mergeCell ref="{m}"/>' for m in sheet["merge"]) + "</mergeCells>")
    for i, rule in enumerate(sheet.get("color") or [], 1):
        out.append(f'<conditionalFormatting sqref="{rule["range"]}"><cfRule type="expression" dxfId="{COLORS[rule["as"]]}" priority="{i}">'
                   f'<formula>{_text(rule["when"])}</formula></cfRule></conditionalFormatting>')
    if sheet.get("landscape"):
        out.append('<pageMargins left="0.4" right="0.4" top="0.5" bottom="0.5" header="0.3" footer="0.3"/>'
                   '<pageSetup orientation="landscape" fitToWidth="1" fitToHeight="0"/>')
    out.append("</worksheet>")
    return "".join(out)


def ref(name):
    """A sheet's name as a formula writes it: 'AS9102 Form 3'."""
    return "'" + str(name)[:31].replace("'", "''") + "'"


def write(path, sheets):
    names = [escape(str(s["name"])[:31], {'"': "&quot;"}) for s in sheets]
    again = "".join(f'<definedName name="_xlnm.Print_Titles" localSheetId="{i}">{escape(ref(s["name"]))}!${s["repeat"][0]}:${s["repeat"][1]}</definedName>'
                    for i, s in enumerate(sheets) if s.get("repeat"))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                             for i in range(1, len(sheets) + 1)) + "</Types>")
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{n}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(names, 1)) + "</sheets>"
                   + (f"<definedNames>{again}</definedNames>" if again else "") + '<calcPr fullCalcOnLoad="1"/></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
                             for i in range(1, len(sheets) + 1))
                   + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr("xl/styles.xml", _STYLES)
        for i, s in enumerate(sheets, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", _sheet(s))
