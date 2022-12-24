from calibre.gui2.actions import InterfaceAction

try:
    from calibre_plugins.kobo2calibre.main import Kobo2CalibreDialog  # type: ignore
except ImportError:
    from main import Kobo2CalibreDialog

from PyQt5.Qt import QIcon


class Kobo2CalibrePlugin(InterfaceAction):
    name = "Kobo2Calibre"
    action_spec = ("Kobo2Calibre", None, "Kobo2Calibre", None)

    def genesis(self) -> None:
        # This method is called once per plugin, do initial setup here
        self.qaction.setIcon(QIcon("images/icon.png"))
        self.qaction.triggered.connect(self.show_dialog)

    def show_dialog(self) -> None:
        base_plugin_object = self.interface_action_base_plugin
        do_user_config = base_plugin_object.do_user_config
        self.d = Kobo2CalibreDialog(
            self.gui,
            self.qaction.icon(),
            do_user_config,
        )
        self.d.show()

    def apply_settings(self) -> None:
        pass

    def shutdown(self) -> None:
        pass
