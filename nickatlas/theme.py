STYLE = """
QWidget {background:transparent;color:#ededed;font-family:'Onest';font-size:12px;}
QMenu {background:#24282c;border:1px solid #43494e;border-radius:10px;padding:6px;}
QMenu::item {padding:9px 14px;border-radius:5px;}
QMenu::item:selected {background:#383e43;}
QDialog,QMessageBox {background:#202429;}
QLabel {background:transparent;}
QLabel#brand {font-size:16px;font-weight:700;color:#f2f2f2;}
QLabel#heading {font-size:23px;font-weight:600;}
QLabel#muted {color:#b3b3b3;}
QLabel#detailTitle {font-size:19px;font-weight:600;}
QLabel#sectionTitle {font-size:15px;font-weight:600;}
QFrame#sidebar {background:rgba(0,0,0,65);border:0;border-right:1px solid rgba(255,255,255,10);}
QFrame#sidebar QPushButton {min-width:48px;max-width:48px;min-height:42px;max-height:42px;padding:0;border-radius:10px;}
QFrame#workspace {background:transparent;border:0;}
QFrame#detail {background:rgba(255,255,255,11);border:1px solid rgba(255,255,255,22);border-radius:14px;}
QFrame#searchPanel {background:rgba(255,255,255,12);border:1px solid rgba(255,255,255,18);border-radius:12px;}
QFrame#resultsPanel {background:rgba(255,255,255,7);border:1px solid rgba(255,255,255,12);border-radius:12px;}
QFrame#titlebar {background:transparent;}
QPushButton {min-height:18px;border:1px solid rgba(255,255,255,34);border-radius:7px;padding:7px 11px;background:rgba(255,255,255,8);font-weight:500;}
QPushButton:hover {background:rgba(255,255,255,20);border-color:rgba(255,255,255,68);}
QPushButton:pressed {background:rgba(255,255,255,30);}
QPushButton:disabled {color:#858585;background:rgba(255,255,255,3);border-color:rgba(255,255,255,12);}
QPushButton#primary {background:#e6e6e6;color:#202020;border:1px solid #e6e6e6;font-weight:600;}
QPushButton#primary:hover {background:#ffffff;}
QPushButton#primary:disabled {background:#555555;color:#a0a0a0;border-color:#555555;}
QPushButton#nav {text-align:center;background:transparent;border:0;border-radius:10px;padding:0;color:#ababab;font-size:12px;}
QPushButton#nav:hover {color:#ffffff;background:rgba(255,255,255,5);}
QPushButton#nav:checked {background:rgba(255,255,255,22);color:#ffffff;font-weight:500;}
QPushButton#quiet {text-align:center;background:transparent;border:0;padding:0;color:#ababab;}
QPushButton#quiet:hover {color:#ffffff;}
QPushButton#newSearch {background:rgba(255,255,255,7);border:1px solid rgba(255,255,255,24);text-align:center;padding:0;}
QPushButton#newSearch:hover {background:rgba(255,255,255,15);border-color:rgba(255,255,255,55);}
QPushButton#coverage {background:transparent;border:0;color:#bdbdbd;font-size:12px;padding:0;}
QPushButton#coverage:hover {color:#ffffff;}
QPushButton#windowControl {border:0;border-radius:5px;background:transparent;padding:2px;min-height:22px;color:#bbbbbb;font-size:17px;}
QPushButton#windowControl:hover {background:rgba(255,255,255,16);color:#ffffff;}
QPushButton#closeControl {border:0;border-radius:5px;background:transparent;padding:2px;min-height:22px;color:#bbbbbb;font-size:20px;}
QPushButton#closeControl:hover {background:#984a4a;color:#ffffff;}
QLineEdit,QComboBox,QSpinBox,QTextEdit,QPlainTextEdit {background:rgba(255,255,255,6);border:1px solid rgba(255,255,255,27);border-radius:7px;padding:9px;selection-background-color:#626262;selection-color:white;}
QLineEdit:focus,QTextEdit:focus {border-color:rgba(255,255,255,105);}
QLineEdit#query {background:transparent;border:0;font-size:21px;padding:5px 0;}
QComboBox {padding:7px 27px 7px 10px;min-height:18px;}
QComboBox::drop-down {border:0;width:22px;}
QComboBox QAbstractItemView {background:#363636;border:1px solid #666666;selection-background-color:#565656;}
QLineEdit#filter {background:transparent;border:0;border-bottom:1px solid rgba(255,255,255,30);border-radius:0;padding:9px 0;}
QListWidget {background:transparent;border:0;outline:0;}
QListWidget::item {padding:11px 8px;border:0;border-radius:5px;color:#b9b9b9;}
QListWidget::item:selected {background:rgba(255,255,255,11);color:#ffffff;}
QTableView {background:transparent;alternate-background-color:transparent;border:0;selection-background-color:rgba(255,255,255,14);selection-color:#ffffff;outline:0;}
QTableView::item {padding:8px 6px;border:0;border-bottom:1px solid rgba(255,255,255,9);}
QHeaderView {background:transparent;}
QHeaderView::section {background:transparent;color:#aaaaaa;padding:8px 6px;border:0;border-bottom:1px solid rgba(255,255,255,25);font-weight:400;}
QTableCornerButton::section {background:transparent;border:0;}
QProgressBar {background:rgba(255,255,255,18);border:0;border-radius:1px;}
QProgressBar::chunk {background:#cccccc;border-radius:1px;}
QScrollArea {background:transparent;border:0;}
QScrollBar:vertical {background:transparent;width:6px;margin:0;}
QScrollBar::handle:vertical {background:rgba(255,255,255,50);min-height:30px;border-radius:3px;}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {height:0;}
QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical {background:transparent;}
QScrollBar:horizontal {background:transparent;height:6px;}
QScrollBar::handle:horizontal {background:rgba(255,255,255,50);min-width:30px;border-radius:3px;}
QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal {width:0;}
QScrollBar::add-page:horizontal,QScrollBar::sub-page:horizontal {background:transparent;}
QToolTip {background:#3d3d3d;color:#eeeeee;border:1px solid #666666;padding:6px;}
QCheckBox {spacing:8px;color:#c3c3c3;}
QCheckBox::indicator {width:13px;height:13px;border:1px solid #888888;border-radius:3px;background:rgba(255,255,255,4);}
QCheckBox::indicator:checked {background:#dddddd;border-color:#dddddd;}
QCheckBox::indicator:disabled {border-color:#666666;background:transparent;}
QSplitter::handle {background:transparent;width:18px;}
QSizeGrip {background:transparent;width:14px;height:14px;}
"""

from .paths import assets

STYLE += """
QComboBox::down-arrow {image: url('%s');width:12px;height:12px;}
QCheckBox::indicator:checked {image: url('%s');}
""" % ((assets() / "chevron.svg").as_posix(), (assets() / "check.svg").as_posix())

STYLE += """
QTreeWidget {background:transparent;border:0;}
QTreeWidget::item {padding:9px;border-bottom:1px solid rgba(255,255,255,12);}
QTreeWidget::item:selected {background:rgba(255,255,255,14);}
"""
