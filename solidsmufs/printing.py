"""Printing: a PDF's (or a picture's) pages, or a picture of a model, fitted to the paper.

Pages are drawn by the document's worker at up to DPI dots per inch on the paper, turned to match the paper's
orientation and centred. A model is printed from a picture of the view the page makes on a white background.

From the command line, with no window (as Acrobat's /t), in a process of its own that ends once the job is with
the Windows spooler: exit code 0 when every file printed, 1 when any didn't, 2 for a mistake in the command.
    SolidSmurfs.exe --print FILE... [--printer NAME] [--copies N] [--pages 1-4,9]
    SolidSmurfs.exe --print-to OUT.pdf FILE...     (to a PDF file instead of a printer)
    SolidSmurfs.exe /t FILE [PRINTER [DRIVER [PORT]]]   (Acrobat's form, as Windows' "printto" runs it)
    SolidSmurfs.exe /p /h FILE                     (Acrobat's: the default printer, no dialog)
    SolidSmurfs.exe /p FILE                        (asks with the print dialog, then prints)
Several files go out as one job. --pages picks pages of a PDF ("-2" is the last two).
"""

from pathlib import Path

DPI = 300  # on the paper: plenty for a drawing's thinnest lines, and a tabloid page stays under 70 MB to send
MAX_PIXELS = 40_000_000  # a page bigger than this at DPI (a plotter sheet) is drawn coarser


class PrintError(ValueError):
    pass


def parse_job(argv):
    """The print job asked for on the command line, or None: {"mode": "default" | "named" | "pdf" | "dialog",
    "printer", "out", "copies", "files"}. `files` are the arguments that are files to print."""
    from .kernel.formats import ALL_FORMATS
    low = [a.lower() for a in argv]
    job = {"mode": None, "printer": None, "out": None, "copies": 1, "pages": None, "files": []}

    def value(flag):
        i = low.index(flag)
        if i + 1 >= len(argv):
            raise PrintError(f"{flag} needs a value after it.")
        return argv[i + 1]

    if "/t" in low or "/p" in low:  # Acrobat's: /t file [printer [driver [port]]], /p file, /p /h file (no dialog)
        i = low.index("/t") if "/t" in low else low.index("/p")
        rest = [a for a in argv[i + 1:] if a.lower() not in ("/h", "/n", "/s", "/o")]
        silent = "/h" in low
        if not rest:
            raise PrintError(f"{argv[i]} needs a file after it.")
        job["files"] = [rest[0]]
        if low[i] == "/p":
            job["mode"] = "default" if silent else "dialog"
        elif len(rest) > 1 and rest[1] and not rest[1].startswith("--"):
            job["mode"], job["printer"] = "named", rest[1]
        else:
            job["mode"] = "default"
    if "--print-to" in low:  # these win over Acrobat's form too
        job["mode"], job["out"] = "pdf", value("--print-to")
    elif "--print-dialog" in low:
        job["mode"] = "dialog"
    elif "--print" in low:
        job["mode"] = "default"
    elif not job["mode"]:
        return None
    if "--printer" in low:
        job["printer"] = value("--printer")
        if job["mode"] == "default":
            job["mode"] = "named"
    if "--copies" in low:
        try:
            job["copies"] = max(1, int(value("--copies")))
        except ValueError:
            raise PrintError("--copies needs a number.") from None
    if "--pages" in low:
        job["pages"] = parse_pages(value("--pages"))
    valued = {"--print-to", "--printer", "--copies", "--pages", "--port"}
    if not job["files"]:  # Acrobat's form has already named its one file
        job["files"] = [a for i, a in enumerate(argv) if not a.startswith("-") and Path(a).suffix.lower() in ALL_FORMATS
                        and not (i and low[i - 1] in valued)]
    if not job["files"]:
        raise PrintError("Name a file to print.")
    return job


def parse_pages(text):
    """Page numbers as people write them ("1-4,9", "7-", "-2" counted from the end): a list of 1-based numbers
    and (first, last) ranges, last None for "to the end". Turned into pages with pick_pages once the count is known."""
    out = []
    for part in text.replace(" ", "").split(","):
        if not part:
            continue
        try:
            if part.startswith("-") and part[1:].isdigit():  # the last n pages
                out.append((-int(part[1:]), None))
            elif "-" in part:
                a, b = part.split("-", 1)
                out.append((int(a), int(b) if b else None))
            else:
                out.append((int(part), int(part)))
        except ValueError:
            raise PrintError(f'"{text}" isn\'t a list of pages, such as 1-4,9.') from None
    if not out:
        raise PrintError("--pages needs page numbers, such as 1-4,9.")
    return out


def pick_pages(spec, count):
    """The 0-based pages a parse_pages list picks from `count` pages, in order, each once."""
    if spec is None:
        return list(range(count))
    picked = []
    for a, b in spec:
        if a < 0:
            first, last = max(1, count + a + 1), count
        else:
            first, last = a, count if b is None else b
        for n in range(max(1, first), min(count, last) + 1):
            if n - 1 not in picked:
                picked.append(n - 1)
    return picked


def printer_names():
    from PySide6.QtPrintSupport import QPrinterInfo
    return [p.printerName() for p in QPrinterInfo.availablePrinters()]


