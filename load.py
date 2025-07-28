import sys

from companion import CAPIData
import fleetcarriercargo
import threading
import os


this = sys.modules[__name__]


def plugin_start3(plugin_dir: str) -> str:
    return os.path.basename(os.path.dirname(__file__))


def capi_fleetcarrier(data: CAPIData):
    """
    We have new data on our Fleet Carrier triggered by the logs.
    This function must return quickly, so sync_to_capi runs in a separate thread.
    """

    def worker():
        fleetcarriercargo.FleetCarrier().sync_to_capi(data)

    threading.Thread(target=worker, daemon=True).start()


def cmdr_data(data: CAPIData, is_beta: bool) -> None:
    pass


def journal_entry(cmdr, is_beta, system, station, entry, state):
    # TODO: track FC docking, if docked to the own one track market events and "sudden" cargo disappered, updated cargo.
    pass


def plugin_prefs(parent, cmdr, is_beta):
    return None


def prefs_changed(cmdr, is_beta):
    pass


def plugin_app(parent):
    # this.ui = MainUi()
    # this.plugin.setup_ui(this.ui)
    # ui = this.ui.plugin_app(parent)
    # this.plugin.update_display()
    # return ui
    return None
