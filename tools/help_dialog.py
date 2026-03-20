# -*- coding: utf-8 -*-
from typing import Optional

from qgis.PyQt import QtGui, QtWidgets

from .config import get_plugin_config_value
from .i18n import apply_language, tr


class ArchToolkitHelpDialog(QtWidgets.QDialog):
    def __init__(
        self,
        *,
        title: str,
        html: str,
        plugin_dir: Optional[str] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(tr(str(title or "도움말")))
        min_width = int(get_plugin_config_value("plugin", "ui", "help_dialog", "min_width", default=760) or 760)
        min_height = int(get_plugin_config_value("plugin", "ui", "help_dialog", "min_height", default=560) or 560)
        self.setMinimumSize(max(640, min_width), max(420, min_height))

        layout = QtWidgets.QVBoxLayout(self)

        hint_text = str(
            get_plugin_config_value(
                "plugin",
                "ui",
                "help_dialog",
                "hint_text",
                default="이 도움말은 검색하고 복사할 수 있습니다.",
            )
            or ""
        ).strip()
        if hint_text:
            self.lblHint = QtWidgets.QLabel(tr(hint_text), self)
            self.lblHint.setWordWrap(True)
            self.lblHint.setStyleSheet(
                "background:#f1f8e9; border:1px solid #dcedc8; color:#355724; "
                "padding:8px; border-radius:4px;"
            )
            layout.addWidget(self.lblHint)

        search_row = QtWidgets.QHBoxLayout()
        self.txtSearch = QtWidgets.QLineEdit(self)
        self.txtSearch.setPlaceholderText(
            tr(
                get_plugin_config_value(
                    "plugin",
                    "ui",
                    "help_dialog",
                    "search_placeholder",
                    default="도움말 검색...",
                )
                or "도움말 검색..."
            )
        )
        self.btnSearchNext = QtWidgets.QPushButton(tr("다음"), self)
        self.btnSearchPrev = QtWidgets.QPushButton(tr("이전"), self)
        self.btnSearchClear = QtWidgets.QPushButton(tr("지우기"), self)
        self.lblSearchStatus = QtWidgets.QLabel("", self)
        self.lblSearchStatus.setStyleSheet("color:#455a64;")
        self.txtSearch.returnPressed.connect(self._find_next)
        self.btnSearchNext.clicked.connect(self._find_next)
        self.btnSearchPrev.clicked.connect(self._find_prev)
        self.btnSearchClear.clicked.connect(self._clear_search)
        search_row.addWidget(self.txtSearch, 1)
        search_row.addWidget(self.btnSearchPrev)
        search_row.addWidget(self.btnSearchNext)
        search_row.addWidget(self.btnSearchClear)
        layout.addLayout(search_row)
        layout.addWidget(self.lblSearchStatus)

        self.browser = QtWidgets.QTextBrowser(self)
        # Keep help self-contained: don't launch the user's browser from inside QGIS.
        self.browser.setOpenExternalLinks(False)
        try:
            self.browser.setHtml(str(html or ""))
        except Exception:
            self.browser.setPlainText(str(html or ""))
        layout.addWidget(self.browser, 1)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)

        self.btnCopy = QtWidgets.QPushButton(tr("복사"), self)
        self.btnClose = QtWidgets.QPushButton(tr("닫기"), self)

        self.btnCopy.clicked.connect(self._copy_text)
        self.btnClose.clicked.connect(self.accept)

        btn_row.addWidget(self.btnCopy)
        btn_row.addWidget(self.btnClose)
        layout.addLayout(btn_row)
        apply_language(self)

    def _find_text(self, *, backward: bool = False):
        text = str(self.txtSearch.text() or "").strip()
        if not text:
            self.lblSearchStatus.setText(tr("검색어를 입력하면 도움말 안에서 바로 찾을 수 있습니다."))
            return

        flags = QtGui.QTextDocument.FindBackward if backward else QtGui.QTextDocument.FindFlags()
        found = False
        try:
            found = bool(self.browser.find(text, flags))
        except Exception:
            found = False

        if not found:
            try:
                cursor = self.browser.textCursor()
                cursor.movePosition(
                    QtGui.QTextCursor.End if backward else QtGui.QTextCursor.Start
                )
                self.browser.setTextCursor(cursor)
                found = bool(self.browser.find(text, flags))
            except Exception:
                found = False

        if found:
            self.lblSearchStatus.setText(tr("'{text}' 검색 결과로 이동했습니다.", text=text))
        else:
            self.lblSearchStatus.setText(tr("'{text}' 검색 결과를 찾지 못했습니다.", text=text))

    def _find_next(self):
        self._find_text(backward=False)

    def _find_prev(self):
        self._find_text(backward=True)

    def _clear_search(self):
        try:
            self.txtSearch.clear()
        except Exception:
            pass
        self.lblSearchStatus.setText("")

    def _copy_text(self):
        try:
            QtWidgets.QApplication.clipboard().setText(self.browser.toPlainText())
        except Exception:
            pass


def show_help_dialog(*, parent, title: str, html: str, plugin_dir: Optional[str] = None) -> None:
    # plugin_dir is currently unused (kept for compatibility with callers).
    dlg = ArchToolkitHelpDialog(title=title, html=html, plugin_dir=plugin_dir, parent=parent)
    try:
        dlg.exec_()
    except Exception:
        try:
            dlg.exec()
        except Exception:
            dlg.show()
