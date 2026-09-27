"""
region_selector.py - lets the user drag a rectangle on the screen (Step 8).

How it works:
  1. Take a picture of every monitor FIRST (we "freeze" the screen).
  2. Cover each monitor with a borderless full-screen window that shows that
     frozen picture, slightly darkened, with a crosshair mouse pointer.
  3. The user drags a rectangle. That part is shown bright, with its size.
  4. On mouse release we cut exactly that rectangle out of the frozen picture
     and hand it to the main window. The full-screen pictures are thrown away,
     so only the selected region is ever kept (and only in memory).

Esc or right-click cancels.

About "logical" vs "real" pixels:
  With Windows display scaling (e.g. 125%), Qt measures the screen in logical
  pixels (1536 wide) while the picture has real pixels (1920 wide). The mouse
  gives us logical positions, so we multiply by the ratio (1.25) before cutting.
"""

import logging

from PySide6.QtCore import QObject, QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QImage, QPainter, QPen, QPixmap, QScreen
from PySide6.QtWidgets import QWidget

log = logging.getLogger(__name__)

MIN_SELECTION = 8  # logical pixels; a smaller drag is treated as an accidental click
DIM_COLOR = QColor(0, 0, 0, 120)  # black at ~50% opacity darkens the unselected area
BORDER_COLOR = QColor(0, 170, 255)  # bright blue selection border
HINT_TEXT = "Drag to select the question   |   Esc or right-click to cancel"


