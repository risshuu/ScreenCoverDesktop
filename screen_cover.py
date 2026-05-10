"""ScreenCoverDesktop - app-agnostic clone of YouTubeScreenCover.

Always-on-top frameless overlays you drag/resize over anything on screen.
Lives in the system tray. Works over YouTube, Netflix, Twitch, VLC, anything.

Cover types:
  - Bar       : solid black with adjustable opacity (top/bottom curtain pattern)
  - Mosaic    : pixelates whatever is behind it, with adjustable intensity

Hotkeys (global):
  Ctrl+Alt+H  toggle show/hide all
  Ctrl+Alt+L  toggle lock (locked = click-through, no edit handles)
  Ctrl+Alt+M  add a new mosaic region

Right-click any cover for per-cover options. Right-click the tray icon for
add/remove/quit.
"""

import sys
import ctypes

from PySide6.QtCore import Qt, QTimer, QRect, QObject
from PySide6.QtGui import (QPainter, QColor, QIcon, QPixmap, QAction,
                           QGuiApplication, QFont)
from PySide6.QtWidgets import (QApplication, QWidget, QSystemTrayIcon, QMenu,
                               QSlider, QLabel, QVBoxLayout, QWidgetAction)

try:
    from pynput import keyboard as _kb
    HAS_HOTKEYS = True
except ImportError:
    HAS_HOTKEYS = False


WDA_EXCLUDEFROMCAPTURE = 0x00000011
EDGE = 8


