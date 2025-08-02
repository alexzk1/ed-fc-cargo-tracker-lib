from dataclasses import dataclass
import json
import time
from typing import Dict, Optional, Any, Protocol, ClassVar
import threading
from _logger import logger
from config import config
import fleetcarriercargo

# How often request carrier update amoung many other events, except docking.
_UPDATE_PERIOD_SECONDS_DUE_GAMEPLAY = 7200


@dataclass
class JournalContext:
    """Gathers all journal callback's parameters in one place."""

    cmdr: str
    is_beta: bool
    system: Optional[str]
    station: Optional[str]
    entry: Dict[str, Any]
    state: Dict[str, Any]

    @property
    def event(self) -> Optional[str]:
        return self.entry.get("event")

    def get(self, key: str, default: Any = None) -> Any:
        return self.entry.get(key, default)

    def is_own_carrier(self) -> bool:
        own: bool = False
        if self.station:

            def callback(call_sign: str | None, cargo: dict[str, int]) -> bool:
                nonlocal own
                if call_sign == self.station or call_sign == self.state["StationName"]:
                    own = True
                return False

            fleetcarriercargo.FleetCarrierCargo().inventory(callback)
        return own


class JournalHandler(Protocol):
    """Callable to process JournalContext."""

    def __call__(self, ctx: JournalContext) -> None: ...


class PersistentCmdrState:
    _cmdr_state_save_key: str = "edmc_fleet_carrier_cargo_lib_cmdr_state"

    def __init__(self):
        self.is_docked_on_own_carrer: bool = False

    def save(self):
        data: dict[str, dict[str, int] | str | None | bool] = {
            "is_docked_on_own_carrer": self.is_docked_on_own_carrer,
        }
        config.set(
            self._cmdr_state_save_key,
            json.dumps(data, ensure_ascii=False, indent=2, separators=(",", ":")),
        )

    def load(self):
        loaded_str = config.get_str(self._cmdr_state_save_key)
        if not loaded_str:
            logger.warning("Failed to load local persistent CMDR state.")
            return False
        try:
            data = json.loads(loaded_str)
        except json.JSONDecodeError:
            logger.error("Failed to parse local json of persistent CMDR state.")
            return False
        self.is_docked_on_own_carrer = data.get("is_docked_on_own_carrer", False)
        logger.debug(f"Loaded docked on own carrier: {self.is_docked_on_own_carrer}")
        return True

    def reset_all(self):
        self.is_docked_on_own_carrer = False


