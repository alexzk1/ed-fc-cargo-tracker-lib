# Portions of this code are based on the following source:
# Repository: https://github.com/karolnowacki/edmc-colonisation-plugin.git
# Branch: develop
# Source files: colonization/*

import datetime
import json
import threading
from typing import Any, Optional

from cargo_tally import CargoKey, CargoTally
from cargo_signals import InventoryCallback, SignalCargoWasChanged
from watchable_cargo_tally import WatchableCargoTally

from tkinter import Tk
from companion import CAPIData, session, Session
from config import config
from _logger import logger
import time


class FleetCarrierCargo:
    """
    Data about carrier's cargo.
    This is thread-safe singltone.
    All plugins will share the same instance of this class as CMDR can have only 1 carrier.
    """

    _json_config_name: str = "edmc_fleet_carrier_cargo_lib"
    _instance = None
    _instance_lock = threading.Lock()
    _updates_lock = threading.Lock()

    # Lock inside _cargo should be used to access those 3 fields.
    _cargo: WatchableCargoTally = WatchableCargoTally()
    _last_sync: str | None = None
    _call_sign: str | None = None

    @staticmethod
    def is_sync_stale(max_age_seconds: int = 3600) -> bool:
        """
        Checks whether the synchronization is stale.

        :param max_age_seconds: Maximum allowed data age in seconds (default is 1 hour).
        :return: True if the last synchronization time is older than max_age_seconds.
        """

        last_sync_str: Optional[str] = None

        def locker(cargo: Any):
            nonlocal last_sync_str
            last_sync_str = FleetCarrierCargo._last_sync

        FleetCarrierCargo._cargo.inventory(locker)
        try:
            if last_sync_str is None or last_sync_str == "":
                return True
            last_sync_dt = datetime.datetime.fromisoformat(last_sync_str)
            now = datetime.datetime.now(datetime.timezone.utc)
            delta = now - last_sync_dt
            return delta.total_seconds() > max_age_seconds
        except Exception:
            return True

    @staticmethod
    def add_on_cargo_change_handler(handler: SignalCargoWasChanged):
        """
        Installs your handler of the "cargo changed" event.
        Note, you cannot un-install it.
        """
        FleetCarrierCargo._cargo.add_on_cargo_change_handler(handler=handler)

    @staticmethod
    def set_gui_root_once(root: Tk):
        """
        Internal method.
        Do not use it directly.
        """
        FleetCarrierCargo._cargo.set_gui_root_once(root=root)

    @staticmethod
    def inventory(callback: InventoryCallback) -> None:
        """
        Provides synchronized access to the current cargo inventory.

        The callback receives the carrier's call sign (read-only)
        and a mutable reference to the cargo dictionary. If the callback
        returns True, the last access time is updated to the current time.

        :param callback: A function that receives (call_sign, cargo) and returns a bool.
        """

        def cargoAccess(cargo: CargoTally):
            if callback(FleetCarrierCargo._call_sign, cargo):
                FleetCarrierCargo._update_access_time_not_locked()
                FleetCarrierCargo._save_not_locked(cargo=cargo)

        FleetCarrierCargo._cargo.inventory(cargoAccess)

    @staticmethod
    def load():
        """
        Loads this object from the EDMC settings.
        """
        logger.debug("Trying to load cargo locally...")
        loaded_str = config.get_str(FleetCarrierCargo._json_config_name)
        if not loaded_str:
            logger.debug("Failed to load local data.")
            return False
        try:
            data = json.loads(loaded_str)
        except json.JSONDecodeError:
            logger.debug("Failed to parse local json data.")
            return False

        def load_all(cargo: CargoTally):
            logger.debug("FleetCarrier's cargo is locked for loading...")
            cargo.load_from_dict(data.get("cargo", {}))
            FleetCarrierCargo._last_sync = data.get("lastSync", None)
            FleetCarrierCargo._call_sign = data.get("callSign", None)
            logger.debug("FleetCarrier's cargo is loaded locally...")

        FleetCarrierCargo._cargo.inventory(load_all)
        return True

    @staticmethod
    def save():
        """
        Saves this object to EDMC settings.
        """

        def saver(cargo: CargoTally):
            FleetCarrierCargo._save_not_locked(cargo=cargo)

        FleetCarrierCargo._cargo.inventory(saver)

    @staticmethod
    def _save_not_locked(cargo: CargoTally):
        """
        Saves this object to EDMC settings without lock.
        Do not call it directly.
        """
        logger.debug("Saving carrier data...")
        data: dict[str, dict[str, int] | str | None] = {
            "cargo": cargo.to_json_dict(),
            "lastSync": FleetCarrierCargo._last_sync,
            "callSign": FleetCarrierCargo._call_sign,
        }
        config.set(
            FleetCarrierCargo._json_config_name,
            json.dumps(data, ensure_ascii=False, indent=2, separators=(",", ":")),
        )

    @staticmethod
    def _update_access_time_not_locked():
        """
        Do not use directly from outside.
        Updates last modified time stamp to now().
        """
        FleetCarrierCargo._last_sync = (
            datetime.datetime.now(datetime.timezone.utc)
            .replace(microsecond=0)
            .isoformat()
        )
        logger.debug("Updated access time to carrier.")

    @staticmethod
    def _load_from_capi(data: CAPIData):
        """
        Loads this object from Frontier's response.
        It will overwrite any existing data.
        Args:
            data (CAPIData): response generated by EDMC itself.
        Example of 1 CAPIData element in "cargo":
        {
            "commodity": "Tritium",
            "originSystem": null,
            "mission": false,
            "qty": 106,
            "value": 5629978,
            "stolen": false,
            "locName": "Tritium"
        },

        """
        logger.debug(f"Parsing CAPI data...{json.dumps(data, indent=2)}")

        def loader(cargo: CargoTally):
            FleetCarrierCargo._call_sign = data["name"]["callsign"]
            if not FleetCarrierCargo._call_sign:
                logger.warning("It was no callsign in CAPI response. Nothing parsed.")
                return
            logger.debug("Parsing CAPI cargo-data...")
            cargo.clear()
            for item in data["cargo"]:
                key = CargoKey(item)
                cargo[key] = cargo.get(key, 0) + item["qty"]
            FleetCarrierCargo._update_access_time_not_locked()
            FleetCarrierCargo._save_not_locked(cargo=cargo)

        FleetCarrierCargo._cargo.inventory(loader)

    @staticmethod
    def is_updating_from_server():
        """
        Returns True if updating is currently in progress.
        """
        return FleetCarrierCargo._updates_lock.locked()

    @staticmethod
    def sync_to_capi(data: CAPIData):
        """
        Sync cargo to existing response from Frontier's servers.

        Args:
            data (CAPIData): response from the servers as EDMC gives it.
        """

        def updater():
            with FleetCarrierCargo._updates_lock:
                logger.debug("Syncing to CAPI, got _updates_lock...")
                FleetCarrierCargo._load_from_capi(data)

        logger.debug("Syncing data to CAPI...")
        threading.Thread(target=updater, daemon=True).start()

    @staticmethod
    def update_from_server():
        """
        Tries to trigger cargo update from Frontier's servers.
        It may do nothing if something else already triggered (other plugin, for example).
        """

        def updater():
            if not FleetCarrierCargo._updates_lock.acquire(blocking=False):
                return
            try:
                logger.debug("Accessing server thread started...")
                sleep_time: int = 30
                attempts_count = 30

                for attempt in range(attempts_count):
                    if not threading.main_thread().is_alive():
                        logger.debug("Main thread is not alive, aborting update.")
                        return

                    if session.state != Session.STATE_OK:
                        logger.debug(
                            f"[Attempt {attempt + 1}] Session state is not OK. Retrying in {sleep_time}s..."
                        )
                        time.sleep(sleep_time)
                        continue

                    try:
                        logger.debug(
                            f"[Attempt {attempt + 1}] Querying remote FC data..."
                        )
                        response = session.requests_session.get(
                            session.capi_host_for_galaxy()
                            + session.FRONTIER_CAPI_PATH_FLEETCARRIER
                        )
                        FleetCarrierCargo._load_from_capi(response.json())
                        logger.debug("Remote data received and synced.")
                        return
                    except Exception as e:
                        logger.warning(
                            f"[Attempt {attempt + 1}] Failed to fetch data: {e}"
                        )
                        time.sleep(sleep_time)

                logger.error(
                    f"All {attempts_count} attempts to update fleet carrier data from server failed."
                )
            finally:
                FleetCarrierCargo._updates_lock.release()

        logger.debug("Loading data from server...")
        threading.Thread(target=updater, daemon=True).start()

    @staticmethod
    def load_or_update():
        """
        Tries to load data, if failed or it was outdated than query server.
        """
        if not FleetCarrierCargo.load() or FleetCarrierCargo.is_sync_stale(12 * 3600):
            FleetCarrierCargo.update_from_server()
