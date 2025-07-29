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


class FleetCarrierCargo:
    _instance = None
    _instance_lock = threading.Lock()
    _json_config_name: str = "edmc_fleet_carrier_cargo_lib"

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init_once()
        return cls._instance

    @classmethod
    def is_initialized(cls) -> bool:
        return cls._instance is not None

    def _init_once(self):
        self._lock = threading.Lock()
        self._cargo: dict[str, int] = {}
        self._last_sync: str | None = None
        self._call_sign: str | None = None

    def is_sync_stale(self, max_age_seconds: int = 3600) -> bool:
        """
        Проверяет, устарела ли синхронизация.
        :param max_age_seconds: Максимально допустимый возраст данных в секундах (по умолчанию 1 час).
        :return: True, если время последней синхронизации старше max_age_seconds.
        """
        with self._lock:
            if not self._last_sync:
                return True
            try:
                last_sync_dt = datetime.datetime.fromisoformat(self._last_sync)
                now = datetime.datetime.now(datetime.timezone.utc)
                delta = now - last_sync_dt
                return delta.total_seconds() > max_age_seconds
            except Exception:
                return True

    def get_cargo(self):
        """Returns a copy of the current cargo"""
        with self._lock:
            return dict(self._cargo)

    def set_cargo(self, cargo_dict: dict[str, int]):
        """Sets current cargo in full."""
        with self._lock:
            self._cargo = dict(cargo_dict)

    def add_commodity(self, commodity: str, qty: int):
        with self._lock:
            self._cargo[commodity] = self._cargo.get(commodity, 0) + qty

    def get_commodity(self, commodity: str) -> int:
        with self._lock:
            return self._cargo.get(commodity, 0)

    def get_last_sync(self):
        with self._lock:
            return self._last_sync

    def set_last_sync(self, value: str):
        with self._lock:
            self._last_sync = value

    def get_call_sign(self):
        with self._lock:
            return self._call_sign

    def load(self):
        logger.debug("Trying to load cargo locally...")
        with self._lock:
            logger.debug("Cargo is locked for loading...")
            loaded_str = config.get_str(self._json_config_name)
            if not loaded_str:
                logger.debug("Failed to load local data.")
                return False
            try:
                data = json.loads(loaded_str)
            except json.JSONDecodeError:
                logger.debug("Failed to parse local json data.")
                return False
            self._cargo = data.get("cargo", {})
            self._last_sync = data.get("lastSync", None)
            self._call_sign = data.get("callSign", None)
            logger.debug("Cargo is loaded locally...")
            return True

    def save(self):
        logger.debug("Saving carrier data...")
        with self._lock:
            data: dict[str, dict[str, int] | str | None] = {
                "cargo": self._cargo,
                "lastSync": self._last_sync,
                "callSign": self._call_sign,
            }
            config.set(
                self._json_config_name,
                json.dumps(data, ensure_ascii=False, indent=2, separators=(",", ":")),
            )

    def load_from_capi(self, data: CAPIData):
        logger.debug("Parsing CAPI data...")
        with self._lock:
            self._call_sign = data["name"]["callsign"]
            if not self._call_sign:
                logger.warning("It was no callsign in CAPI response. Nothing parsed.")
                return
            self._last_sync = (
                datetime.datetime.now(datetime.timezone.utc)
                .replace(microsecond=0)
                .isoformat()
            )
            logger.debug("Parsing CAPI cargo-data...")
            self._cargo = {}
            for c in data["cargo"]:
                cn = c["commodity"].lower()
                if cn in self._cargo:
                    self._cargo[cn] += c["qty"]
                else:
                    self._cargo[cn] = c["qty"]


class FleetCarrier:
    def __init__(self):
        is_first_load = not FleetCarrierCargo.is_initialized()
        self.__carrier = FleetCarrierCargo()
        if is_first_load:
            logger.debug("This is 1st copy of the object, loading things...")
            if not self.access_cargo().load() or self.access_cargo().is_sync_stale(
                3600 * 12
            ):
                self.update_from_server()
        else:
            logger.debug(
                "This is NOT 1st copy of the object, skipping loading of things..."
            )

    def update_from_server(self):
        def worker():
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
                    logger.debug(f"[Attempt {attempt + 1}] Querying remote FC data...")
                    response = session.requests_session.get(
                        session.capi_host_for_galaxy()
                        + session.FRONTIER_CAPI_PATH_FLEETCARRIER
                    )
                    self.sync_to_capi(response.json())
                    logger.debug("Remote data received and synced.")
                    return
                except Exception as e:
                    logger.warning(f"[Attempt {attempt + 1}] Failed to fetch data: {e}")
                    time.sleep(sleep_time)

            logger.error(
                f"All {attempts_count} attempts to update fleet carrier data from server failed."
            )

        logger.debug("Loading data from server...")
        threading.Thread(target=worker, daemon=True).start()

    def sync_to_capi(self, data: CAPIData):
        self.__carrier.load_from_capi(data)
        self.access_cargo().save()

    def access_cargo(self) -> FleetCarrierCargo:
        """Main method to access cargo. Use methods of the returned object to deal with.
        Note, this object is shared accross all plugins in the current session."""
        logger.debug("Accessing cargo on carrier...")
        return self.__carrier
