# ed-fc-cargo-tracker-lib

A backend plugin for EDMC that tracks the cargo state of a fleet carrier in real time.

This plugin maintains an up-to-date view of carrier cargo and exposes it for other plugins to read or modify via a shared interface.

Useful for coordination, automation, or any plugin that needs consistent access to carrier inventory.

Designed as a shared cargo state tracker for fleet carriers in Elite Dangerous, enabling other EDMC plugins to synchronize, monitor, or modify inventory data safely and efficiently.

## Example usage:

```
def report_all(call_sign: str | None, cargo: dict[str, int]):
    print(f"Cargo status for carrier {call_sign or 'unknown'}:")
    for name, count in cargo.items():
        print(f" - {name}: {count}")
    return False  # No modification

fleetcarriercargo.FleetCarrierCargo.inventory(report_all)
```

Another example, which subscribes to "on cargo changed":

```
import fleetcarriercargo

def process_cargo(cargo: dict[str, int]):
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