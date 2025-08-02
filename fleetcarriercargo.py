# Portions of this code are based on the following source:
# Repository: https://github.com/karolnowacki/edmc-colonisation-plugin.git
# Branch: develop
# Source files: colonization/*


import copy
import datetime
import json
import threading
from tkinter import Tk
from companion import CAPIData, session, Session
from config import config
from _logger import logger
import time
from typing import Any, Protocol
from cargo_names import MarketCatalogue, MarketName


class CargoKey:
    """
    This is information about cargo (at least the name of it).
    """

    def __init__(self, source: str | dict[str, Any]):
        if isinstance(source, str):
            self._fields: dict[str, Any] = {
                "commodity": source.lower(),
                "stolen": False,
                "mission": False,
                "originSystem": None,
                "qty": None,
                "value": None,
                "locName": None,
            }
        else:
            self._fields: dict[str, Any] = copy.deepcopy(source)
            self._fields["commodity"] = self._fields["commodity"].lower()
            self._fields["qty"] = None
            self._fields["value"] = None
            self._fields["locName"] = None

            # TODO: deal with those fields later, as it requires changes in CargoMonitor too:
            self._fields["stolen"] = False
            self._fields["mission"] = False
            self._fields["originSystem"] = None

    @property
    def commodity(self):
        """
        This "symbol" ("commodity") name, used by the game to name some commodity.
        """
        return self._fields["commodity"]

    @property
    def is_stolen(self) -> bool:
        return self._fields["stolen"]

    def market_name(self):
        """
        Returns name situable to show in GUI to user.
        """
        what = self.commodity
        return (
            MarketCatalogue.explain_commodity(what) or MarketName("", what, 0)
        ).trade_name

    def __eq__(self, other: Any):
        if not isinstance(other, CargoKey):
            return NotImplemented
        return self._fields == other._fields

    def __hash__(self):
        return hash(tuple(sorted(self._fields.items())))

    def __repr__(self):
        return f"CargoKey({self._fields!r})"

    def to_string(self) -> str:
        return json.dumps(self._fields, sort_keys=True, separators=(",", ":"))


class CargoTally(dict[CargoKey, int]):
    """
    Contains cargo information as key, and quantity as value.
    """

    def to_json_dict(self) -> dict[str, int]:
        return {key.to_string(): value for key, value in self.items()}

    @classmethod
    def from_json_dict(cls, d: dict[str, int]) -> "CargoTally":
        data = cls()
        for k, v in d.items():
            logger.debug(f"Decoding: {k}")
            key_dict = json.loads(k)
            data[CargoKey(key_dict)] = v
        return data

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_json_dict(), **kwargs)

    @classmethod
    def from_json(cls, s: str) -> "CargoTally":
        d = json.loads(s)
        return cls.from_json_dict(d)


class InventoryCallback(Protocol):
    """
    Callback that receives the carrier's call sign (read-only) and
    a mutable reference to the cargo dictionary.

    Return True if you want to update the last access time to now().
    Note, external plugins should always return False, probably.
    """

    def __call__(self, call_sign: str | None, cargo: CargoTally) -> bool: ...


class SignalCargoWasChanged(Protocol):
    """
    A signal that is triggered when the cargo has changed, and is guaranteed to be called in the GUI (main) thread context.
    Implementations should avoid long-running operations; use this for lightweight tasks such as refreshing the UI.
    """

    def __call__(self) -> None: ...


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
    _signals_lock = threading.Lock()

    _cargo: CargoTally = CargoTally()
    _last_sync: str | None = None
    _call_sign: str | None = None
    _handlers: list[SignalCargoWasChanged] = []
    _gui_root: Tk | None = None

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
    def add_on_cargo_change_handler(handler: SignalCargoWasChanged):
        """
        Installs your handler of the "cargo changed" event.
        Note, you cannot un-install it.
        """
        with FleetCarrierCargo._signals_lock:
            FleetCarrierCargo._handlers.append(handler)

    @staticmethod
    def set_gui_root_once(root: Tk):
        """
        Internal method.
        Do not use it directly.
        """
        with FleetCarrierCargo._signals_lock:
            if FleetCarrierCargo._gui_root is None:
                FleetCarrierCargo._gui_root = root
            elif FleetCarrierCargo._gui_root != root:
                raise RuntimeError("Attempt to overwrite GUI root")

    @staticmethod
    def _signal_cargo_was_changed():
        """
        Internal method, used to call all handlers out of main-gui thread.
        """
        with FleetCarrierCargo._signals_lock:
            if FleetCarrierCargo._gui_root:
                logger.debug("Calling on_cargo_changed handlers.")
                for handler in FleetCarrierCargo._handlers:
                    try:
                        FleetCarrierCargo._gui_root.after(0, handler)
                    except Exception as e:
                        logger.error(f"Handler raised exception: {e}", exc_info=True)
            else:
                logger.warning("Called _signal_cargo_was_changed() without GUI root.")

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
            old_hash = hash(frozenset(FleetCarrierCargo._cargo.items()))
            res = callback(FleetCarrierCargo._call_sign, FleetCarrierCargo._cargo)
            invalid_keys = [
                k
                for k in FleetCarrierCargo._cargo
                if not isinstance(k, CargoKey)  # pyright: ignore[reportUnnecessaryIsInstance]
            ]
            if invalid_keys:
                logger.warning(
                    "FleetCarrierCargo: removed invalid keys: %s",
                    ", ".join(repr(k) for k in invalid_keys),
                )
            FleetCarrierCargo._cargo = CargoTally(
                {
                    k: v
                    for k, v in FleetCarrierCargo._cargo.items()
                    if isinstance(k, CargoKey) and v > 0  # pyright: ignore[reportUnnecessaryIsInstance]
                }
            )
            new_hash = hash(frozenset(FleetCarrierCargo._cargo.items()))
            if res:
                FleetCarrierCargo._update_access_time_not_locked()
                FleetCarrierCargo._save_not_locked()
            if old_hash != new_hash:
                FleetCarrierCargo._signal_cargo_was_changed()

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
            FleetCarrierCargo._cargo = CargoTally.from_json_dict(data.get("cargo", {}))
            FleetCarrierCargo._last_sync = data.get("lastSync", None)
            FleetCarrierCargo._call_sign = data.get("callSign", None)
            logger.debug("Cargo is loaded locally...")
            FleetCarrierCargo._signal_cargo_was_changed()
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
            "cargo": FleetCarrierCargo._cargo.to_json_dict(),
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
        with FleetCarrierCargo._cargo_lock:
            FleetCarrierCargo._call_sign = data["name"]["callsign"]
            if not FleetCarrierCargo._call_sign:
                logger.warning("It was no callsign in CAPI response. Nothing parsed.")
                return
            logger.debug("Parsing CAPI cargo-data...")
            FleetCarrierCargo._cargo = CargoTally()
            for item in data["cargo"]:
                key = CargoKey(item)
                if key in FleetCarrierCargo._cargo:
                    FleetCarrierCargo._cargo[key] += item["qty"]
                else:
                    FleetCarrierCargo._cargo[key] = item["qty"]
            FleetCarrierCargo._update_access_time_not_locked()
            FleetCarrierCargo._save_not_locked()
        FleetCarrierCargo._signal_cargo_was_changed()

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
