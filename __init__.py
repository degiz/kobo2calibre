from typing import Optional

from calibre.customize import InterfaceActionBase
from PyQt6.QtWidgets import QWidget


class Kobo2Calibre(InterfaceActionBase):
    """Base class for Calibre plugin."""

    name = "Kobo2Calibre"
    description = "Embed highlights from Kobo device into matching books in Calibre"
    supported_platforms = ["windows", "osx", "linux"]
    author = "Alexander Khizov"
    version = (0, 1, 0)
    minimum_calibre_version = (6, 10, 0)

    actual_plugin = "calibre_plugins.kobo2calibre.plugin:Kobo2CalibrePlugin"

    def is_customizable(self) -> bool:
        """Return True if the plugin has a configuration dialog."""
        return False

    def config_widget(self) -> Optional[QWidget]:
        """Return the configuration widget."""
        return None

    def save_settings(self, _: QWidget) -> None:
        """Save the settings from the config widget."""
        pass