class CargoMonitor:
    _data_lock = threading.Lock()
    _updates_lock = threading.Lock()

    _last_known_cmdr: str = ""
    _delayed_update_data: list[JournalContext] = []
    _last_known_cmdr_state: PersistentCmdrState = PersistentCmdrState()

    @staticmethod
    def _apply_all_delayed_updates():
        """Does actual apply of cached data."""
        with CargoMonitor._data_lock:
            for ctx in CargoMonitor._delayed_update_data:
                entry = ctx.entry
                event: Optional[str] = entry.get("event")
                if not event:
                    logger.error("Empty event in consumer, should never happen.")
                    continue
                handler = CargoMonitor.EVENT_HANDLERS.get(event)
                if handler:
                    handler(ctx)
                else:
                    logger.error("Event '{event}' was queued but it has no handler!")
            CargoMonitor._delayed_update_data.clear()

    @staticmethod
    def _is_delayed_updating():
        """
        Returns True if updating is currently in progress.
        """
        return CargoMonitor._updates_lock.locked()

    @staticmethod
    def _delayed_update():
        """
        Consumer (thread). It locks mutex, and parses everything atm, than releases mutex and sleeps some.
        If CAPI request is in progress, it just waits till one ends, than applies changes.
        """

        def updater():
            if not CargoMonitor._updates_lock.acquire(blocking=False):
                return
            try:
                sleep_time: int = 5
                while threading.main_thread().is_alive():
                    if not fleetcarriercargo.FleetCarrierCargo.is_updating_from_server():
                        CargoMonitor._apply_all_delayed_updates()
                    else:
                        logger.debug("Awaiting CAPI to finish...")
                    time.sleep(sleep_time)
            finally:
                CargoMonitor._updates_lock.release()

        if not CargoMonitor._is_delayed_updating():
            logger.debug("Delayed update by the event.")
            threading.Thread(target=updater, daemon=True).start()

    @staticmethod
    def _cmdrSwitchedTo(cmdr: str):
        logger.info(f"New CMDR detected {cmdr}. Resetting fleet carrier data.")
        CargoMonitor._last_known_cmdr_state.reset_all()
        fleetcarriercargo.FleetCarrierCargo.update_from_server()

    @staticmethod
    def _cmdrLoggedIn(cmdr: str):
        CargoMonitor._last_known_cmdr_state.load()
        if (
            not fleetcarriercargo.FleetCarrierCargo.load()
            or fleetcarriercargo.FleetCarrierCargo.is_sync_stale(3600 * 12)
        ):
            fleetcarriercargo.FleetCarrierCargo.update_from_server()

    @staticmethod
    def process_journal_entry(
        cmdr: str,
        is_beta: bool,
        system: Optional[str],
        station: Optional[str],
        entry: Dict[str, Any],
        state: Dict[str, Any],
    ) -> None:
        with CargoMonitor._data_lock:
            if (
                CargoMonitor._last_known_cmdr == ""
                or CargoMonitor._last_known_cmdr != cmdr
            ):
                if CargoMonitor._last_known_cmdr != "":
                    CargoMonitor._cmdrSwitchedTo(cmdr)
                else:
                    CargoMonitor._cmdrLoggedIn(cmdr)

                CargoMonitor._last_known_cmdr = cmdr
                CargoMonitor._delayed_update_data.clear()

            event: Optional[str] = entry.get("event")
            if not event or event not in CargoMonitor.EVENT_HANDLERS:
                # TODO: we may want some smart tracking, like player does missions somewhere - it is safe to update FC.
                if (
                    fleetcarriercargo.FleetCarrierCargo.is_sync_stale(
                        _UPDATE_PERIOD_SECONDS_DUE_GAMEPLAY
                    )
                    and not CargoMonitor._last_known_cmdr_state.is_docked_on_own_carrer
                ):
                    logger.debug("Forcing CAPI update, because time passed outside.")
                    fleetcarriercargo.FleetCarrierCargo.update_from_server()
                return

            ctx: JournalContext = JournalContext(
                cmdr=cmdr,
                is_beta=is_beta,
                system=system,
                station=station,
                entry=entry,
                state=state,
            )

            # Producer
            logger.debug(f"Adding EDMC event for the later processing: {event}.")
            CargoMonitor._delayed_update_data.append(ctx)
            # Run consumer
            CargoMonitor._delayed_update()

    # https://github.com/EDCD/EDMarketConnector/blob/main/PLUGINS.md

    @staticmethod
    def handle_docked(ctx: JournalContext) -> None:
        old = CargoMonitor._last_known_cmdr_state.is_docked_on_own_carrer
        CargoMonitor._last_known_cmdr_state.is_docked_on_own_carrer = (
            ctx.entry.get("StationType") == "FleetCarrier" and ctx.is_own_carrier()
        )
        if old != CargoMonitor._last_known_cmdr_state.is_docked_on_own_carrer:
            CargoMonitor._last_known_cmdr_state.save()

    @staticmethod
    def handle_undocked(ctx: JournalContext) -> None:
        # Respect SSD ...
        old = CargoMonitor._last_known_cmdr_state.is_docked_on_own_carrer
        CargoMonitor._last_known_cmdr_state.is_docked_on_own_carrer = False
        if old != CargoMonitor._last_known_cmdr_state.is_docked_on_own_carrer:
            CargoMonitor._last_known_cmdr_state.save()

    @staticmethod
    def handle_market_buy(ctx: JournalContext) -> None:
        if not CargoMonitor._last_known_cmdr_state.is_docked_on_own_carrer:
            return

        def process_buy(call_sign: str | None, cargo: dict[str, int]):
            nonlocal ctx
            key = ctx.entry["Type"].lower()
            item = cargo.get(key, 0) - ctx.entry["Count"]
            cargo[key] = item
            return True

        fleetcarriercargo.FleetCarrierCargo.inventory(process_buy)

    @staticmethod
    def handle_market_sell(ctx: JournalContext) -> None:
        if not CargoMonitor._last_known_cmdr_state.is_docked_on_own_carrer:
            return

        def process_sell(call_sign: str | None, cargo: dict[str, int]):
            nonlocal ctx
            key = ctx.entry["Type"].lower()
            item = cargo.get(key, 0) + ctx.entry["Count"]
            cargo[key] = item
            return True

        fleetcarriercargo.FleetCarrierCargo.inventory(process_sell)

    @staticmethod
    def handle_cargo_transfer(ctx: JournalContext) -> None:
        if not CargoMonitor._last_known_cmdr_state.is_docked_on_own_carrer:
            logger.warning(
                "Receieved event 'CargoTransfer' but didn't have mark that docked to own carrier."
            )
            CargoMonitor._last_known_cmdr_state.is_docked_on_own_carrer = True
            CargoMonitor._last_known_cmdr_state.save()

        def process_transfers(call_sign: str | None, cargo: dict[str, int]):
            nonlocal ctx
            for t in ctx.entry["Transfers"]:
                key = t["Type"].lower()
                item = cargo.get(key, 0)
                if t["Direction"] == "toship":
                    item -= t["Count"]
                if t["Direction"] == "tocarrier":
                    item += t["Count"]
                cargo[key] = item
            return True

        fleetcarriercargo.FleetCarrierCargo.inventory(process_transfers)

    EVENT_HANDLERS: ClassVar[dict[str, JournalHandler]]


CargoMonitor.EVENT_HANDLERS = {
    "Docked": CargoMonitor.handle_docked,
    "Undocked": CargoMonitor.handle_undocked,
    "MarketBuy": CargoMonitor.handle_market_buy,
    "MarketSell": CargoMonitor.handle_market_sell,
    "CargoTransfer": CargoMonitor.handle_cargo_transfer,
}
