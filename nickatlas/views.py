from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QListWidget,
    QProgressBar,
    QScrollArea,
    QSizeGrip,
    QSplitter,
    QStackedWidget,
    QTableView,
    QTextEdit,
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

from .ui import RowsModel, button, configure_table, label
from .visuals import Backdrop, TitleBar
from .paths import assets


def build_window(w):
    w.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    root = Backdrop()
    w.setCentralWidget(root)
    shell = QVBoxLayout(root)
    shell.setContentsMargins(1, 1, 1, 1)
    shell.setSpacing(0)
    body = QHBoxLayout()
    body.setSpacing(0)
    body.setContentsMargins(0, 0, 0, 0)
    w.sidebar = QFrame()
    w.sidebar.setObjectName("sidebar")
    w.sidebar.setFixedWidth(72)
    side = QVBoxLayout(w.sidebar)
    side.setContentsMargins(10, 18, 10, 12)
    side.setSpacing(10)
    brand_row = QHBoxLayout()
    brand_row.setContentsMargins(0, 0, 0, 0)
    brand_row.setSpacing(8)
    w.brand_label = label("NIX", "brand")
    brand_row.addWidget(w.brand_label, 0, Qt.AlignmentFlag.AlignCenter)
    side.addLayout(brand_row)
    side.addSpacing(16)
    w.new_search_button = button("Новый поиск", w.new_search)
    w.new_search_button.setObjectName("newSearch")
    w.new_search_button.setIcon(QIcon(str(assets() / "nav-plus.svg")))
    w.new_search_button.setIconSize(QSize(16, 16))
    w.new_search_button.setToolTip(tr("Новый поиск") + " · Ctrl+N / Cmd+N")
    w.new_search_button.setAccessibleName(tr("Новый поиск"))
    w.new_search_button.setText("")
    w.new_search_button.setFixedSize(48, 40)
    side.addWidget(w.new_search_button)
    side.addSpacing(14)
    w.search_nav = button("Поиск", lambda: w.navigate(0))
    w.sources_nav = button("Источники", lambda: w.navigate(1))
    w.harvest_nav = button("Сбор сайтов", lambda: w.navigate(2))
    for b, icon in (
        (w.search_nav, "nav-search.svg"),
        (w.sources_nav, "nav-sources.svg"),
        (w.harvest_nav, "nav-discovery.svg"),
    ):
        b.setObjectName("nav")
        b.setCheckable(True)
        b.setIcon(QIcon(str(assets() / icon)))
        b.setIconSize(QSize(18, 18))
        b.setToolTip(b.text())
        b.setAccessibleName(b.text())
        b.setText("")
        b.setFixedSize(48, 42)
        side.addWidget(b)
    w.search_nav.setChecked(True)
    side.addSpacing(14)
    w.history_button = button("", w.show_history)
    w.history_button.setObjectName("nav")
    w.history_button.setIcon(QIcon(str(assets() / "nav-history.svg")))
    w.history_button.setToolTip(tr("Недавние"))
    w.history_button.setAccessibleName(tr("Недавние"))
    w.history_button.setFixedSize(48, 42)
    side.addWidget(w.history_button)
    w.history = QListWidget(w.sidebar)
    w.history.setAccessibleName("История поисков")
    w.history.itemClicked.connect(w.load_history)
    w.history.hide()
    side.addStretch()
    w.delete_button = button("Удалить запуск", w.delete_history)
    w.delete_button.setObjectName("quiet")
    w.delete_button.setIcon(QIcon(str(assets() / "nav-trash.svg")))
    w.delete_button.setIconSize(QSize(16, 16))
    w.delete_button.setParent(w.sidebar)
    w.delete_button.hide()
    for text, callback, icon in (
        ("Настройки", w.settings, "nav-settings.svg"),
        ("О программе", w.about, "nav-info.svg"),
    ):
        item = button(text, callback)
        if text == "Настройки":
            w.settings_button = item
        item.setObjectName("quiet")
        item.setIcon(QIcon(str(assets() / icon)))
        item.setIconSize(QSize(16, 16))
        item.setToolTip(item.text())
        item.setAccessibleName(item.text())
        item.setText("")
        item.setFixedSize(48, 42)
        side.addWidget(item)
    body.addWidget(w.sidebar)
    workspace = QFrame()
    workspace.setObjectName("workspace")
    content = QVBoxLayout(workspace)
    content.setContentsMargins(0, 0, 0, 0)
    content.setSpacing(0)
    w.titlebar = TitleBar(w)
    content.addWidget(w.titlebar)
    w.stack = QStackedWidget()
    content.addWidget(w.stack, 1)
    grip_row = QHBoxLayout()
    grip_row.setContentsMargins(0, 0, 3, 2)
    grip_row.addStretch()
    w.resize_grip = QSizeGrip(w)
    grip_row.addWidget(w.resize_grip)
    content.addLayout(grip_row)
    body.addWidget(workspace, 1)
    shell.addLayout(body)
    build_search(w)
    build_sources(w)
    build_harvest(w)
    w.focus_shortcut = QShortcut(QKeySequence.StandardKey.Find, w)
    w.focus_shortcut.activated.connect(w.focus_search)
    w.new_shortcut = QShortcut(QKeySequence.StandardKey.New, w)
    w.new_shortcut.activated.connect(w.new_search)


