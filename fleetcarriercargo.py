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

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def is_initialized(cls) -> bool:
        return cls._instance is not None

    def is_sync_stale(self, max_age_seconds: int = 3600) -> bool:
        """
        Checks whether the synchronization is stale.

        :param max_age_seconds: Maximum allowed data age in seconds (default is 1 hour).
        :return: True if the last synchronization time is older than max_age_seconds.
        """

        with self._cargo_lock:
            try:
                last_sync_str = type(self)._last_sync
                if last_sync_str is None or last_sync_str == "":
                    return True
                last_sync_dt = datetime.datetime.fromisoformat(last_sync_str)
                now = datetime.datetime.now(datetime.timezone.utc)
                delta = now - last_sync_dt
                return delta.total_seconds() > max_age_seconds
            except Exception:
                return True

    def inventory(self, callback: InventoryCallback) -> None:
        """
        Provides synchronized access to the current cargo inventory.

        The callback receives the carrier's call sign (read-only)
        and a mutable reference to the cargo dictionary. If the callback
        returns True, the last access time is updated to the current time.

        :param callback: A function that receives (call_sign, cargo) and returns a bool.
        """
        with type(self)._cargo_lock:
            logger.debug("Accessing inventory")
            if callback(type(self)._call_sign, type(self)._cargo):
                self._update_access_time_not_locked()

    def load(self):
        """
        Loads this object from the EDMC settings.
        """
        logger.debug("Trying to load cargo locally...")
        with type(self)._cargo_lock:
            logger.debug("Cargo is locked for loading...")
            loaded_str = config.get_str(type(self)._json_config_name)
            if not loaded_str:
                logger.debug("Failed to load local data.")
                return False
            try:
                data = json.loads(loaded_str)
            except json.JSONDecodeError:
                logger.debug("Failed to parse local json data.")
                return False
            type(self)._cargo = data.get("cargo", {})
            type(self)._last_sync = data.get("lastSync", None)
            type(self)._call_sign = data.get("callSign", None)
            logger.debug("Cargo is loaded locally...")
            return True

    def save(self):
        """
        Saves this object to EDMC settings.
        """
        logger.debug("Saving carrier data...")
        with type(self)._cargo_lock:
            self._save_not_locked()

    def _save_not_locked(self):
        """
        Saves this object to EDMC settings without lock.
        Do not call it directly.
        """
        logger.debug("Saving carrier data...")
        data: dict[str, dict[str, int] | str | None] = {
            "cargo": type(self)._cargo,
            "lastSync": type(self)._last_sync,
            "callSign": type(self)._call_sign,
        }
        config.set(
            type(self)._json_config_name,
            json.dumps(data, ensure_ascii=False, indent=2, separators=(",", ":")),
        )

    def _update_access_time_not_locked(self):
        """
        Do not use directly from outside.
        Updates last modified tume-stamp to now().
        """
        type(self)._last_sync = (
            datetime.datetime.now(datetime.timezone.utc)
            .replace(microsecond=0)
            .isoformat()
        )
        logger.debug("Updated access time to carrier.")

    def load_from_capi(self, data: CAPIData):
        """
        Loads this object from Frontier's response.
        It will overwrite any existing data.
        Args:
            data (CAPIData): response generated by EDMC itself.
        """
        logger.debug("Parsing CAPI data...")
        with type(self)._cargo_lock:
            type(self)._call_sign = data["name"]["callsign"]
            if not type(self)._call_sign:
                logger.warning("It was no callsign in CAPI response. Nothing parsed.")
                return
            self._update_access_time_not_locked()
            logger.debug("Parsing CAPI cargo-data...")
            type(self)._cargo = {}
            for c in data["cargo"]:
                cn = c["commodity"].lower()
                if cn in type(self)._cargo:
                    type(self)._cargo[cn] += c["qty"]
                else:
                    type(self)._cargo[cn] = c["qty"]
            self._save_not_locked()

    def update_from_server(self):
        """
        Tries to trigger cargo update from Frontier's servers.
        It may do nothing if something else already triggered (other plugin, for example).
        """

        def worker():
            if not type(self)._updates_lock.acquire(blocking=False):
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
                        self.load_from_capi(response.json())
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
                type(self)._updates_lock.release()

        logger.debug("Loading data from server...")
        threading.Thread(target=worker, daemon=True).start()


class FleetCarrier:
    """
    Front-face to access carrier.
    It can be many such objects created, they will all use the same cargo amoung all plugins.
    """

    def __init__(self):
        is_first_load = not FleetCarrierCargo.is_initialized()
        self.__carrier = FleetCarrierCargo()
        if is_first_load:
            logger.debug("This is 1st copy of the object, loading things...")
            if not self.access_cargo().load() or self.access_cargo().is_sync_stale(
                3600 * 12
            ):
                self.access_cargo().update_from_server()
        else:
            logger.debug(
                "This is NOT 1st copy of the object, skipping loading of things..."
            )

    def sync_to_capi(self, data: CAPIData):
        """
        Sync cargo to existing response from Frontier's servers.

        Args:
            data (CAPIData): response from the servers as EDMC gives it.
        """
        self.__carrier.load_from_capi(data)

    def access_cargo(self) -> FleetCarrierCargo:
        """Main method to access cargo. Use methods of the returned object to deal with.
        Note, this object is shared accross all plugins in the current session."""
        logger.debug("Accessing cargo on carrier...")
        return self.__carrier
