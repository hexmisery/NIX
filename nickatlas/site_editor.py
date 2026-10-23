import asyncio
from dataclasses import replace
import json
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

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

from .customsites import (
    PRESETS,
    preset,
    read_sites,
    rule_data,
    validate_rule,
    write_sites,
)
from .engine import check_site
from .models import Site, STATUS, canonical, username
from .network import Network


class SiteEditor(QDialog):
    def __init__(self, parent, rule=None):
        super().__init__(parent)
        self.setWindowTitle("Свой сайт")
        self.resize(620, 620)
        self.rule = None
        self.worker = None
        self.close_after = False
        self.setStyleSheet(parent.styleSheet())
        outer = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)
        self.title_input = QLineEdit()
        self.profile_input = QLineEdit()
        self.profile_input.setPlaceholderText("https://example.org/users/{username}")
        self.probe_input = QLineEdit()
        self.probe_input.setPlaceholderText("Пусто: проверять адрес профиля")
        self.base_input = QLineEdit()
        self.base_input.setPlaceholderText("https://forum.example.org")
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(list(PRESETS))
        self.preset_button = QPushButton("Заполнить шаблон")
        self.preset_button.clicked.connect(self.fill_preset)
        row = QHBoxLayout()
        row.addWidget(self.preset_combo)
        row.addWidget(self.base_input, 1)
        row.addWidget(self.preset_button)
        form.addRow("Готовый адаптер", row)
        form.addRow("Название", self.title_input)
        form.addRow("Адрес профиля", self.profile_input)
        form.addRow("Адрес проверки", self.probe_input)
        self.kind_combo = QComboBox()
        for label, value in (
            ("Маркеры в ответе", "message"),
            ("HTTP-код, требует ручной проверки", "status_code"),
            ("Точный ник и ID в JSON", "json_user"),
        ):
            self.kind_combo.addItem(label, value)
        form.addRow("Метод", self.kind_combo)
        self.json_path = QLineEdit()
        self.json_path.setPlaceholderText(
            "user для Discourse; пусто для объекта в корне"
        )
        form.addRow("Путь к профилю в JSON", self.json_path)
        self.present = QPlainTextEdit()
        self.absent = QPlainTextEdit()
        for edit in (self.present, self.absent):
            edit.setMaximumHeight(68)
            edit.setPlaceholderText("Каждый маркер с новой строки")
        form.addRow("Профиль найден", self.present)
        form.addRow("Профиль отсутствует", self.absent)
        codes = QHBoxLayout()
        self.code_found = QSpinBox()
        self.code_missing = QSpinBox()
        for box, value in ((self.code_found, 200), (self.code_missing, 404)):
            box.setRange(100, 599)
            box.setValue(value)
        codes.addWidget(QLabel("Найден"))
        codes.addWidget(self.code_found)
        codes.addWidget(QLabel("Отсутствует"))
        codes.addWidget(self.code_missing)
        form.addRow("HTTP-коды", codes)
        self.category_input = QComboBox()
        self.category_input.setEditable(True)
        self.category_input.addItems(
            ["Свои сайты", "Форумы", "Социальные сети", "Разработка", "Игры"]
        )
        form.addRow("Категория", self.category_input)
        self.known_input = QLineEdit()
        form.addRow("Известный ник", self.known_input)
        self.enabled = QCheckBox("Участвует в поиске")
        self.enabled.setChecked(True)
        form.addRow(self.enabled)
        fields = QWidget()
        fields.setLayout(form)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(fields)
        outer.addWidget(scroll, 1)
        self.test_account = QLineEdit()
        self.test_account.setPlaceholderText("Ник для пробной проверки")
        self.test_button = QPushButton("Проверить правило")
        self.test_button.clicked.connect(self.test_rule)
        test_row = QHBoxLayout()
        test_row.addWidget(self.test_account, 1)
        test_row.addWidget(self.test_button)
        outer.addLayout(test_row)
        self.status = QLabel(
            "Укажи известный профиль, чтобы проверить правило и отсеять заглушки."
        )
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        outer.addWidget(self.buttons)
        self.engine = rule.engine if rule else ""
        if rule:
            self.title_input.setText(rule.site)
            self.profile_input.setText(rule.profile)
            self.probe_input.setText(rule.probe if rule.probe != rule.profile else "")
            self.kind_combo.setCurrentIndex(self.kind_combo.findData(rule.kind))
            self.json_path.setText(rule.json_path)
            self.present.setPlainText("\n".join(rule.present))
            self.absent.setPlainText("\n".join(rule.absent))
            self.code_found.setValue(rule.exists_code)
            self.code_missing.setValue(rule.missing_code)
            self.category_input.setCurrentText(rule.category)
            self.known_input.setText(rule.known)
            self.test_account.setText(rule.known)
            self.enabled.setChecked(not rule.disabled)

    def value(self):
        return validate_rule(
            {
                "site": self.title_input.text().strip(),
                "profile": self.profile_input.text().strip(),
                "probe": self.probe_input.text().strip(),
                "kind": self.kind_combo.currentData(),
                "present": [
                    x.strip()
                    for x in self.present.toPlainText().splitlines()
                    if x.strip()
                ],
                "absent": [
                    x.strip()
                    for x in self.absent.toPlainText().splitlines()
                    if x.strip()
                ],
                "exists_code": self.code_found.value(),
                "missing_code": self.code_missing.value(),
                "category": self.category_input.rawText().strip(),
                "known": self.known_input.text().strip(),
                "disabled": not self.enabled.isChecked(),
                "json_path": self.json_path.text().strip(),
                "engine": self.engine,
            }
        )

    def fill_preset(self):
        try:
            data = preset(
                self.preset_combo.currentText(),
                self.base_input.text(),
                self.title_input.text() or self.base_input.text(),
            )
            self.profile_input.setText(data["profile"])
            self.probe_input.setText(data["probe"])
            self.kind_combo.setCurrentIndex(self.kind_combo.findData(data["kind"]))
            self.json_path.setText(data["json_path"])
            self.category_input.setCurrentText(data["category"])
            self.engine = data["engine"]
            self.status.setText(
                "Шаблон заполнен. Проверь на существующем нике перед использованием."
            )
        except ValueError as exc:
            self.status.setText(str(exc))

    def save(self):
        if self.worker and self.worker.isRunning():
            return
        try:
            self.rule = self.value()
            write_sites_preview = json.dumps(rule_data(self.rule))
            if len(write_sites_preview) > 20000:
                raise ValueError("Слишком большое правило")
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.accept()

    def test_rule(self):
        if self.worker and self.worker.isRunning():
            return
        try:
            rule = self.value()
            account = username(self.test_account.text() or self.known_input.text())
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        from .ui import Job

        async def run(job):
            async with Network(concurrency=2, timeout=12) as net:
                result = await check_site(net, Site([rule]), account, True)
                return {"result": result}

        self.worker = Job(run, self)
        self.worker.completed.connect(self.test_done)
        self.worker.failed.connect(self.status.setText)
        self.worker.finished.connect(self.worker_done)
        self.test_button.setEnabled(False)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(False)
        self.status.setText("Проверяется указанный ник и контрольный случайный ник…")
        self.worker.start()

    def test_done(self, data):
        result = data.get("result")
        if result:
            self.status.setText(
                f"{STATUS[result.status]} · HTTP {result.http}\n{result.reason}"
            )
        else:
            self.status.setText("Проверка остановлена")

    def worker_done(self):
        self.test_button.setEnabled(True)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(True)
        if self.close_after:
            QTimer.singleShot(0, self.reject)

    def reject(self):
        if self.worker and self.worker.isRunning():
            self.close_after = True
            self.worker.cancel.set()
            return
        super().reject()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.close_after = True
            self.worker.cancel.set()
            event.ignore()
            return
        super().closeEvent(event)