def exclude_from_capture(widget):
    """Tell DWM to skip this window during screen capture (Win10 2004+).
    Without this, MosaicCover would capture its own pixels and feedback-loop."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.SetWindowDisplayAffinity(
            int(widget.winId()), WDA_EXCLUDEFROMCAPTURE
        )
    except Exception:
        pass


class Cover(QWidget):
    def __init__(self, controller, mode="bar", opacity_pct=100, intensity=50):
        super().__init__()
        self.controller = controller
        self.mode = mode
        self.opacity_pct = opacity_pct
        self.intensity = intensity
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self._drag_offset = None
        self._resize_edge = None
        self._resize_origin = None
        self._resize_geom = None
        self._locked = False
        self._snapshot = None
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._capture)

    def show_and_init(self):
        self.show()
        exclude_from_capture(self)
        if self.mode == "mosaic":
            self._timer.start()

    def hideEvent(self, _):
        self._timer.stop()

    def showEvent(self, _):
        if self.mode == "mosaic":
            self._timer.start()

    def set_mode(self, mode):
        if mode == self.mode:
            return
        self.mode = mode
        if mode == "mosaic" and self.isVisible():
            self._timer.start()
        else:
            self._timer.stop()
            self._snapshot = None
        self.update()

    def set_opacity(self, pct):
        self.opacity_pct = max(0, min(100, pct))
        self.update()

    def set_intensity(self, v):
        self.intensity = max(1, min(100, v))
        self.update()

    def set_locked(self, locked):
        self._locked = locked
        self.setAttribute(Qt.WA_TransparentForMouseEvents, locked)
        self.update()

    def _capture(self):
        scr = self.screen() or QGuiApplication.primaryScreen()
        if not scr:
            return
        g = self.geometry()
        sg = scr.geometry()
        pm = scr.grabWindow(0, g.x() - sg.x(), g.y() - sg.y(), g.width(), g.height())
        self._snapshot = pm
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        if self.mode == "bar":
            self._paint_bar(p)
        else:
            self._paint_mosaic(p)
        if not self._locked:
            p.setPen(QColor(255, 255, 255, 110 if self.mode == "mosaic" else 90))
            p.drawRect(self.rect().adjusted(0, 0, -1, -1))

    def _paint_bar(self, p):
        p.fillRect(self.rect(), QColor(0, 0, 0, int(255 * self.opacity_pct / 100)))

    def _paint_mosaic(self, p):
        if not self._snapshot or self._snapshot.isNull():
            p.fillRect(self.rect(), QColor(40, 40, 40, 200))
            return
        block = max(2, int(32 * self.intensity / 100))
        sw = max(1, self.width() // block)
        sh = max(1, self.height() // block)
        small = self._snapshot.scaled(sw, sh, Qt.IgnoreAspectRatio, Qt.FastTransformation)
        # Use rect-target overload so Qt scales to the widget's logical size,
        # which keeps mosaic correct on HiDPI displays.
        p.drawPixmap(self.rect(), small)
        darken = int(255 * (self.intensity / 100) * 0.3)
        if darken:
            p.fillRect(self.rect(), QColor(0, 0, 0, darken))

    def _hit_edge(self, p):
        r = self.rect()
        l = p.x() < EDGE
        rr = p.x() > r.width() - EDGE
        t = p.y() < EDGE
        b = p.y() > r.height() - EDGE
        if t and l: return 'tl'
        if t and rr: return 'tr'
        if b and l: return 'bl'
        if b and rr: return 'br'
        if l: return 'l'
        if rr: return 'r'
        if t: return 't'
        if b: return 'b'
        return None

    def _cursor_for(self, edge):
        return {
            'l': Qt.SizeHorCursor, 'r': Qt.SizeHorCursor,
            't': Qt.SizeVerCursor, 'b': Qt.SizeVerCursor,
            'tl': Qt.SizeFDiagCursor, 'br': Qt.SizeFDiagCursor,
            'tr': Qt.SizeBDiagCursor, 'bl': Qt.SizeBDiagCursor,
        }.get(edge, Qt.SizeAllCursor)

    def mousePressEvent(self, ev):
        if self._locked:
            return
        if ev.button() == Qt.RightButton:
            self._show_menu(ev.globalPosition().toPoint())
            return
        if ev.button() != Qt.LeftButton:
            return
        edge = self._hit_edge(ev.position().toPoint())
        if edge:
            self._resize_edge = edge
            self._resize_origin = ev.globalPosition().toPoint()
            self._resize_geom = QRect(self.geometry())
        else:
            self._drag_offset = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, ev):
        if self._locked:
            return
        gp = ev.globalPosition().toPoint()
        if self._drag_offset is not None:
            self.move(gp - self._drag_offset)
        elif self._resize_edge:
            d = gp - self._resize_origin
            g = QRect(self._resize_geom)
            e = self._resize_edge
            if 'l' in e: g.setLeft(g.left() + d.x())
            if 'r' in e: g.setRight(g.right() + d.x())
            if 't' in e: g.setTop(g.top() + d.y())
            if 'b' in e: g.setBottom(g.bottom() + d.y())
            if g.width() < 30: g.setWidth(30)
            if g.height() < 20: g.setHeight(20)
            self.setGeometry(g)
        else:
            self.setCursor(self._cursor_for(self._hit_edge(ev.position().toPoint())))

    def mouseReleaseEvent(self, ev):
        self._drag_offset = None
        self._resize_edge = None
        self._resize_geom = None

    def _show_menu(self, gp):
        m = QMenu(self)
        for a in self.controller.menu_actions_for(self):
            m.addAction(a)
        m.exec(gp)


def make_tray_icon():
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(20, 20, 20))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(2, 2, 60, 60, 12, 12)
    p.setPen(QColor(255, 255, 255))
    p.setFont(QFont("Arial", 28, QFont.Bold))
    p.drawText(pm.rect(), Qt.AlignCenter, "C")
    p.end()
    return QIcon(pm)


class Controller(QObject):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.covers = []
        self.locked = False
        self.tray = QSystemTrayIcon(make_tray_icon())
        self.tray.setToolTip("ScreenCoverDesktop")
        self.tray.setContextMenu(self._tray_menu())
        self.tray.show()
        self._kb_listener = None
        if HAS_HOTKEYS:
            self._setup_hotkeys()

    def _tray_menu(self):
        m = QMenu()
        m.addAction("Add top bar", self.add_top_bar)
        m.addAction("Add bottom bar", self.add_bottom_bar)
        m.addAction("Add mosaic region", self.add_mosaic)
        m.addSeparator()
        m.addAction("Toggle lock (click-through)\tCtrl+Alt+L", self.toggle_lock)
        m.addAction("Show / hide all\tCtrl+Alt+H", self.toggle_visibility)
        m.addSeparator()
        m.addAction("Remove all covers", self.remove_all)
        m.addSeparator()
        m.addAction("Quit", self.app.quit)
        return m

    def _setup_hotkeys(self):
        def trig(fn):
            return lambda: QTimer.singleShot(0, fn)
        self._kb_listener = _kb.GlobalHotKeys({
            '<ctrl>+<alt>+h': trig(self.toggle_visibility),
            '<ctrl>+<alt>+l': trig(self.toggle_lock),
            '<ctrl>+<alt>+m': trig(self.add_mosaic),
        })
        self._kb_listener.start()

    def _primary(self):
        return QGuiApplication.primaryScreen().availableGeometry()

    def add_top_bar(self):
        g = self._primary()
        c = Cover(self, mode="bar")
        c.setGeometry(g.x(), g.y(), g.width(), 100)
        self._add(c)

    def add_bottom_bar(self):
        g = self._primary()
        c = Cover(self, mode="bar")
        c.setGeometry(g.x(), g.bottom() - 100, g.width(), 100)
        self._add(c)

    def add_mosaic(self):
        g = self._primary()
        c = Cover(self, mode="mosaic")
        w, h = 480, 200
        c.setGeometry(g.center().x() - w // 2, g.center().y() - h // 2, w, h)
        self._add(c)

    def _add(self, c):
        self.covers.append(c)
        c.set_locked(self.locked)
        c.show_and_init()

    def toggle_lock(self):
        self.locked = not self.locked
        for c in self.covers:
            c.set_locked(self.locked)
        self.tray.showMessage(
            "ScreenCoverDesktop",
            "Locked (click-through)" if self.locked else "Unlocked (editable)",
            QSystemTrayIcon.Information, 1200
        )

    def toggle_visibility(self):
        any_visible = any(c.isVisible() for c in self.covers)
        for c in self.covers:
            c.setVisible(not any_visible)

    def remove_all(self):
        for c in list(self.covers):
            c.close()
        self.covers.clear()

    def remove_one(self, c):
        if c in self.covers:
            self.covers.remove(c)
        c.close()

    def menu_actions_for(self, cover):
        actions = []
        a_mode = QAction("Mosaic mode", self)
        a_mode.setCheckable(True)
        a_mode.setChecked(cover.mode == "mosaic")
        a_mode.triggered.connect(lambda checked: cover.set_mode("mosaic" if checked else "bar"))
        actions.append(a_mode)
        if cover.mode == "bar":
            actions.append(self._slider("Opacity", cover.opacity_pct, 0, 100, cover.set_opacity))
        else:
            actions.append(self._slider("Mosaic intensity", cover.intensity, 1, 100, cover.set_intensity))
        a_lock = QAction("Lock all (click-through)", self)
        a_lock.setCheckable(True)
        a_lock.setChecked(self.locked)
        a_lock.triggered.connect(self.toggle_lock)
        actions.append(a_lock)
        a_del = QAction("Remove this cover", self)
        a_del.triggered.connect(lambda: self.remove_one(cover))
        actions.append(a_del)
        return actions

    def _slider(self, label, value, lo, hi, on_change):
        wa = QWidgetAction(self)
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 4, 8, 4)
        lbl = QLabel(f"{label}: {value}")
        s = QSlider(Qt.Horizontal)
        s.setRange(lo, hi)
        s.setValue(value)
        s.setMinimumWidth(200)

        def upd(val):
            lbl.setText(f"{label}: {val}")
            on_change(val)
        s.valueChanged.connect(upd)
        v.addWidget(lbl)
        v.addWidget(s)
        wa.setDefaultWidget(w)
        return wa


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    if not QSystemTrayIcon.isSystemTrayAvailable():
        sys.stderr.write("System tray not available\n")
        return 1
    ctrl = Controller(app)
    msg = "Right-click tray to add covers. Drag to move, edges to resize."
    if HAS_HOTKEYS:
        msg += " Hotkeys: Ctrl+Alt+H/L/M."
    else:
        msg += " (Install pynput for global hotkeys.)"
    ctrl.tray.showMessage("ScreenCoverDesktop", msg, QSystemTrayIcon.Information, 4000)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
