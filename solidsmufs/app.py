"""The desktop window: a Qt WebEngine view of the viewer page, plus what only a native app can do
(file dialogs, dropped files, the window title)."""

import base64
import ctypes
import json
import logging
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

from . import APP_NAME, printing, settings
from .archive import ChooseInArchive
from .kernel.formats import ALL_FORMATS, EDRAWINGS_FORMATS, IMAGE_FORMATS, TOOLPATH_FORMATS
from .server import WEB, App, Native, needs_save_as

log = logging.getLogger("solidsmufs")


def _setup_logging():
    logging.basicConfig(filename=str(settings.folder() / "log.txt"), level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")


def run(argv):
    _setup_logging()
    log.info("[timing] python started")
    if "--difficulty" in argv:  # a print's part difficulty as JSON, with no window: for a quoting system
        from . import difficulty
        return difficulty.main(argv)
    browser_mode = "--browser" in argv or "--no-open" in argv
    port = 0
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    try:
        job = printing.parse_job(argv)  # printing with no window: --print, --print-to, or Acrobat's /t and /p
    except printing.PrintError as e:
        log.error("print: %s", e)
        print(e, file=sys.stderr)
        return 2
    valued = ("--port", "--snapshot", "--snapshot-js", "--snapshot-delay")  # options followed by a value, not a file
    files = [a for i, a in enumerate(argv) if not a.startswith("--") and Path(a).suffix.lower() in ALL_FORMATS
             and not (i and argv[i - 1] in valued)]
    if job:
        files = job["files"]
    # development: --snapshot out.png [--snapshot-js "script"] [--snapshot-delay seconds] renders the
    # window off screen, runs the script in the page, saves a picture of the window and quits
    snapshot = argv[argv.index("--snapshot") + 1] if "--snapshot" in argv else None
    snap_js = argv[argv.index("--snapshot-js") + 1] if "--snapshot-js" in argv else ""
    snap_delay = float(argv[argv.index("--snapshot-delay") + 1]) if "--snapshot-delay" in argv else 8.0

    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--ignore-gpu-blocklist")
    from .gpu import prefer_discrete
    chip = prefer_discrete()  # two-GPU laptops: draw on the discrete chip, not the flickery integrated one
    if chip:
        log.info("drawing on %s (adapter %s)", chip, os.environ["QT_D3D_ADAPTER_INDEX"])
    from PySide6.QtCore import QCoreApplication, QObject, Qt, QUrl, Signal, Slot, QEvent, QSettings, QByteArray
    from PySide6.QtGui import QColor, QIcon, QDesktopServices
    from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow

    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("WagnerMachine.SolidSmurfs")
        except Exception:
            pass
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    qapp = QApplication(sys.argv[:1])
    qapp.setApplicationName(APP_NAME)
    qapp.setOrganizationName("SolidSmufs")

    # one window: a second launch (e.g. "Open with" on another file) hands its files to the first
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    import getpass
    instance_key = f"SolidSmufs-{getpass.getuser()}"
    if not browser_mode and not snapshot and not job:  # a print job is a process of its own, start to finish
        # Explorer starts one process per selected file at once: the lock picks a single first
        # window, and the others wait for its listener instead of opening windows of their own
        from PySide6.QtCore import QLockFile
        import tempfile
        import time
        instance_lock = QLockFile(str(Path(tempfile.gettempdir()) / f"{instance_key}.lock"))
        first = instance_lock.tryLock(0)  # holding the lock means no other window is running
        deadline = time.monotonic() + 30
        while not first:
            probe = QLocalSocket()
            probe.connectToServer(instance_key)
            if probe.waitForConnected(400):
                probe.write(json.dumps([str(Path(f).resolve()) for f in files]).encode())
                probe.flush()
                probe.waitForBytesWritten(1500)
                probe.disconnectFromServer()
                return 0
            if time.monotonic() > deadline:
                break
            time.sleep(0.25)
            first = instance_lock.tryLock(0)  # the first window closed before listening
    icon = QIcon(str(WEB / "img" / "solidsmurfs.ico"))
    qapp.setWindowIcon(icon)

    class Bridge(QObject):
        """Runs native calls from server threads on the GUI thread and hands back the answer."""

        call = Signal(object)

        def __init__(self):
            super().__init__()
            self.call.connect(self._run, Qt.ConnectionType.QueuedConnection)

        @Slot(object)
        def _run(self, job):
            try:
                job["result"] = job["fn"](*job["args"])
            except Exception as e:  # never leave the server thread waiting
                log.exception("native call failed")
                job["result"] = None
                job["error"] = str(e)
            job["done"].set()

        def __call__(self, fn, *args):
            job = {"fn": fn, "args": args, "done": threading.Event()}
            self.call.emit(job)
            job["done"].wait()
            return job.get("result")

    bridge = Bridge()
    window_ref = {}

    class QtNative(Native):
        available = True

        def open_dialog(self, start_dir=None):
            def ask():
                def pats(formats):
                    return " ".join(f"*{e}" for e in sorted(formats))
                cad = "*.step *.stp *.igs *.iges *.sldprt *.sldasm *.x_t *.x_b *.xmt_txt *.xmt_bin *.brep"
                mesh = "*.stl *.obj *.ply *.off *.3mf *.glb *.gltf"
                drawings = f"*.dxf *.dwg *.plt *.hpgl *.hgl *.svg *.slddrw {pats(EDRAWINGS_FORMATS)} *.pdf"
                start = start_dir or settings.load()["ui"].get("lastDir") or str(Path.home())
                path, _ = QFileDialog.getOpenFileName(window_ref.get("w"), "Open a file", start,
                                                      f"Everything SolidSmurfs opens ({pats(ALL_FORMATS)});;CAD ({cad});;Meshes ({mesh});;"
                                                      f"Drawings and PDFs ({drawings});;G-code ({pats(TOOLPATH_FORMATS)});;"
                                                      f"Pictures ({pats(IMAGE_FORMATS)});;Zip archives (*.zip);;All files (*)")
                if path:
                    settings.set_ui({"lastDir": str(Path(path).parent)})
                return path or None
            return bridge(ask)

        def save_image(self, data, suggested):
            def ask():
                start = str(Path(settings.load()["ui"].get("lastDir") or Path.home()) / suggested)
                path, _ = QFileDialog.getSaveFileName(window_ref.get("w"), "Save picture", start, "PNG image (*.png)")
                if not path:
                    return None
                raw = base64.b64decode(data.split(",", 1)[1] if "," in data else data)
                Path(path).write_bytes(raw)
                return path
            return bridge(ask)

        def save_file(self, title, suggested, file_filter):
            def ask():
                start = str(Path(settings.load()["ui"].get("lastDir") or Path.home()) / suggested)
                path, _ = QFileDialog.getSaveFileName(window_ref.get("w"), title, start, file_filter)
                return path or None
            return bridge(ask)

        def open_files(self, title, file_filter):
            def ask():
                start = settings.load()["ui"].get("lastDir") or str(Path.home())
                paths, _ = QFileDialog.getOpenFileNames(window_ref.get("w"), title, start, file_filter)
                if paths:
                    settings.set_ui({"lastDir": str(Path(paths[0]).parent)})
                return paths
            return bridge(ask) or []

        def _ask_printer(self, title, pages=0):
            """The print dialog, on the GUI thread: a printer set up as chosen, or None if cancelled."""
            def ask():
                from PySide6.QtPrintSupport import QPrintDialog, QPrinter
                printer = QPrinter(QPrinter.PrinterMode.HighResolution)
                last = settings.load()["ui"].get("printer")
                if last and last in printing.printer_names():
                    printer.setPrinterName(last)
                printer.setDocName(title)
                dlg = QPrintDialog(printer, window_ref.get("w"))
                dlg.setWindowTitle(f"Print {title}")
                opts = QPrintDialog.PrintDialogOption
                dlg.setOption(opts.PrintPageRange, pages > 1)
                dlg.setOption(opts.PrintSelection, False)
                dlg.setOption(opts.PrintCurrentPage, False)
                if pages > 1:
                    dlg.setMinMax(1, pages)
                if dlg.exec() != QPrintDialog.DialogCode.Accepted:
                    return None
                if printer.outputFormat() == QPrinter.OutputFormat.NativeFormat:
                    settings.set_ui({"printer": printer.printerName()})
                return printer
            return bridge(ask)

        def print_pages(self, doc):
            pages = doc.meta["pdf"]["pages"]
            printer = self._ask_printer(doc.name, len(pages))
            if printer is None:
                return None
            which = printing.dialog_pages(printer, len(pages))
            job = printing.Job(printer, bridge)  # pages render on this thread; the printer is spoken to on the GUI thread
            try:
                job.add_pages(doc, pages, which)
            finally:
                job.finish()
            return job.sheets

        def print_image(self, data, name):
            img = printing.image_from_data_url(data)
            printer = self._ask_printer(name)
            if printer is None:
                return None
            job = printing.Job(printer, bridge)
            try:
                job.add_image(img)
            finally:
                job.finish()
            return job.sheets

        def reveal(self, path):
            if sys.platform == "win32" and Path(path).exists():
                import subprocess
                subprocess.Popen(["explorer", "/select,", str(Path(path))])
            else:
                super().reveal(path)

        def set_title(self, title):
            if "w" in window_ref:
                bridge(lambda: window_ref["w"].setWindowTitle(title))

    app = App(QtNative())
    app.start(port)
    for f in files:
        try:
            app.open(f)
        except ChooseInArchive as e:  # the page shows what's in it once it's up
            app.browse_first = e.path
        except Exception as e:
            log.warning("could not open %s: %s", f, e)

    if browser_mode:
        print(app.url, flush=True)
        if "--browser" in argv:
            webbrowser.open(app.url)
        code = qapp.exec()
        app.stop()
        return code

    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView

    # a profile kept on disk (Qt's default one is thrown away at exit): compiled scripts and shaders
    # are reused on the next launch, and the page's saved state (dialog positions) survives
    web_dir = Path(os.environ.get("LOCALAPPDATA") or settings.folder()) / "SolidSmufs" / "web"
    profile = QWebEngineProfile("SolidSmurfs", qapp)
    profile.setPersistentStoragePath(str(web_dir / "storage"))
    profile.setCachePath(str(web_dir / "cache"))
    profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)

    class Page(QWebEnginePage):
        def javaScriptConsoleMessage(self, level, message, line, source):
            log.info("js[%s] %s (%s:%s)", int(level.value) if hasattr(level, "value") else level, message, source, line)

        def acceptNavigationRequest(self, url, nav_type, is_main):
            if url.host() == "127.0.0.1" or url.scheme() in ("data", "blob", "about"):
                return True
            if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in ALL_FORMATS:
                open_paths([url.toLocalFile()])
                return False
            QDesktopServices.openUrl(url)  # links out go to the real browser
            return False

    class Window(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle(APP_NAME)
            self.view = QWebEngineView(self)
            self.page = Page(profile, self.view)
            self.view.setPage(self.page)
            s = self.page.settings()
            s.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
            s.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True)
            s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)
            self.setCentralWidget(self.view)
            self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)  # no browser Back/Reload menu
            self.view.setAcceptDrops(True)
            self.view.titleChanged.connect(lambda t: self.setWindowTitle(t or APP_NAME))
            self.view.loadFinished.connect(self._hook_drops)
            qs = QSettings()
            geo = qs.value("geometry")
            if isinstance(geo, QByteArray) and not geo.isEmpty():
                self.restoreGeometry(geo)
            else:
                self.resize(1440, 900)
            # paint the saved theme's color from the start instead of white while the page loads
            theme = "dark" if settings.load()["ui"].get("theme") == "dark" else "light"
            self.page.setBackgroundColor(QColor("#151a25" if theme == "dark" else "#f6f8fa"))
            self.view.setUrl(QUrl(f"{app.url}&theme={theme}"))

        def _unsaved_ok(self):
            """PDFs with edits not saved: ask to save them (True to go on closing, False to stay open)."""
            from PySide6.QtWidgets import QMessageBox
            dirty = [d for d in app.docs.all() if getattr(d, "pdf_dirty", False)]
            if not dirty:
                return True
            names = "\n".join(f"  {d.name}" for d in dirty)
            box = QMessageBox(QMessageBox.Icon.Warning, APP_NAME, f"Save the changes to these PDFs before closing?\n\n{names}",
                              QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                              | QMessageBox.StandardButton.Cancel, self)
            box.button(QMessageBox.StandardButton.Discard).setText("Don't Save")
            answer = box.exec()
            if answer == QMessageBox.StandardButton.Cancel:
                return False
            if answer == QMessageBox.StandardButton.Discard:
                return True
            for d in dirty:
                try:
                    path = None
                    if needs_save_as(d, app.upload_dir):
                        path, _ = QFileDialog.getSaveFileName(self, f"Save {d.name} As", d.name, "PDF (*.pdf)")
                        if not path:
                            return False
                    d.request("pdf_edit", timeout=600, op="save", args={"path": path})
                    d.pdf_dirty = False
                except Exception as e:
                    QMessageBox.critical(self, APP_NAME, f"{d.name} couldn't be saved: {e}")
                    return False
            return True

        def _hook_drops(self, ok):
            proxy = self.view.focusProxy()
            for w in (self.view, proxy):
                if w is not None:
                    w.installEventFilter(self)
                    w.setAcceptDrops(True)

        def eventFilter(self, obj, ev):
            t = ev.type()
            if t in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
                if _model_paths(ev.mimeData()):
                    ev.acceptProposedAction()
                    if t == QEvent.Type.DragEnter:
                        self.page.runJavaScript("window.SS && SS.nativeDrag(true)")
                    return True
            elif t == QEvent.Type.DragLeave:
                self.page.runJavaScript("window.SS && SS.nativeDrag(false)")
            elif t == QEvent.Type.Drop:
                paths = _model_paths(ev.mimeData())
                if paths:
                    ev.acceptProposedAction()
                    self.page.runJavaScript("window.SS && SS.nativeDrag(false)")
                    open_paths(paths)
                    return True
            return super().eventFilter(obj, ev)

        def closeEvent(self, ev):
            if not self._unsaved_ok():
                ev.ignore()
                return
            QSettings().setValue("geometry", self.saveGeometry())
            super().closeEvent(ev)
            self.view.setPage(None)
            self.page.deleteLater()  # before the profile goes, or Qt warns and may not flush it

    def _model_paths(md):
        if not md.hasUrls():
            return []
        return [u.toLocalFile() for u in md.urls()
                if u.isLocalFile() and Path(u.toLocalFile()).suffix.lower() in ALL_FORMATS]

    def open_paths(paths):
        for p in paths:
            try:
                doc = app.open(p)
                window.page.runJavaScript(f"window.SS && SS.attach({json.dumps(doc.id)})")
            except ChooseInArchive as e:  # a zip of several files: show them, to pick from
                window.page.runJavaScript(f"window.SS && SS.browse({json.dumps(e.path)})")
            except Exception as e:
                window.page.runJavaScript(f"window.SS && SS.toast({json.dumps(str(e))}, 'error')")

    if job:
        try:
            code = _print_headless(job, app, Window, window_ref)
        except printing.PrintError as e:
            log.error("print: %s", e)
            print(e, file=sys.stderr)
            code = 1
        app.stop()
        return code

    window = Window()
    window_ref["w"] = window
    if snapshot:
        from PySide6.QtCore import QTimer
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        window.resize(1440, 900)
        window.show()
        if snap_js:
            QTimer.singleShot(int(snap_delay * 600), lambda: window.page.runJavaScript(snap_js))

        def shoot():
            window.grab().save(snapshot)
            app.stop()
            qapp.quit()

        QTimer.singleShot(int(snap_delay * 1000), shoot)
        return qapp.exec()
    window.show()
    log.info("[timing] window shown")

    # a 3Dconnexion SpaceMouse, read straight from the device; motion goes to the page on the GUI thread
    class SpaceBridge(QObject):  # lives on the GUI thread, so the reader thread's emits are queued to it
        moved = Signal(list)

        def __init__(self):
            super().__init__()
            self.latest, self.sent_at, self.busy = None, 0.0, False

        @Slot(list)
        def take(self, v):
            self.latest = v
            self.send()

        def send(self):
            # one call in the page at a time, always the newest values: a busy page must not build up a
            # backlog of old motion that then plays out all at once
            if self.latest is None or (self.busy and time.monotonic() - self.sent_at < 0.25):
                return
            v, self.latest = self.latest, None
            self.busy, self.sent_at = True, time.monotonic()
            window.page.runJavaScript(f"window.SS && SS.viewer.spaceNav({json.dumps(v)})", 0, self.done)

        def done(self, _result=None):
            self.busy = False
            self.send()

    space = SpaceBridge()
    space.moved.connect(space.take)
    reader = None
    if sys.platform == "win32" and os.environ.get("SOLIDSMURFS_SPACEMOUSE") != "off":
        try:
            from .spacemouse import Reader
            reader = Reader(space.moved.emit)
            reader.start()
        except Exception:
            log.exception("SpaceMouse: not started")

    def handoff():
        conn = listener.nextPendingConnection()

        def read():
            try:
                paths = json.loads(bytes(conn.readAll()).decode() or "[]")
            except ValueError:
                paths = []
            if window.isMinimized():
                window.showNormal()
            window.raise_()
            window.activateWindow()
            open_paths(paths)

        conn.readyRead.connect(read)
        conn.disconnected.connect(conn.deleteLater)

    QLocalServer.removeServer(instance_key)
    listener = QLocalServer()
    listener.newConnection.connect(handoff)
    listener.listen(instance_key)

    code = qapp.exec()
    if reader is not None:
        reader.stop()
    app.stop()
    return code


