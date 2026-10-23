from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)


def paint_mark(painter, bounds):
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.translate(bounds.center())
    painter.scale(
        min(bounds.width(), bounds.height()) / 100,
        min(bounds.width(), bounds.height()) / 100,
    )
    fill = QLinearGradient(-40, -40, 40, 40)
    fill.setColorAt(0, QColor("#4d4d4d"))
    fill.setColorAt(1, QColor("#222222"))
    painter.setBrush(fill)
    painter.setPen(QPen(QColor("#666666"), 0.7))
    painter.drawRoundedRect(QRectF(-43, -43, 86, 86), 19, 19)
    path = QPainterPath()
    path.moveTo(-20, 22)
    path.lineTo(-20, -22)
    path.lineTo(20, 22)
    path.lineTo(20, -22)
    pen = QPen(QColor("#f0f0f0"), 7)
    pen.setCapStyle(Qt.PenCapStyle.SquareCap)
    pen.setJoinStyle(Qt.PenJoinStyle.BevelJoin)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(pen)
    painter.drawPath(path)
    painter.restore()


def application_icon():
    icon = QIcon()
    for size in (24, 32, 48, 64, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        paint_mark(painter, QRectF(0, 0, size, size))
        painter.end()
        icon.addPixmap(pixmap)
    return icon