class CustomSitesDialog(QDialog):
    def __init__(self, parent, path):
        super().__init__(parent)
        self.path = Path(path)
        self.rules = read_sites(self.path)
        self.setWindowTitle("Мои сайты")
        self.resize(640, 440)
        self.setStyleSheet(parent.styleSheet())
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self.edit)
        layout.addWidget(self.list, 1)
        row = QHBoxLayout()
        for text, action in (
            ("Добавить", self.add),
            ("Изменить", self.edit),
            ("Вкл. / выкл.", self.toggle),
            ("Удалить", self.remove),
        ):
            item = QPushButton(text)
            item.clicked.connect(action)
            row.addWidget(item)
        layout.addLayout(row)
        transfer = QHBoxLayout()
        for text, action in (
            ("Импорт JSON", self.import_file),
            ("Экспорт JSON", self.export_file),
        ):
            item = QPushButton(text)
            item.clicked.connect(action)
            transfer.addWidget(item)
        transfer.addStretch()
        layout.addLayout(transfer)
        self.status = QLabel(
            "Свои правила сохраняются отдельно от обновляемых каталогов."
        )
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.button(QDialogButtonBox.StandardButton.Close).setText("Закрыть")
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        self.refresh()

    def refresh(self):
        selected = self.list.currentRow()
        self.list.clear()
        for r in self.rules:
            self.list.addItem(
                (tr("Выкл. · ") if r.disabled else "") + r.site + "   " + r.profile
            )
        if self.rules:
            self.list.setCurrentRow(max(0, min(selected, len(self.rules) - 1)))

    def commit(self, rules):
        try:
            write_sites(self.path, rules)
        except (OSError, ValueError) as exc:
            self.status.setText(str(exc))
            return False
        self.rules = rules
        self.refresh()
        return True

    def add(self):
        dialog = SiteEditor(self)
        if dialog.exec():
            if canonical(dialog.rule.profile) in {
                canonical(r.profile) for r in self.rules
            }:
                self.status.setText(
                    "Такой адрес уже есть в своём каталоге. Измени существующую запись."
                )
                return
            self.commit(self.rules + [dialog.rule])

    def edit(self, *_):
        index = self.list.currentRow()
        if not 0 <= index < len(self.rules):
            return
        dialog = SiteEditor(self, self.rules[index])
        if dialog.exec():
            updated = list(self.rules)
            updated[index] = dialog.rule
            self.commit(updated)

    def toggle(self):
        index = self.list.currentRow()
        if 0 <= index < len(self.rules):
            updated = list(self.rules)
            updated[index] = replace(
                updated[index], disabled=not updated[index].disabled
            )
            self.commit(updated)

    def remove(self):
        index = self.list.currentRow()
        if (
            0 <= index < len(self.rules)
            and QMessageBox.question(
                self, "Удалить сайт", f"Удалить правило {self.rules[index].site}?"
            )
            == QMessageBox.StandardButton.Yes
        ):
            self.commit([r for i, r in enumerate(self.rules) if i != index])

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Импорт своих сайтов", "", "JSON (*.json)"
        )
        if not path:
            return
        try:
            incoming = read_sites(path)
            known = {canonical(r.profile) for r in self.rules}
            new = [r for r in incoming if canonical(r.profile) not in known]
            if self.commit(self.rules + new):
                self.status.setText(
                    f"Добавлено {len(new)}. Совпадающие адреса сохранены без замены."
                )
        except (OSError, ValueError) as exc:
            self.status.setText(str(exc))

    def export_file(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт своих сайтов", "nix-sites.json", "JSON (*.json)"
        )
        if path:
            try:
                write_sites(Path(path), self.rules)
                self.status.setText("Каталог экспортирован")
            except (OSError, ValueError) as exc:
                self.status.setText(str(exc))
