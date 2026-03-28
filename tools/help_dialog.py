# -*- coding: utf-8 -*-
from typing import Optional

from qgis.PyQt import QtWidgets


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
        self.setWindowTitle(str(title or "도움말"))
        self.setMinimumSize(700, 520)

        layout = QtWidgets.QVBoxLayout(self)

        hint_text = str(
            get_plugin_config_value(
                "plugin",
                "ui",
                "help_dialog",
                "hint_text",
                default="이 도움말은 검색하고 복사할 수 있습니다.",
            ) or ""
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
                ) or "도움말 검색..."
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
        self.browser.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)
        self.browser.setWordWrapMode(QtGui.QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.browser.setHorizontalScrollBarPolicy(QtWidgets.QAbstractScrollArea.ScrollBarAsNeeded)
        self.browser.setVerticalScrollBarPolicy(QtWidgets.QAbstractScrollArea.ScrollBarAsNeeded)
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
