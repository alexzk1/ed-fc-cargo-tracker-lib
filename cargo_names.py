class HumanCargoName:
    """
    This class can translate "key-name" from commodity/cargo response in CAPI into human readable locilized names.
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

    @staticmethod
    def localize(key_name: str) -> str:
        """
        Translates cargo-name as key in CAPI response into human readable name.
        """
        return key_name