def make_printer(name=None, out=None, copies=1, title="SolidSmurfs"):
    """A printer ready to print to: the one named (its whole name, any case), the default one, or a PDF file
    at `out`."""
    from PySide6.QtPrintSupport import QPrinter, QPrinterInfo
    p = QPrinter(QPrinter.PrinterMode.HighResolution)
    if out:
        p.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        p.setOutputFileName(str(Path(out).resolve()))
    elif name:
        names = printer_names()
        # the whole name only, as Acrobat: part of one could send a job to a printer nobody meant
        found = [n for n in names if n.lower() == name.strip().lower()]
        if not found:
            raise PrintError(f'No printer is named "{name}". The printers here: {", ".join(names) or "none"}.')
        p.setPrinterName(found[0])
    else:
        d = QPrinterInfo.defaultPrinter()
        if d.isNull():
            raise PrintError("There's no default printer. Name one with --printer.")
        p.setPrinterName(d.printerName())
    p.setCopyCount(max(1, int(copies)))
    p.setDocName(title)
    return p


class Job:
    """One print job: each page or picture added goes on a sheet of its own."""

    def __init__(self, printer, gui=None):
        """`gui` runs a call on the GUI thread and waits for it (the window's bridge): everything that talks to the
        printer goes through it, since a driver such as Microsoft Print to PDF opens its own Save As box when printing
        starts, and that box needs the GUI thread. Pages are drawn by the worker in between, off it."""
        from PySide6.QtGui import QPainter
        self.printer = printer
        self.painter = QPainter()
        self.sheets = 0
        self.gui = gui

    def _on_gui(self, fn, *args):
        if self.gui is None:
            return fn(*args)
        box = {}

        def run():
            try:
                box["r"] = fn(*args)
            except Exception as e:  # handed back to this thread, not swallowed by the bridge
                box["e"] = e
        self.gui(run)
        if "e" in box:
            raise box["e"]
        return box.get("r")

    def _sheet(self, wide):
        return self._on_gui(self._sheet_now, wide)

    def _draw(self, area, w, h, img):
        from PySide6.QtCore import QRectF
        self._on_gui(lambda: self.painter.drawImage(QRectF((area.width() - w) / 2, (area.height() - h) / 2, w, h), img))

    def _sheet_now(self, wide):
        """Start the next sheet, the paper turned landscape when `wide` (Acrobat's "auto portrait / landscape"):
        the area to draw in, in the painter's (device pixel) units."""
        from PySide6.QtGui import QPageLayout
        o = QPageLayout.Orientation
        self.printer.setPageOrientation(o.Landscape if wide else o.Portrait)
        if self.sheets == 0:
            if not self.painter.begin(self.printer):
                raise PrintError("Printing didn't start: it was cancelled, the printer is offline, or the file is open elsewhere.")
        elif not self.printer.newPage():
            raise PrintError("The printer stopped taking pages.")
        self.sheets += 1
        from PySide6.QtGui import QPainter
        self.painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        return self.painter.viewport()

    def add_pages(self, doc, pages, which=None):
        """A PDF's (or picture's) pages, from the document's worker: those in `which` (0-based), or all."""
        from PySide6.QtGui import QImage
        which = range(len(pages)) if which is None else [i for i in which if 0 <= i < len(pages)]
        if not which:
            raise PrintError(f"Those pages aren't in it: it has {len(pages)}.")
        res = self.printer.resolution()
        for i in which:
            pw, ph = pages[i]["w"], pages[i]["h"]
            area = self._sheet(pw > ph)
            fit = min(area.width() / pw, area.height() / ph)  # device pixels per point
            scale = fit * min(1.0, DPI / res)  # drawn pixels per point
            if pw * ph * scale * scale > MAX_PIXELS:
                scale = (MAX_PIXELS / (pw * ph)) ** 0.5
            w, h = max(1, round(pw * scale)), max(1, round(ph * scale))
            raw = doc.request("pdf_tile", timeout=300, page=i, scale=scale, x=0, y=0, w=w, h=h)
            img = QImage(raw, w, h, w * 4, QImage.Format.Format_RGBA8888)
            self._draw(area, pw * fit, ph * fit, img)

    def add_image(self, img):
        """A picture (a QImage), as big as fits, on paper turned the picture's way."""
        if img.isNull():
            raise PrintError("There was no picture to print.")
        area = self._sheet(img.width() > img.height())
        fit = min(area.width() / img.width(), area.height() / img.height())
        self._draw(area, img.width() * fit, img.height() * fit, img)

    def finish(self):
        if self.sheets and self.painter.isActive():
            self._on_gui(self.painter.end)
        return self.sheets


def image_from_data_url(data):
    """A QImage from a data: URL (or bare base64) of a PNG, on white: transparent parts print as paper."""
    import base64
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    raw = base64.b64decode(data.split(",", 1)[1] if "," in data else data)
    img = QImage.fromData(raw)
    if img.isNull():
        raise PrintError("The picture to print couldn't be read.")
    if img.hasAlphaChannel():
        out = QImage(img.size(), QImage.Format.Format_RGB32)
        out.fill(Qt.GlobalColor.white)
        p = QPainter(out)
        p.drawImage(0, 0, img)
        p.end()
        img = out
    return img


def dialog_pages(dialog_printer, count):
    """The 0-based pages the print dialog asked for."""
    from PySide6.QtPrintSupport import QPrinter
    if dialog_printer.printRange() == QPrinter.PrintRange.PageRange and dialog_printer.fromPage() > 0:
        first = max(1, dialog_printer.fromPage())
        last = min(count, dialog_printer.toPage() or count)
        return list(range(first - 1, max(first, last)))
    return list(range(count))
