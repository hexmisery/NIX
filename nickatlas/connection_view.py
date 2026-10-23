from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)
from PySide6.QtCore import QUrl

from .i18n import (
    tr,
    set_language,
    Label as QLabel,
    Button as QPushButton,
    CheckBox as QCheckBox,
    ComboBox as QComboBox,
    LineEdit as QLineEdit,
    TextEdit as QTextEdit,
    PlainTextEdit as QPlainTextEdit,
    Dialog as QDialog,
    MessageBox as QMessageBox,
    FileDialog as QFileDialog,
    TreeWidget as QTreeWidget,
    TreeItem as QTreeWidgetItem,
)

from .connections import connection_rows
from .network import safe_url


class ConnectionsDialog(QDialog):
    def __init__(self, parent, results):
        super().__init__(parent)
        self.owner = parent
        self.rows = connection_rows(results)
        self.setWindowTitle("Связки профилей")
        self.resize(820, 460)
        self.setStyleSheet(parent.styleSheet())
        layout = QVBoxLayout(self)
        self.filter = QComboBox()
        self.filter.addItems(
            [
                "Все ссылки",
                "На профили из этого запуска",
                "Только взаимные ссылки",
                "Общие внешние ссылки",
            ]
        )
        self.filter.currentIndexChanged.connect(self.refresh)
        layout.addWidget(self.filter)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Источник", "Ссылка", "Основание", "Совпадение"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(False)
        self.tree.setColumnWidth(0, 150)
        self.tree.setColumnWidth(1, 270)
        self.tree.setColumnWidth(2, 175)
        self.tree.itemDoubleClicked.connect(self.open_target)
        layout.addWidget(self.tree, 1)
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.summary)
        row = QHBoxLayout()
        open_button = QPushButton("Открыть ссылку")
        open_button.clicked.connect(self.open_target)
        row.addWidget(open_button)
        source_button = QPushButton("Показать исходный профиль")
        source_button.clicked.connect(self.show_source)
        row.addWidget(source_button)
        row.addStretch()
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.button(QDialogButtonBox.StandardButton.Close).setText("Закрыть")
        close.rejected.connect(self.reject)
        row.addWidget(close)
        layout.addLayout(row)
        self.refresh()
        self.live_timer = QTimer(self)
        self.live_timer.timeout.connect(self.refresh_live)
        self.live_timer.start(500)
        self.last_signature = None

    def refresh_live(self):
        signature = tuple(
            (r.url, r.status, tuple(link.get("url", "") for link in r.links))
            for r in self.owner.results
        )
        if signature != self.last_signature:
            self.last_signature = signature
            self.rows = connection_rows(self.owner.results)
            self.refresh()

    def refresh(self, *_):
        self.tree.clear()
        shown = 0
        for row in self.rows:
            if (
                self.filter.currentIndex() == 1
                and not row["matched"]
                or self.filter.currentIndex() == 2
                and not row["reciprocal"]
            ):
                continue
            if self.filter.currentIndex() == 3 and row.get("shared_count", 0) < 2:
                continue
            state = (
                "Взаимная ссылка"
                if row["reciprocal"]
                else "Профиль найден"
                if row["matched"]
                else "Внешняя ссылка"
            )
            if row.get("shared_count", 0) > 1:
                state += f" · общая у {row['shared_count']} профилей"
            if row["source_status"] == "possible":
                state += " · источник не подтверждён"
            item = QTreeWidgetItem([row["site"], row["target"], row["evidence"], state])
            item.setData(0, Qt.ItemDataRole.UserRole, row)
            item.setToolTip(0, row["source"])
            item.setToolTip(1, row["target"])
            self.tree.addTopLevelItem(item)
            shown += 1
        self.summary.setText(f"{shown} {tr('Links')}")
        if self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))

    def open_target(self, *_):
        item = self.tree.currentItem()
        if item:
            row = item.data(0, Qt.ItemDataRole.UserRole)
            try:
                safe_url(row["target"])
            except ValueError:
                return
            QDesktopServices.openUrl(QUrl(row["target"]))

    def show_source(self):
        item = self.tree.currentItem()
        if not item:
            return
        row = item.data(0, Qt.ItemDataRole.UserRole)
        self.owner.filter_text.clear()
        self.owner.status_filter.setCurrentIndex(
            self.owner.status_filter.findData("all")
        )
        self.owner.navigate(0)
        for index, result in enumerate(self.owner.model.rows):
            if result.url == row["source"]:
                self.owner.table.selectRow(index)
                self.accept()
                break
