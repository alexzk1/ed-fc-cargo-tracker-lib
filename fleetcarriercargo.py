# Portions of this code are based on the following source:
# Repository: https://github.com/karolnowacki/edmc-colonisation-plugin.git
# Branch: develop
# Source files: colonization/*


import datetime
import json
from typing import Any, Self
from os import path
from companion import CAPIData, session, Session


class FleetCarrierCargo:
    """
    Class to manage the cargo state of a Fleet Carrier in Elite Dangerous.

    Responsible for storing, updating, and saving cargo information,
    as well as synchronizing with the Companion API and game journal events.

    Attributes:
        cargo (dict): A dictionary with commodity names as keys and their quantities as values.
        last_sync (str | None): Timestamp of the last synchronization with the Companion API.
        storage_path (str): File path for saving and loading cargo state.
    """

    def __init__(self) -> None:
        """
        Initializes the cargo tracker.

        Args:
            storage_path (str): Path to the JSON file for loading and saving state.
        """
        self.cargo: dict[str, int] = {}
        self.last_sync: str | None = None
        self.call_sign: str | None = None
        self.file_path: str | None = None
        self.auto_save: bool = False

    def load_local(self, file_path: str, auto_save: bool = False) -> None:
        """
        Loads the cargo state from a JSON file at `storage_path`.

        If the file does not exist, initializes with an empty cargo dictionary.
        """
        self.file_path = file_path
        self.auto_save = auto_save
        if path.isfile(file_path):
            with open(file_path, "r", encoding="utf-8") as file:
                data = json.load(file)
            self.cargo = data.get("cargo", {})
            self.last_sync = data.get("lastSync", None)
            self.call_sign = data.get("callSign", None)

    def save_local(self, file_path: str | None = None) -> None:
        """
        Saves the current cargo state to a JSON file at `storage_path`.

        If no path is provided and auto-save is enabled, uses the stored path.
        """
        if file_path is None and self.auto_save:
            file_path = self.file_path
        if file_path is None:
            return
        with open(file_path, "w", encoding="utf-8") as file:
            json.dump(
                self,
                file,
                ensure_ascii=False,
                indent=4,
                cls=FleetCarrierCargoEncoder,
                sort_keys=True,
            )

    def load_data_from_frontiers(self) -> Self | None:
        if session.state != Session.STATE_OK:
            return

        carrier = session.requests_session.get(
            session.capi_host_for_galaxy() + session.FRONTIER_CAPI_PATH_FLEETCARRIER
        )
        data: CAPIData = carrier.json()

        self.call_sign = data["name"]["callsign"]
        if not self.call_sign:
            return None
        self.last_sync = (
            datetime.datetime.now(datetime.timezone.utc)
            .replace(microsecond=0)
            .isoformat()
        )

        self.cargo = {}
        for c in data["cargo"]:
            cn = c["commodity"].lower()
            if cn in self.cargo:
                self.cargo[cn] += c["qty"]
            else:
                self.cargo[cn] = c["qty"]
        self.save_local()
        return self

    def get_commodity(self, commodity: str) -> int:
        return self.cargo.get(commodity, 0)

    def add_commodity(self, commodity: str, qty: int) -> int:
        if commodity in self.cargo:
            self.cargo[commodity] += qty
        else:
            self.cargo[commodity] = qty
        self.save_local()
        return self.cargo[commodity]

    def remove_commodity(self, commodity: str, qty: int) -> int:
        if commodity in self.cargo:
            self.cargo[commodity] -= qty
            if self.cargo[commodity] < 0:
                self.cargo[commodity] = 0
        else:
            self.cargo[commodity] = 0
        self.save_local()
        return self.cargo[commodity]


class FleetCarrierCargoEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, FleetCarrierCargo):
            return o.__dict__
        return super().default(o)
