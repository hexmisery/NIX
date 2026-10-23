from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QWidget
from .paths import assets
from .i18n import tr


class Backdrop(QWidget):
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(QColor(255, 255, 255, 24))
        painter.setBrush(QColor("#15181b"))
        painter.drawRoundedRect(bounds, 18, 18)


class TitleBar(QFrame):
    def __init__(self, window):
        super().__init__()
        self.owner = window
        self.setObjectName("titlebar")
        self.setFixedHeight(32)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 3, 12, 3)
        row.setSpacing(4)
        row.addStretch()
        self.minimize = self.control("−", "Свернуть", window.showMinimized, row)
        self.maximize = self.control(
            "", "Развернуть или восстановить", self.toggle_maximized, row
        )
        self.maximize.setIcon(QIcon(str(assets() / "window-maximize.svg")))
        self.close_button = self.control("×", "Закрыть", window.close, row, True)

    def control(self, text, name, callback, layout, close=False):
        item = QPushButton(text)
        item.setObjectName("closeControl" if close else "windowControl")
        item.setAccessibleName(tr(name))
        item.setToolTip(tr(name))
        item.setFixedSize(36, 28)
        item.clicked.connect(callback)
        layout.addWidget(item)
        return item

    def toggle_maximized(self):
        self.owner.showNormal() if self.owner.isMaximized() else self.owner.showMaximized()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.owner.windowHandle():
            self.owner.windowHandle().startSystemMove()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()
        super().mouseDoubleClickEvent(event)