def _print_headless(job, app, Window, window_ref):
    """Print the opened files with no window on screen, then return the exit code: 0 when every file printed.
    Pages print straight from the document; a model is drawn in a window kept off screen, then printed as a
    picture. The job is handed to the spooler before this returns, so the process can simply end."""
    from PySide6.QtCore import QEventLoop, Qt, QTimer
    from PySide6.QtPrintSupport import QPrintDialog, QPrinter

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    docs = list(app.docs.all())
    failed = len(job["files"]) - len(docs)  # couldn't be opened at all (logged by run)
    if not docs:
        raise printing.PrintError("None of the files could be opened.")
    deadline = time.monotonic() + 600
    while any(d.state == "loading" for d in docs) and time.monotonic() < deadline:
        wait(100)

    title = docs[0].name if len(docs) == 1 else f"{len(docs)} files"
    if job["mode"] == "dialog":
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setDocName(title)
        dlg = QPrintDialog(printer)
        dlg.setWindowTitle(f"Print {title}")
        lone = docs[0].meta["pdf"]["pages"] if len(docs) == 1 and docs[0].state == "ready" and docs[0].meta.get("pdf") else []
        dlg.setOption(QPrintDialog.PrintDialogOption.PrintPageRange, len(lone) > 1)
        if len(lone) > 1:
            dlg.setMinMax(1, len(lone))
        if dlg.exec() != QPrintDialog.DialogCode.Accepted:
            return 1
    else:
        printer = printing.make_printer(job["printer"], job["out"], job["copies"], title)

    out = printing.Job(printer)
    window = None
    try:
        for d in docs:
            if d.state != "ready":
                log.error("print: %s: %s", d.name, d.error or d.locked or "didn't finish opening")
                print(f"{d.name}: {d.error or d.locked or 'did not finish opening'}", file=sys.stderr)
                failed += 1
                continue
            if d.meta.get("pdf"):  # a PDF, a picture or a preview: its pages
                pages = d.meta["pdf"]["pages"]
                which = printing.dialog_pages(printer, len(pages)) if job["mode"] == "dialog" \
                    else printing.pick_pages(job.get("pages"), len(pages))
                out.add_pages(d, pages, which)
                log.info("print: %s, %d page(s)", d.name, len(which))
                continue
            if window is None:  # a model: the page draws it, off screen
                window = Window()
                window_ref["w"] = window
                window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
                window.resize(1600, 1100)
                window.show()
            data, until = None, time.monotonic() + 300
            while not data and time.monotonic() < until:
                wait(400)
                got = {}
                loop = QEventLoop()
                window.page.runJavaScript(
                    f"window.SS && SS.printPicture ? SS.printPicture({json.dumps(d.id)}) : null", 0,
                    lambda r: (got.setdefault("r", r), loop.quit()))
                QTimer.singleShot(60000, loop.quit)
                loop.exec()
                data = got.get("r")
            if not data:
                log.error("print: %s: the view wasn't drawn", d.name)
                print(f"{d.name}: the view could not be drawn", file=sys.stderr)
                failed += 1
                continue
            out.add_image(printing.image_from_data_url(data))
            log.info("print: %s, a picture of the model", d.name)
    finally:
        out.finish()
        if window is not None:
            window.hide()  # not close(): closing would save this off-screen size as the window's own
    return 0 if out.sheets and not failed else 1
