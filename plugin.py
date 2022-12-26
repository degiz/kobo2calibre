from pathlib import Path
from typing import Any, List, Tuple

from calibre.gui2.actions import InterfaceAction
from calibre.gui2.library.views import DeviceBooksView
from PyQt6 import QtWidgets

try:
    # For calibre gui plugin
    from calibre_plugins.kobo2calibre import (
        converter,  # pyright: reportMissingImports=false
    )
    from calibre_plugins.kobo2calibre import db  # pyright: reportMissingImports=false
except ImportError:
    # For cli
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
        self.warnings = []
        self.info = []

        # For debugging
        # kobo2calibre.configure_file_logging(None)

        if isinstance(self.gui.current_view(), DeviceBooksView):
            self._abort(
                "Please select books in the calibre library view, not the device view"
            )
            return

        self.to_process = self._process_selected_rows()
        self._show_info_widget()

    def _abort(self, message: str) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel(message))
        layout.addWidget(
            QtWidgets.QDialogButtonBox(
                QtWidgets.QDialogButtonBox.StandardButton.Ok,
                accepted=self.accept,
                parent=self,
            )
        )
        self.setLayout(layout)

    def _show_info_widget(self) -> None:
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(QtWidgets.QLabel("Info:"))
        for info in self.info:
            layout.addWidget(QtWidgets.QLabel(f"• {info}"))
        if self.warnings:
            layout.addWidget(QtWidgets.QLabel("Warnings:"))
            for warning in self.warnings:
                layout.addWidget(QtWidgets.QLabel(f"• {warning}"))
        buttons = None
        if self.to_process:
            layout.addWidget(QtWidgets.QLabel("\nProceed?"))
            buttons = QtWidgets.QDialogButtonBox(
                QtWidgets.QDialogButtonBox.StandardButton.Ok
                | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
                accepted=self._do_import,
                rejected=self.reject,
                parent=self,
            )
        else:
            layout.addWidget(QtWidgets.QLabel("\nNo books to process"))
            buttons = QtWidgets.QDialogButtonBox(
                QtWidgets.QDialogButtonBox.StandardButton.Ok,
                accepted=self.accept,
                parent=self,
            )
        layout.addWidget(buttons)
        self.setLayout(layout)

    def _do_import(self) -> None:
        to_insert = []
        for book, highlights in self.to_process:
            to_insert.extend(
                converter.process_calibre_epub(book[2], book[1], highlights)
            )
        n_inserted = db.insert_highlights_into_calibre(
            self._calibre_db_path(), to_insert
        )
        self.accept()
        QtWidgets.QMessageBox.information(
            self,
            "Kobo2Calibre",
            f"Inserted {n_inserted} highlights into calibre",
        )

    def _process_selected_rows(self) -> List[Tuple[Any, Any]]:

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

        result = []
        for book in calibre_books:
            if not book[3]:
                self.warnings.append(
                    f'Book "{book[0]}" has no matching kepub, and was not processed'
                )
                continue
            highlights = db.get_highlights_from_kobo_by_book(
                self._kobo_db_path(), book[3]
            )
            self.info.append(f'Book "{book[0]}" has {len(highlights)} highlights')
            result.append((book, highlights))

        return result

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
