import sys
from tkinter import Tk

from companion import CAPIData
import fleetcarriercargo
from _logger import logger
from _logger import plugin_name
from typing import Any
from typing import Dict, Optional

this = sys.modules[__name__]


def plugin_start3(plugin_dir: str) -> str:
    logger.debug("Loading plugin")
    return plugin_name


def capi_fleetcarrier(data: CAPIData):
    """
    We have new data on our Fleet Carrier triggered by the logs.
    """

    fleetcarriercargo.FleetCarrierCargo.sync_to_capi(data)


def cmdr_data(data: CAPIData, is_beta: bool) -> None:
    pass


def journal_entry(
    cmdr: str,
    is_beta: bool,
    system: Optional[str],
    station: Optional[str],
    entry: Dict[str, Any],
    state: Dict[str, Any],
) -> None:
    from _cargo_monitor import CargoMonitor

    CargoMonitor.process_journal_entry(cmdr, is_beta, system, station, entry, state)


# def plugin_prefs(parent, cmdr, is_beta):
#     return nb.Frame()


# def prefs_changed(cmdr, is_beta):
#     pass


def plugin_app(parent: Any):
    fleetcarriercargo.FleetCarrierCargo.set_gui_root_once(parent.winfo_toplevel())
    fleetcarriercargo.FleetCarrierCargo.load_or_update()
    return None
