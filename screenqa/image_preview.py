"""
image_preview.py - a box that shows the captured region, scaled to fit (Step 8).
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy

EMPTY_STYLE = "border: 1px dashed gray; color: gray;"
FILLED_STYLE = "border: 1px solid gray;"


class ImagePreview(QLabel):
    """A label that shows an image as large as fits, keeping its shape."""

    def __init__(self, placeholder: str) -> None:
        super().__init__(placeholder)
        self._placeholder = placeholder
        self._image: QImage | None = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(200, 160)
        # "Ignored" means: don't let the picture's size push the window bigger.
        # The label simply uses whatever space the layout gives it.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setStyleSheet(EMPTY_STYLE)

    def set_image(self, image: QImage) -> None:
        """Show a new image."""
        self._image = image
        self.setStyleSheet(FILLED_STYLE)
        self.setToolTip(f"Selected region: {image.width()} x {image.height()} px (kept in memory only)")
        self._refresh()

    def clear_image(self) -> None:
        """Go back to the placeholder text."""
        self._image = None
        self.setPixmap(QPixmap())
        self.setText(self._placeholder)
        self.setStyleSheet(EMPTY_STYLE)
        self.setToolTip("")

    def resizeEvent(self, event) -> None:
        """Qt calls this whenever the box changes size; re-scale the picture."""
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        if self._image is None or self._image.isNull():
            return
        # On a 125% screen the box has 1.25 real pixels per logical pixel.
        # Scaling to the REAL size keeps the preview sharp instead of blurry.
        dpr = self.devicePixelRatioF()
        target = self.contentsRect().size() * dpr
        pixmap = QPixmap.fromImage(self._image)
        if pixmap.width() > target.width() or pixmap.height() > target.height():
            # Shrink to fit, keeping the width:height shape. Small captures are
            # never enlarged, because enlarging only makes them blurry.
            pixmap = pixmap.scaled(
                target, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
        pixmap.setDevicePixelRatio(dpr)
        self.setPixmap(pixmap)
