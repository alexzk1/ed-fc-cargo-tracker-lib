from dataclasses import dataclass
from typing import Optional
from config import config
import csv


@dataclass
class MarketName:
    category: str
    trade_name: str
    id: int


class MarketCatalogue:
    """
    This class can translate "key-name" from commodity/cargo response in CAPI into human readable names.
    Example of server response:
        {
            "commodity": "Tritium",
            "originSystem": null,
            "mission": false,
            "qty": 106,
            "value": 5629978,
            "stolen": false,
            "locName": "Tritium"
        },
    This one translates value of "commodity" field into value of "locName" field effectively.
    """

    _SYMBOL_TO_MARKET_NAMES: dict[str, MarketName] = {}

    @staticmethod
    def load_commodity_map() -> None:
        for f in ("commodity.csv", "rare_commodity.csv"):
            if not (config.app_dir_path / "FDevIDs" / f).is_file():
                continue
            with open(
                config.app_dir_path / "FDevIDs" / f, "r", encoding="utf-8"
            ) as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    MarketCatalogue._SYMBOL_TO_MARKET_NAMES[row["symbol"].lower()] = (
                        MarketName(row["category"], row["name"], int(row["id"]))
                    )

    @staticmethod
    def explain_commodity(commodity: str) -> Optional[MarketName]:
        """
        Translates cargo-name as key in CAPI response into human readable name.
        """
        commodity = commodity.lower()
        if commodity in MarketCatalogue._SYMBOL_TO_MARKET_NAMES:
            return MarketCatalogue._SYMBOL_TO_MARKET_NAMES[commodity]
        return None