def build_search(w):
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(20, 10, 20, 12)
    layout.setSpacing(12)
    heading = QHBoxLayout()
    w.search_heading = label("Поиск профилей", "heading")
    heading.addWidget(w.search_heading)
    heading.addStretch()
    w.coverage_button = button("", lambda: w.navigate(1))
    w.coverage_button.setObjectName("coverage")
    heading.addWidget(w.coverage_button, 0, Qt.AlignmentFlag.AlignBottom)
    layout.addLayout(heading)

    layout.addSpacing(3)

    panel = QFrame()
    w.search_panel = panel
    panel.setObjectName("searchPanel")
    pl = QVBoxLayout(panel)
    pl.setContentsMargins(14, 10, 14, 10)
    pl.setSpacing(10)
    search = QHBoxLayout()
    search.setSpacing(17)
    w.query = QLineEdit()
    w.query.setObjectName("query")
    w.query.setPlaceholderText("Введи ник или @ник")
    w.query.setMaxLength(65)
    w.query.setAccessibleName("Ник для поиска")
    w.query.returnPressed.connect(w.start_scan)
    search.addWidget(w.query, 1)
    w.start_button = button("Найти профили", w.start_scan, True)
    w.start_button.setMinimumHeight(36)
    search.addWidget(w.start_button)
    w.stop_button = button("Остановить", w.stop)
    w.stop_button.hide()
    search.addWidget(w.stop_button)
    pl.addLayout(search)
    options = QHBoxLayout()
    options.setSpacing(12)
    w.mode = QComboBox()
    w.mode.addItems(["Быстро · 100", "Полный каталог"])
    w.mode.setFixedWidth(165)
    w.mode.setAccessibleName("Режим поиска")
    options.addWidget(w.mode)
    w.category = QComboBox()
    w.category.addItem("Все категории")
    w.category.setMinimumWidth(150)
    w.category.setMaximumWidth(215)
    w.category.setAccessibleName("Категория сайтов")
    w.category.setParent(panel)
    w.category.hide()
    w.provider = QComboBox()
    w.provider.addItem("Все каталоги", "")
    w.provider.addItem("Blackbird", "WhatsMyName")
    w.provider.setToolTip(
        "Blackbird использует каталог WhatsMyName. Дубли сайтов объединяются."
    )
    w.provider.addItem("Maigret", "Maigret")
    w.provider.addItem("Sherlock", "Sherlock")
    w.provider.addItem("Автосбор", "Автосбор")
    w.provider.setCurrentIndex(max(0, w.provider.findData(w.selected_source)))
    w.provider.setMaximumWidth(210)
    w.provider.setAccessibleName("Каталог поиска")
    w.provider.setParent(panel)
    w.provider.hide()
    w.verify = QCheckBox("Контроль совпадений")
    w.verify.setChecked(True)
    w.verify.setToolTip("Дополнительная проверка со случайным ником.")
    w.verify.setParent(panel)
    w.verify.hide()
    w.scope = QComboBox()
    for title, key in (
        ("Россия", "ru"),
        ("Все регионы", "all"),
        ("СНГ и Украина", "cis"),
        ("США и международные", "world"),
    ):
        w.scope.addItem(title, key)
    w.scope.setCurrentIndex(max(0, w.scope.findData(w.search_priority)))
    options.addWidget(w.scope)
    options.addStretch()
    pl.addLayout(options)
    layout.addWidget(panel)
    w.progress = QProgressBar()
    w.progress.setTextVisible(False)
    w.progress.setRange(0, 100)
    w.progress.setValue(0)
    w.progress.setFixedHeight(2)
    layout.addWidget(w.progress)
    w.status_line = label("", "muted")
    layout.addWidget(w.status_line)

    surface = QFrame()
    surface.setObjectName("resultsPanel")
    results_layout = QVBoxLayout(surface)
    results_layout.setContentsMargins(16, 6, 16, 12)
    results_layout.setSpacing(8)
    results_heading = QHBoxLayout()
    w.results_heading = label("Результаты", "sectionTitle")
    results_heading.addWidget(w.results_heading)
    results_heading.addStretch()
    w.links_button = button("Связки", w.show_connections)
    w.links_button.setObjectName("quiet")
    w.links_button.setEnabled(False)
    results_heading.addWidget(w.links_button)
    w.export_button = button("Экспорт", w.export)
    w.export_button.setObjectName("quiet")
    w.export_button.setEnabled(False)
    results_heading.addWidget(w.export_button)
    results_layout.addLayout(results_heading)
    filters = QHBoxLayout()
    filters.setSpacing(24)
    w.filter_text = QLineEdit()
    w.filter_text.setObjectName("filter")
    w.filter_text.setPlaceholderText("Найти сайт в результатах")
    w.filter_text.textChanged.connect(w.refilter)
    filters.addWidget(w.filter_text, 1)
    w.status_filter = QComboBox()
    for text, key in [
        ("Найдены профили", "found"),
        ("Все результаты", "all"),
        ("Нужна проверка", "possible"),
        ("Блокировки", "blocked"),
        ("Ошибки", "error"),
        ("Не найдены", "missing"),
        ("Избранное", "favorites"),
        ("Ошибочные", "rejected"),
    ]:
        w.status_filter.addItem(text, key)
    w.status_filter.setMinimumWidth(135)
    w.status_filter.currentIndexChanged.connect(w.refilter)
    filters.addWidget(w.status_filter)
    results_layout.addLayout(filters)

    w.result_stack = QStackedWidget()
    blank = QWidget()
    bl = QVBoxLayout(blank)
    bl.setContentsMargins(30, 20, 30, 20)
    bl.addStretch()
    w.no_results_title = label("Результатов пока нет", "detailTitle")
    w.no_results_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    bl.addWidget(w.no_results_title)
    w.no_results_message = label("Введи ник, чтобы начать поиск.", "muted")
    w.no_results_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
    bl.addWidget(w.no_results_message)
    bl.addStretch()
    w.result_stack.addWidget(blank)
    w.result_split = QSplitter()
    w.table = QTableView()
    w.model = RowsModel()
    w.table.setModel(w.model)
    configure_table(w.table)
    w.table.verticalHeader().setDefaultSectionSize(36)
    for i, size in enumerate((160, 165, 270)):
        w.table.setColumnWidth(i, size)
    w.table.selectionModel().currentRowChanged.connect(w.select_result)
    w.table.doubleClicked.connect(lambda _: w.open_profile())
    w.result_split.addWidget(w.table)
    build_detail(w)
    w.result_split.addWidget(w.detail_scroll)
    w.result_split.setSizes([650, 280])
    w.result_stack.addWidget(w.result_split)
    results_layout.addWidget(w.result_stack, 1)
    layout.addWidget(surface, 1)
    w.empty = label("", "muted")
    w.empty.setWordWrap(True)
    w.empty.hide()
    layout.addWidget(w.empty)
    w.set_detail_enabled(False)
    w.stack.addWidget(page)


