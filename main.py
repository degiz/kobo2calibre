from PyQt5 import QtWidgets


class Kobo2CalibreDialog(QtWidgets.QDialog):
    def __init__(self, gui, icon, do_user_config):
        super(Kobo2CalibreDialog, self).__init__(gui)
