# ed-fc-cargo-tracker-lib

A backend plugin for EDMC that tracks the cargo state of a fleet carrier in real time.

This plugin maintains an up-to-date view of carrier cargo and exposes it for other plugins to read or modify via a shared interface.

Useful for coordination, automation, or any plugin that needs consistent access to carrier inventory.

Designed as a shared cargo state tracker for fleet carriers in Elite Dangerous, enabling other EDMC plugins to synchronize, monitor, or modify inventory data safely and efficiently.

Note, keys are lower-cased and correspond "commodity" field in CAPI response like this:
```
 {
            "commodity": "Tritium",
            "originSystem": null,
            "mission": false,
            "qty": 106,
            "value": 5629978,
            "stolen": false,
            "locName": "Tritium"
},
```

## Example usage:

```
def report_all(call_sign: str | None, cargo: CargoTally):
    print(f"Cargo status for carrier {call_sign or 'unknown'}:")
    for name, count in cargo.items():
        print(f" - {name}: {count}")
    return False  # No modification

fleetcarriercargo.FleetCarrierCargo.inventory(report_all)
```

Another example, which subscribes to "on cargo changed":

```
import fleetcarriercargo

def process_cargo(cargo: CargoTally):
    # Do something with the cargo dictionary
    pass

def on_cargo_change():
    # Called when the cargo has changed
    print("Cargo changed!")
    # Request the current inventory and process it
    fleetcarriercargo.FleetCarrierCargo.inventory(
        lambda call_sign, cargo: process_cargo(cargo)
    )

# Register your handler to react when cargo changes
fleetcarriercargo.FleetCarrierCargo.add_on_cargo_change_handler(on_cargo_change)


```

To enable access to this plugin, add in your `load.py`

```
import sys
import os

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "ed-fc-cargo-tracker-lib")
)

```
