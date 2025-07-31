# Portions of this code are based on the following source:
# Repository: https://github.com/karolnowacki/edmc-colonisation-plugin.git
# Branch: develop
# Source files: colonization/*


import datetime
import json
import threading
from companion import CAPIData, session, Session
from config import config
from _logger import logger
import time

from typing import Protocol


class InventoryCallback(Protocol):
    """
    Callback that receives the carrier's call sign (read-only) and
    a mutable reference to the cargo dictionary.

    Return True if you want to update the last access time to now().
    Note, external plugins should always return False, probably.
    """

    def __call__(self, call_sign: str | None, cargo: dict[str, int]) -> bool: ...


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
    _cargo_lock = threading.Lock()

    _cargo: dict[str, int] = {}
    _last_sync: str | None = None
    _call_sign: str | None = None

    @staticmethod
    def is_sync_stale(max_age_seconds: int = 3600) -> bool:
        """
        Checks whether the synchronization is stale.

        :param max_age_seconds: Maximum allowed data age in seconds (default is 1 hour).
        :return: True if the last synchronization time is older than max_age_seconds.
        """

        with FleetCarrierCargo._cargo_lock:
            last_sync_str = FleetCarrierCargo._last_sync
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
    def inventory(callback: InventoryCallback) -> None:
        """
        Provides synchronized access to the current cargo inventory.

        The callback receives the carrier's call sign (read-only)
        and a mutable reference to the cargo dictionary. If the callback
        returns True, the last access time is updated to the current time.

        :param callback: A function that receives (call_sign, cargo) and returns a bool.
        """
        with FleetCarrierCargo._cargo_lock:
            logger.debug("Accessing inventory")
            res = callback(FleetCarrierCargo._call_sign, FleetCarrierCargo._cargo)
            FleetCarrierCargo._cargo = {
                k: v for k, v in FleetCarrierCargo._cargo.items() if v > 0
            }
            if res:
                FleetCarrierCargo._update_access_time_not_locked()
                FleetCarrierCargo._save_not_locked()

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
        with FleetCarrierCargo._cargo_lock:
            logger.debug("Cargo is locked for loading...")
            FleetCarrierCargo._cargo = data.get("cargo", {})
            FleetCarrierCargo._last_sync = data.get("lastSync", None)
            FleetCarrierCargo._call_sign = data.get("callSign", None)
            logger.debug("Cargo is loaded locally...")
        return True

    @staticmethod
    def save():
        """
        Saves this object to EDMC settings.
        """
        logger.debug("Saving carrier data...")
        with FleetCarrierCargo._cargo_lock:
            FleetCarrierCargo._save_not_locked()

    @staticmethod
    def _save_not_locked():
        """
        Saves this object to EDMC settings without lock.
        Do not call it directly.
        """
        logger.debug("Saving carrier data...")
        data: dict[str, dict[str, int] | str | None] = {
            "cargo": FleetCarrierCargo._cargo,
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
        Updates last modified tume-stamp to now().
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
        """
        logger.debug("Parsing CAPI data...")
        with FleetCarrierCargo._cargo_lock:
            FleetCarrierCargo._call_sign = data["name"]["callsign"]
            if not FleetCarrierCargo._call_sign:
                logger.warning("It was no callsign in CAPI response. Nothing parsed.")
                return
            logger.debug("Parsing CAPI cargo-data...")
            FleetCarrierCargo._cargo = {}
            for c in data["cargo"]:
                cn = c["commodity"].lower()
                if cn in FleetCarrierCargo._cargo:
                    FleetCarrierCargo._cargo[cn] += c["qty"]
                else:
                    FleetCarrierCargo._cargo[cn] = c["qty"]
            FleetCarrierCargo._update_access_time_not_locked()
            FleetCarrierCargo._save_not_locked()

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
