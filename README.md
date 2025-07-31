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