class RegionOverlay(QWidget):
    """One borderless full-screen window covering ONE monitor."""

    selected = Signal(QImage)  # emitted with the cropped region (real pixels)
    cancelled = Signal()  # emitted on Esc or right-click

    def __init__(self, screen: QScreen, frozen: QPixmap) -> None:
        # Frameless: no title bar.  StaysOnTop: above every other window.
        # Tool: no extra button appears in the taskbar.
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self._frozen = frozen
        # Real pixels per logical pixel on this monitor (1.25 at 125% scaling).
        # We measure it from the picture itself, so it is always correct.
        self._ratio = frozen.width() / max(1, screen.geometry().width())
        # Tell Qt the picture's ratio, so drawing it at (0, 0) fills the
        # monitor exactly instead of being drawn 25% too big.
        self._frozen.setDevicePixelRatio(self._ratio)

        self._start: QPoint | None = None  # where the mouse button went down
        self._selection = QRect()  # the current rectangle (logical pixels)

        self.setCursor(Qt.CursorShape.CrossCursor)  # the "+" pointer
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # so it can receive the Esc key
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)  # free memory when closed
        self.setScreen(screen)
        self.setGeometry(screen.geometry())  # cover exactly this monitor

    # ---------- Converting and cropping ----------

    def _to_real_pixels(self, rect: QRect) -> QRect:
        """Convert a logical rectangle to a rectangle in the picture's real pixels."""
        r = self._ratio
        scaled = QRectF(rect.x() * r, rect.y() * r, rect.width() * r, rect.height() * r)
        # toAlignedRect() rounds outwards to whole pixels; intersected() makes
        # sure rounding can never go past the edge of the picture.
        return scaled.toAlignedRect().intersected(QRect(0, 0, self._frozen.width(), self._frozen.height()))

    def crop(self, rect: QRect) -> QImage:
        """Cut the given logical rectangle out of the frozen picture."""
        image = self._frozen.copy(self._to_real_pixels(rect)).toImage()
        image.setDevicePixelRatio(1.0)  # later steps just want plain pixels
        return image

    # ---------- Mouse and keyboard ----------

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self.cancelled.emit()
        elif event.button() == Qt.MouseButton.LeftButton:
            self._start = event.position().toPoint()
            self._selection = QRect()
            self.update()  # ask Qt to repaint (it calls paintEvent)

    def mouseMoveEvent(self, event) -> None:
        if self._start is None:  # mouse moving without a button held: ignore
            return
        pos = event.position().toPoint()
        # Build the rectangle from its two corners. min() and abs() make it the
        # same whichever way you drag (e.g. bottom-right to top-left).
        left = min(self._start.x(), pos.x())
        top = min(self._start.y(), pos.y())
        width = abs(pos.x() - self._start.x())
        height = abs(pos.y() - self._start.y())
        self._selection = QRect(left, top, width, height).intersected(self.rect())  # stay on this monitor
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._start is None:
            return
        self._start = None
        if self._selection.width() < MIN_SELECTION or self._selection.height() < MIN_SELECTION:
            # Too small - probably a click. Stay in selection mode.
            self._selection = QRect()
            self.update()
            return
        self.selected.emit(self.crop(self._selection))

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()

    # ---------- Drawing ----------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._frozen)  # 1. the frozen screen
        painter.fillRect(self.rect(), DIM_COLOR)  # 2. darken all of it

        if self._selection.isEmpty():
            self._draw_hint(painter)
        else:
            # 3. Draw the frozen screen again, but only inside the selection
            #    (the "clip"), so the selected part looks bright again.
            painter.save()
            painter.setClipRect(self._selection)
            painter.drawPixmap(0, 0, self._frozen)
            painter.restore()
            painter.setPen(QPen(BORDER_COLOR, 2))
            painter.drawRect(self._selection)
            self._draw_size_label(painter)
        painter.end()

    def _draw_hint(self, painter: QPainter) -> None:
        """Instruction text in a dark box at the top-centre of the monitor."""
        painter.setFont(QFont("Segoe UI", 12))
        text_rect = painter.fontMetrics().boundingRect(HINT_TEXT).adjusted(-16, -10, 16, 10)
        text_rect.moveCenter(QPoint(self.width() // 2, 40))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(20, 20, 20, 220))
        painter.drawRoundedRect(text_rect, 8, 8)
        painter.setPen(Qt.GlobalColor.white)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, HINT_TEXT)

    def _draw_size_label(self, painter: QPainter) -> None:
        """Show the selection size in real pixels just above the rectangle."""
        real = self._to_real_pixels(self._selection)
        text = f"{real.width()} x {real.height()} px"
        painter.setFont(QFont("Segoe UI", 9))
        label = painter.fontMetrics().boundingRect(text).adjusted(-6, -3, 6, 3)
        label.moveBottomLeft(self._selection.topLeft() + QPoint(0, -4))
        if label.top() < 0:  # no room above (selection touches the top edge): put it inside
            label.moveTopLeft(self._selection.topLeft() + QPoint(4, 4))
        painter.fillRect(label, BORDER_COLOR)
        painter.setPen(Qt.GlobalColor.white)
        painter.drawText(label, Qt.AlignmentFlag.AlignCenter, text)


class RegionSelector(QObject):
    """Puts an overlay on every monitor and reports what the user selected."""

    region_selected = Signal(QImage)  # the user finished a selection
    cancelled = Signal()  # the user pressed Esc / right-click
    failed = Signal(str)  # the screen could not be captured (message for the user)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._overlays: list[RegionOverlay] = []

    def start(self) -> None:
        """Freeze every monitor and show the selection overlays."""
        # Grab ALL monitors before showing ANY overlay, so no overlay can
        # appear inside another monitor's picture.
        for screen in QGuiApplication.screens():
            frozen = screen.grabWindow(0)  # 0 = the whole monitor, not one window
            if frozen.isNull():
                log.warning("Could not capture screen %s", screen.name())
                continue
            log.info(
                "Froze screen %s: %dx%d real px, scaling %.0f%%",
                screen.name(), frozen.width(), frozen.height(), screen.devicePixelRatio() * 100,
            )
            overlay = RegionOverlay(screen, frozen)
            overlay.selected.connect(self._on_selected)
            overlay.cancelled.connect(self._on_cancelled)
            self._overlays.append(overlay)

        if not self._overlays:
            self.failed.emit(
                "ScreenQA could not take a picture of the screen.\n\n"
                "This can happen while a protected screen is shown (for example a "
                "Windows security prompt). Close it and try again."
            )
            return

        for overlay in self._overlays:
            overlay.showFullScreen()

        # Give keyboard focus to the overlay under the mouse, so Esc works at once.
        active = QGuiApplication.screenAt(QCursor.pos())
        for overlay in self._overlays:
            if overlay.screen() == active:
                overlay.raise_()
                overlay.activateWindow()
                overlay.setFocus()

    def _on_selected(self, image: QImage) -> None:
        log.info("Region selected: %dx%d px", image.width(), image.height())
        self._close_overlays()
        self.region_selected.emit(image)

    def _on_cancelled(self) -> None:
        log.info("Region selection cancelled")
        self._close_overlays()
        self.cancelled.emit()

    def _close_overlays(self) -> None:
        # Closing deletes each overlay (WA_DeleteOnClose), and with it the
        # full-screen picture. Only the cropped region survives.
        for overlay in self._overlays:
            overlay.close()
        self._overlays.clear()
