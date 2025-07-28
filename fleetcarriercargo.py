# Portions of this code are based on the following source:
# Repository: https://github.com/karolnowacki/edmc-colonisation-plugin.git
# Branch: develop
# Source files: colonization/*


from dataclasses import dataclass, field
import datetime
import json
import threading
from typing import Any, Self
from os import path
from companion import CAPIData, session, Session
from config import config

__json_config_name: str = "edmc_fleet_carrier_cargo_lib"


class FleetCarrierCargo:
    _instance = None
    _instance_lock = threading.Lock()

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
        with self._lock:
            loaded_str = config.get_str(__json_config_name)
            if not loaded_str:
                return False
            try:
                data = json.loads(loaded_str)
            except json.JSONDecodeError:
                return False
            self._cargo = data.get("cargo", {})
            self._last_sync = data.get("lastSync", None)
            self._call_sign = data.get("callSign", None)
            return True

    def save(self):
        with self._lock:
            data: dict[str, dict[str, int] | str | None] = {
                "cargo": self._cargo,
                "lastSync": self._last_sync,
                "callSign": self._call_sign,
            }
            config.set(
                __json_config_name,
                json.dumps(data, ensure_ascii=False, indent=2, separators=(",", ":")),
            )

    def load_from_capi(self, data: CAPIData):
        with self._lock:
            self._call_sign = data["name"]["callsign"]
            if not self._call_sign:
                return None
            self._last_sync = (
                datetime.datetime.now(datetime.timezone.utc)
                .replace(microsecond=0)
                .isoformat()
            )
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
            if not self.access_cargo().load():
                self.update_from_server()

    def update_from_server(self):
        if session.state != Session.STATE_OK:
            return
        response = session.requests_session.get(
            session.capi_host_for_galaxy() + session.FRONTIER_CAPI_PATH_FLEETCARRIER
        )
        self.sync_to_capi(response.json())

    def sync_to_capi(self, data: CAPIData):
        self.__carrier.load_from_capi(data)
        self.access_cargo().save()

    def access_cargo(self) -> FleetCarrierCargo:
        """Main method to access cargo. Use methods of the returned object to deal with.
        Note, this object is shared accross all plugins in the current session."""
        return self.__carrier
