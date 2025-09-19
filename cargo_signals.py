from cargo_tally import CargoTally
from typing import Protocol


class InventoryCallback(Protocol):
    """
    Callback that receives the carrier's call sign (read-only) and
    a mutable reference to the cargo dictionary.

    Return True if you want to update the last access time to now().
    Note, external plugins should always return False, probably.
    """

    def __call__(self, call_sign: str | None, cargo: CargoTally) -> bool: ...


class InventoryOnlyCallback(Protocol):
    """
    Callback that receives a mutable reference to the cargo dictionary.
    """

    def __call__(self, cargo: CargoTally) -> None: ...


class SignalCargoWasChanged(Protocol):
    """
    A signal that is triggered when the cargo has changed, and is guaranteed to be called in the GUI (main) thread context.
    Implementations should avoid long-running operations; use this for lightweight tasks such as refreshing the UI.
    """

    def __call__(self) -> None: ...
