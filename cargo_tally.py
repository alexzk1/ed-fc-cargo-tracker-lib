import copy
import json

from _logger import logger

from typing import Any
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
        data.load_from_dict(d)
        return data

    def load_from_dict(self, d: dict[str, int]) -> None:
        self.clear()
        for k, v in d.items():
            logger.debug(f"Decoding: {k}")
            key_dict = json.loads(k)
            self[CargoKey(key_dict)] = v

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_json_dict(), **kwargs)

    @classmethod
    def from_json(cls, s: str) -> "CargoTally":
        d = json.loads(s)
        return cls.from_json_dict(d)