def build_detail(w):
    w.detail = QFrame()
    w.detail.setObjectName("detail")
    w.detail_scroll = QScrollArea()
    w.detail_scroll.setWidgetResizable(True)
    w.detail_scroll.setFrameShape(QFrame.Shape.NoFrame)
    w.detail_scroll.setMinimumWidth(215)
    w.detail_scroll.setMaximumWidth(260)
    w.detail_scroll.setWidget(w.detail)
    dl = QVBoxLayout(w.detail)
    dl.setContentsMargins(12, 14, 12, 14)
    dl.setSpacing(10)
    w.detail_title = label("Профиль", "detailTitle")
    w.detail_title.setWordWrap(True)
    dl.addWidget(w.detail_title)
    w.detail_info = label("", "muted")
    w.detail_info.setWordWrap(True)
    w.detail_info.setMinimumHeight(70)
    w.detail_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    dl.addWidget(w.detail_info)
    w.open_button = button("Открыть профиль", w.open_profile)
    dl.addWidget(w.open_button)
    w.favorite = QCheckBox("В избранное")
    w.rejected = QCheckBox("Ложное совпадение")
    for checkbox in (w.favorite, w.rejected):
        checkbox.toggled.connect(w.save_annotation)
        dl.addWidget(checkbox)
    dl.addSpacing(6)
    dl.addWidget(label("Заметка", "sectionTitle"))
    w.note = QTextEdit()
    w.note.setPlaceholderText("Что удалось проверить")
    w.note.setMinimumHeight(82)
    w.note.setMaximumHeight(130)
    w.note.setAcceptRichText(False)
    dl.addWidget(w.note)
    w.save_note_button = button("Сохранить заметку", w.save_annotation)
    dl.addWidget(w.save_note_button)
    dl.addStretch()


