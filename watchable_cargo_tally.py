import threading
from typing import Any
from _logger import logger

from cargo_tally import CargoKey, CargoTally
from cargo_signals import InventoryOnlyCallback, SignalCargoWasChanged

from tkinter import Tk


class WatchableCargoTally:
    def __init__(self):
        self._cargo_lock = threading.Lock()
        self._cargo: CargoTally = CargoTally()

        self._signals_lock = threading.Lock()
        self._handlers: list[SignalCargoWasChanged] = []
        self._gui_root: Tk | None = None

    def set_gui_root_once(self, root: Tk):
        """
        Internal method.
        Do not use it directly.
        """
        with self._signals_lock:
            if self._gui_root is None:
                self._gui_root = root
            elif self._gui_root != root:
                raise RuntimeError("Attempt to overwrite GUI root")

    def add_on_cargo_change_handler(self, handler: SignalCargoWasChanged):
        """
        Installs your handler of the "cargo changed" event.
        Note, you cannot un-install it.
        """
        with self._signals_lock:
            self._handlers.append(handler)

    def inventory(self, callback: InventoryOnlyCallback) -> None:
        """
        Provides synchronized access to the current cargo inventory.
        The callback receives the a mutable reference to the cargo dictionary.

        :param callback: A function that receives (cargo).
        """
        with self._cargo_lock:
            logger.debug("Accessing watchable inventory")
            old_hash = hash(frozenset(self._cargo.items()))
            callback(self._cargo)

            keys_to_remove: list[Any] = []
            for k, v in self._cargo.items():
                if not isinstance(k, CargoKey) or not isinstance(v, int) or v <= 0:  # pyright: ignore[reportUnnecessaryIsInstance]
                    keys_to_remove.append(k)
            for k in keys_to_remove:
                del self._cargo[k]

            new_hash = hash(frozenset(self._cargo.items()))
            if old_hash != new_hash:
                self.signal_cargo_was_changed()

    def signal_cargo_was_changed(self):
        """
        Internal method, used to call all handlers out of main-gui thread.
        """
        with self._signals_lock:
            if self._gui_root:
                logger.debug("Calling on_cargo_changed handlers.")
                for handler in self._handlers:
                    try:
                        self._gui_root.after(0, handler)
                    except Exception as e:
                        logger.error(f"Handler raised exception: {e}", exc_info=True)
            else:
                logger.warning("Called _signal_cargo_was_changed() without GUI root.")
