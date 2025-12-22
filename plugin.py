from pathlib import Path
from typing import Any, List, Tuple

from calibre.gui2.actions import InterfaceAction  # type: ignore
from calibre.gui2.library.views import DeviceBooksView  # type: ignore
from PyQt6 import QtCore, QtGui, QtWidgets

try:
    # For calibre gui plugin
    from calibre_plugins.kobo2calibre import (  # type: ignore
        converter,
    )
    from calibre_plugins.kobo2calibre import db  # type: ignore
except ImportError:
    # For local calibre debug
    import os
    import sys

    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    import converter  # type: ignore
    import db  # type: ignore


EPUB = "EPUB"
ICON_PATH = "images/icon.png"
HELP_MESSAGE = "Import highlights from the selected books"


class Kobo2CalibreDialog(QtWidgets.QDialog):
    """Main logic of the plugin."""

    def __init__(self, gui, *_: object) -> None:
        """Initialize the dialog."""
        super(Kobo2CalibreDialog, self).__init__(gui)
        self.gui = gui
        self.warnings: List[str] = []
        self.info: List[Any] = []  # Now stores dicts
        self.kepub_format = "new"  # Default value

        # Set dialog properties
        self.setWindowTitle("Kobo2Calibre - Import Highlights")
        self.setMinimumWidth(550)
        self.setMinimumHeight(350)

        # For debugging
        # kobo2calibre.configure_file_logging(None)

        if isinstance(self.gui.current_view(), DeviceBooksView):
            self._abort(
                "Please select books in the calibre library view, not the device view"
            )
            return

        (
            self.to_process_from_kobo,
            self.to_process_from_calibre,
        ) = self._process_selected_rows()
        self._show_info_widget()

    def _abort(self, message: str) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Error icon and message
        error_widget = QtWidgets.QWidget()
        error_layout = QtWidgets.QHBoxLayout(error_widget)
        error_layout.setContentsMargins(0, 0, 0, 0)

        icon_label = QtWidgets.QLabel()
        style = self.style()
        if style:
            icon_label.setPixmap(
                style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MessageBoxWarning)
                .pixmap(32, 32)
            )
        error_layout.addWidget(icon_label)

        message_label = QtWidgets.QLabel(message)
        message_font = QtGui.QFont()
        message_font.setBold(True)
        message_label.setFont(message_font)
        message_label.setWordWrap(True)
        error_layout.addWidget(message_label, 1)

        layout.addWidget(error_widget)

        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok,
            parent=self,
        )
        button_box.accepted.connect(self.accept)
        layout.addWidget(button_box)
        self.setLayout(layout)

    def _show_info_widget(self) -> None:
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Info section
        if self.info:
            info_group = QtWidgets.QGroupBox("📚 Book Information")
            info_group.setStyleSheet(
                """
                QGroupBox {
                    font-weight: bold;
                    font-size: 15px;
                    border: 2px solid #4a90e2;
                    border-radius: 8px;
                    margin-top: 12px;
                    padding-top: 15px;
                    background-color: #f8fbff;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 8px;
                    color: #2c5aa0;
                }
            """
            )
            info_layout = QtWidgets.QVBoxLayout()
            info_layout.setSpacing(12)
            info_layout.setContentsMargins(15, 15, 15, 15)

            for book_info in self.info:
                # Create a container for each book
                book_widget = QtWidgets.QWidget()
                book_layout = QtWidgets.QVBoxLayout(book_widget)
                book_layout.setContentsMargins(0, 0, 0, 0)
                book_layout.setSpacing(6)

                # Book title - using QFont instead of HTML
                title_label = QtWidgets.QLabel(book_info['title'])
                title_font = QtGui.QFont()
                title_font.setPointSize(13)
                title_font.setBold(True)
                title_label.setFont(title_font)
                title_label.setStyleSheet("color: #1a1a1a;")
                title_label.setWordWrap(True)
                title_label.setTextInteractionFlags(
                    QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
                )
                book_layout.addWidget(title_label)

                # Highlights info - using QHBoxLayout with styled labels
                highlights_widget = QtWidgets.QWidget()
                highlights_layout = QtWidgets.QHBoxLayout(highlights_widget)
                highlights_layout.setContentsMargins(10, 0, 0, 0)
                highlights_layout.setSpacing(5)
                
                # "Highlights:" label
                prefix_label = QtWidgets.QLabel("Highlights:")
                prefix_font = QtGui.QFont()
                prefix_font.setPointSize(11)
                prefix_label.setFont(prefix_font)
                prefix_label.setStyleSheet("color: #666;")
                highlights_layout.addWidget(prefix_label)
                
                # Kobo count
                kobo_label = QtWidgets.QLabel(str(book_info['kobo_count']))
                kobo_font = QtGui.QFont()
                kobo_font.setPointSize(11)
                kobo_font.setBold(True)
                kobo_label.setFont(kobo_font)
                kobo_label.setStyleSheet("color: #e74c3c;")
                highlights_layout.addWidget(kobo_label)
                
                # "in Kobo" text
                kobo_text = QtWidgets.QLabel("in Kobo")
                kobo_text.setFont(prefix_font)
                kobo_text.setStyleSheet("color: #666;")
                highlights_layout.addWidget(kobo_text)
                
                # Bullet separator
                bullet_label = QtWidgets.QLabel("•")
                bullet_label.setFont(prefix_font)
                bullet_label.setStyleSheet("color: #666;")
                highlights_layout.addWidget(bullet_label)
                
                # Calibre count
                calibre_label = QtWidgets.QLabel(str(book_info['calibre_count']))
                calibre_font = QtGui.QFont()
                calibre_font.setPointSize(11)
                calibre_font.setBold(True)
                calibre_label.setFont(calibre_font)
                calibre_label.setStyleSheet("color: #27ae60;")
                highlights_layout.addWidget(calibre_label)
                
                # "in Calibre" text
                calibre_text = QtWidgets.QLabel("in Calibre")
                calibre_text.setFont(prefix_font)
                calibre_text.setStyleSheet("color: #666;")
                highlights_layout.addWidget(calibre_text)
                
                highlights_layout.addStretch()
                book_layout.addWidget(highlights_widget)

                info_layout.addWidget(book_widget)

                # Add a subtle separator between books (except for the last one)
                if book_info != self.info[-1]:
                    separator = QtWidgets.QFrame()
                    separator.setFrameShape(QtWidgets.QFrame.Shape.HLine)
                    separator.setStyleSheet("background-color: #e0e0e0; margin: 5px 0;")
                    separator.setMaximumHeight(1)
                    info_layout.addWidget(separator)

            info_group.setLayout(info_layout)
            layout.addWidget(info_group)

        # Warnings section
        if self.warnings:
            warning_group = QtWidgets.QGroupBox("⚠️  Warnings")
            warning_group.setStyleSheet(
                """
                QGroupBox {
                    font-weight: bold;
                    font-size: 15px;
                    border: 2px solid #f39c12;
                    border-radius: 8px;
                    margin-top: 12px;
                    padding-top: 15px;
                    background-color: #fff9e6;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 8px;
                    color: #c87f0a;
                }
            """
            )
            warning_layout = QtWidgets.QVBoxLayout()
            warning_layout.setSpacing(8)
            warning_layout.setContentsMargins(15, 15, 15, 15)

            for warning in self.warnings:
                warning_label = QtWidgets.QLabel(f"• {warning}")
                warning_font = QtGui.QFont()
                warning_font.setPointSize(11)
                warning_label.setFont(warning_font)
                warning_label.setStyleSheet("color: #856404;")
                warning_label.setWordWrap(True)
                warning_label.setTextInteractionFlags(
                    QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
                )
                warning_layout.addWidget(warning_label)

            warning_group.setLayout(warning_layout)
            layout.addWidget(warning_group)

        # Options section
        options_group = QtWidgets.QGroupBox("⚙️  Options")
        options_group.setStyleSheet(
            """
            QGroupBox {
                font-weight: bold;
                font-size: 15px;
                border: 2px solid #95a5a6;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 15px;
                background-color: #f8f9fa;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px;
                color: #5a6c7d;
            }
            QCheckBox {
                font-size: 11pt;
                color: #2c3e50;
            }
        """
        )
        options_layout = QtWidgets.QVBoxLayout()
        options_layout.setContentsMargins(15, 15, 15, 15)

        self.kepub_checkbox = QtWidgets.QCheckBox(
            "Use old KTE plugin format (uncheck for new Calibre kepubify format)"
        )
        self.kepub_checkbox.setChecked(False)  # Default to new format
        self.kepub_checkbox.stateChanged.connect(self._on_kepub_format_changed)
        options_layout.addWidget(self.kepub_checkbox)

        options_group.setLayout(options_layout)
        layout.addWidget(options_group)

        # Spacer
        layout.addStretch()

        # Action section
        buttons = None
        if self.to_process_from_kobo:
            buttons = QtWidgets.QDialogButtonBox(
                QtWidgets.QDialogButtonBox.StandardButton.Ok
                | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
                parent=self,
            )
            ok_button = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
            if ok_button:
                ok_button.setText("Import Highlights")
            buttons.accepted.connect(self._do_import)
            buttons.rejected.connect(self.reject)
        else:
            no_books_label = QtWidgets.QLabel("No books to process")
            no_books_font = QtGui.QFont()
            no_books_font.setPointSize(13)
            no_books_font.setBold(True)
            no_books_label.setFont(no_books_font)
            no_books_label.setStyleSheet("color: #95a5a6;")
            no_books_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(no_books_label)

            buttons = QtWidgets.QDialogButtonBox(
                QtWidgets.QDialogButtonBox.StandardButton.Ok,
                parent=self,
            )
            buttons.accepted.connect(self.accept)

        layout.addWidget(buttons)
        self.setLayout(layout)

    def _on_kepub_format_changed(self, state: int) -> None:
        """Handle checkbox state change."""
        self.kepub_format = "old" if state == 2 else "new"  # Qt.CheckState.Checked == 2

    def _do_import(self) -> None:
        # Use the kepub format from the checkbox
        to_insert_from_kobo = []
        for book, highlights in self.to_process_from_kobo:
            to_insert_from_kobo.extend(
                converter.process_calibre_epub_from_kobo(
                    book[2], book[1], highlights, self.kepub_format
                )
            )
        n_inserted_from_kobo = db.insert_highlights_into_calibre(
            self._calibre_db_path(), to_insert_from_kobo
        )

        to_insert_from_calibre = []
        for book, highlights in self.to_process_from_calibre:
            kobo_lpath = db.get_kobo_content_path_by_book_id(
                self._kobo_mount_prefix(), book[1]
            )
            to_insert_from_calibre.extend(
                converter.process_calibre_epub_from_calibre(
                    book[2], kobo_lpath, highlights
                )
            )
        n_inserted_from_calibre = db.insert_highlights_into_kobo(
            self._kobo_db_path(), to_insert_from_calibre
        )

        self.accept()
        QtWidgets.QMessageBox.information(
            self,
            "Kobo2Calibre",
            f"Inserted {n_inserted_from_kobo} highlights into calibre and "
            f"{n_inserted_from_calibre} highlights into Kobo",
        )

    def _process_selected_rows(self):
        # We're in library view
        calibre_books, books_with_no_epubs = self._get_books_from_selected_rows()

        if books_with_no_epubs:
            self.warnings.append(
                "The following books have no EPUB format and were not processed:\n"
                + ",\n".join(f"    • {book}" for book in books_with_no_epubs)
            )
        elif not calibre_books:
            QtWidgets.QMessageBox.information(
                self,
                "Kobo2Calibre",
                "No books selected",
            )
            return []

        result_from_kobo = []
        result_from_calibre = []
        for book in calibre_books:
            print(f"Processing book: {book}")
            if not book[3]:
                self.warnings.append(
                    f'Book "{book[0]}" has no matching kepub, and was not processed'
                )
                continue
            highlights_from_kobo = db.get_highlights_from_kobo_by_book(
                self._kobo_db_path(), book[3]
            )
            # Store structured info for better formatting
            self.info.append(
                {
                    "title": book[0],
                    "kobo_count": len(highlights_from_kobo),
                    "calibre_count": 0,  # Will be updated below
                }
            )
            result_from_kobo.append((book, highlights_from_kobo))

            # Now process the other way
            highlights_from_calibre = db.get_highlights_from_calibre_by_book_id(
                self._calibre_db_path(), book[1]
            )
            result_from_calibre.append((book, highlights_from_calibre))
            # Update the calibre count in the last info entry
            self.info[-1]["calibre_count"] = len(highlights_from_calibre)

        return result_from_kobo, result_from_calibre

    def _get_books_from_selected_rows(self) -> Tuple[List[Any], List[str]]:
        rows = self.gui.library_view.selectionModel().selectedRows()
        if not rows or len(rows) < 1:
            return ([], [])
        rows = list(map(self.gui.current_view().model().id, rows))

        print(f"Selected rows: {rows}")

        calibre_db = self.gui.library_view.model().db

        result = []
        no_epubs = []
        for id in rows:
            title = calibre_db.get_metadata(id, index_is_id=True).title
            epub_path = calibre_db.format(id, EPUB, as_path=True, index_is_id=True)
            print(f"Book {title} has epub path {epub_path}")
            if not epub_path:
                no_epubs.append(title)
                continue
            result.append((title, id, epub_path, self._get_kobo_content_id(id)))

        return result, no_epubs

    def _get_kobo_content_id(self, book_id: int) -> str:
        paths = []
        for x in ("memory", "card_a"):
            x = getattr(self.gui, x + "_view").model()
            paths += x.paths_for_db_ids([book_id], as_map=True)[book_id]  # type: ignore
        return [r.contentID for r in paths][0] if paths else ""

    def _kobo_db_path(self) -> Path:
        return (
            Path(self.gui.device_manager.connected_device._main_prefix)
            / ".kobo"
            / "KoboReader.sqlite"
        )

    def _kobo_mount_prefix(self) -> Path:
        return Path(self.gui.device_manager.connected_device._main_prefix)

    def _calibre_db_path(self) -> Path:
        return Path(self.gui.library_view.model().db.dbpath)


class Kobo2CalibrePlugin(InterfaceAction):
    """Kobo2Calibre plugin."""

    name = "Kobo2Calibre"
    action_spec = (name, None, HELP_MESSAGE, None)

    def genesis(self) -> None:
        """Load the plugin."""
        # Calibre defines `get_icons` globally, can't import it
        self.qaction.setIcon(
            get_icons(ICON_PATH, self.name)  # type: ignore # noqa: F821
        )
        self.qaction.triggered.connect(self.show_dialog)

    def show_dialog(self) -> None:
        """Show the dialog."""
        base_plugin_object = self.interface_action_base_plugin
        # Some more Calibre magic with `do_user_config`
        do_user_config = base_plugin_object.do_user_config
        self.d = Kobo2CalibreDialog(
            self.gui,
            self.qaction.icon(),
            do_user_config,
        )
        self.d.show()

    def apply_settings(self) -> None:
        """Apply settings."""
        pass

    def shutdown(self) -> None:
        """Shutdown the plugin."""
        pass
