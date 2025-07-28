import sys

from companion import CAPIData
import fleetcarriercargo
from _logger import logger
from _logger import plugin_name
import myNotebook as nb

this = sys.modules[__name__]
__fleet_carrier_tracker: fleetcarriercargo.FleetCarrier


def plugin_start3(plugin_dir: str) -> str:
    logger.debug("Loading plugin")
    __fleet_carrier_tracker = fleetcarriercargo.FleetCarrier()
    return plugin_name


def capi_fleetcarrier(data: CAPIData):
    """
    We have new data on our Fleet Carrier triggered by the logs.
    """

    fleetcarriercargo.FleetCarrier().sync_to_capi(data)


def cmdr_data(data: CAPIData, is_beta: bool) -> None:
    pass


def journal_entry(cmdr, is_beta, system, station, entry, state):
    # TODO: track FC docking, if docked to the own one track market events and "sudden" cargo disappered, updated cargo.
    # Note, use thread ?
    pass


# def plugin_prefs(parent, cmdr, is_beta):
#     return nb.Frame()


# def prefs_changed(cmdr, is_beta):
#     pass


def plugin_app(parent):
    # this.ui = MainUi()
    # this.plugin.setup_ui(this.ui)
    # ui = this.ui.plugin_app(parent)
    # this.plugin.update_display()
    # return ui
    return None