def build_sources(w):
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(20, 10, 20, 12)
    layout.setSpacing(12)
    layout.addWidget(label("Источники поиска", "heading"))
    w.catalog_info = label("")
    w.catalog_info.setWordWrap(True)
    layout.addWidget(w.catalog_info)
    actions = QHBoxLayout()
    w.update_button = button("Обновить каталоги", w.update_catalog, True)
    w.health_button = button("Проверить 10 источников", w.check_health)
    w.rollback_button = button("Откатить", w.rollback_catalog)
    w.rollback_button.hide()
    for b in (w.update_button, w.health_button):
        actions.addWidget(b)
    w.source_stop = button("Остановить", w.stop)
    w.source_stop.hide()
    actions.addWidget(w.source_stop)
    actions.addStretch()
    layout.addLayout(actions)
    custom_actions = QHBoxLayout()
    w.manage_sites_button = button("Мои сайты", w.manage_sites)
    w.discover_button = button("Сбор сайтов", lambda: w.navigate(2))
    w.collect_button = button("Вставить свои адреса", w.collect_sites)
    w.forum_search_button = button("Поиск по форумам", w.search_forums)
    w.discover_button.hide()
    w.forum_search_button.hide()
    for item in (w.manage_sites_button, w.collect_button):
        custom_actions.addWidget(item)
    w.import_catalog_button = button("Import", lambda: w.transfer_catalog(True))
    w.export_catalog_button = button("Export", w.transfer_catalog)
    custom_actions.addWidget(w.import_catalog_button)
    custom_actions.addWidget(w.export_catalog_button)
    custom_actions.addStretch()
    layout.addLayout(custom_actions)
    w.source_status = label("", "muted")
    w.source_status.setWordWrap(True)
    layout.addWidget(w.source_status)
    w.catalog_search = QLineEdit()
    w.catalog_search.setObjectName("filter")
    w.catalog_search.setPlaceholderText("Найти сайт или каталог")
    w.catalog_search.textChanged.connect(w.filter_catalog)
    catalog_filters = QHBoxLayout()
    catalog_filters.addWidget(w.catalog_search, 1)
    w.catalog_filter = QComboBox()
    w.catalog_filter.addItems(["Все источники", "Свои сайты", "Форумы"])
    w.catalog_filter.currentIndexChanged.connect(w.filter_catalog)
    catalog_filters.addWidget(w.catalog_filter)
    layout.addLayout(catalog_filters)
    w.catalog_table = QTableView()
    configure_table(w.catalog_table)
    w.catalog_model = RowsModel(True)
    w.catalog_table.setModel(w.catalog_model)
    for i, size in enumerate((180, 180, 230)):
        w.catalog_table.setColumnWidth(i, size)
    layout.addWidget(w.catalog_table, 1)
    w.stack.addWidget(page)


def build_harvest(w):
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(20, 10, 20, 12)
    layout.setSpacing(18)
    layout.addWidget(label("Сбор сайтов", "heading"))
    row = QHBoxLayout()
    w.harvest_start = button("Начать сбор", w.start_harvest, True)
    w.harvest_stop = button("Остановить сбор", w.stop)
    w.harvest_stop.setEnabled(False)
    w.harvest_budget = QComboBox()
    for count in (20, 60, 100, 200):
        w.harvest_budget.addItem(f"{count} доменов за цикл", count)
    w.harvest_budget.setCurrentIndex(1)
    row.addWidget(w.harvest_start)
    row.addWidget(w.harvest_stop)
    row.addWidget(w.harvest_budget)
    row.addStretch()
    layout.addLayout(row)
    options = QHBoxLayout()
    w.harvest_continuous = QComboBox()
    w.harvest_continuous.addItem("До остановки", True)
    w.harvest_continuous.addItem("Один цикл", False)
    w.harvest_continuous.setAccessibleName("Режим сбора")
    options.addWidget(label("Режим"))
    options.addWidget(w.harvest_continuous)
    w.harvest_region = QComboBox()
    from .regions import PRIORITIES

    for key, title in PRIORITIES.items():
        w.harvest_region.addItem(title, key)
    w.harvest_region.setCurrentIndex(max(0, w.harvest_region.findData("ru")))
    w.harvest_region.setToolTip("")
    options.addWidget(label("Приоритет"))
    options.addWidget(w.harvest_region)
    options.addStretch()
    layout.addLayout(options)
    w.harvest_status = label("Ready")
    w.harvest_status.setWordWrap(True)
    layout.addWidget(w.harvest_status)
    w.harvest_log = QTextEdit()
    w.harvest_log.setReadOnly(True)
    w.harvest_log.document().setMaximumBlockCount(400)
    layout.addWidget(w.harvest_log, 1)
    w.stack.addWidget(page)
