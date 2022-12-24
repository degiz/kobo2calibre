from calibre.customize import InterfaceActionBase


class Kobo2Calibre(InterfaceActionBase):
    name = "Kobo2Calibre"
    description = "Embed highlights from Kobo device into matching books in Calibre"
    supported_platforms = ["windows", "osx", "linux"]
    author = "Alexander Khizov"
    version = (0, 0, 1)
    minimum_calibre_version = (6, 10, 0)

    actual_plugin = "calibre_plugins.kobo2calibre.ui:Kobo2CalibrePlugin"

    def is_customizable(self) -> bool:
        return False

    def config_widget(self):  # type: ignore
        return None

    def save_settings(self, config_widget) -> None:  # type: ignore
        pass

    def load_icon(self):  # type: ignore
        return None
