"""Stop environments when host addresses change. Runs outside agent namespaces."""

import os
import sys
import time

from .control import Control
from .runtime import local_addresses
from .settings import load_settings


def main():
    settings = load_settings()
    if os.getuid() != settings["service_uid"]:
        raise SystemExit("Address guard must run as agentbox")
    control = Control(settings)
    while True:
        try:
            with control.store.locked() as data:
                control.verified(data)
                addresses = local_addresses()
                for name, environment in data["environments"].items():
                    if (
                        environment["host_addresses"] != addresses
                        and environment["status"] != "stopped-host-address-change"
                    ):
                        control.stop(data, name)
                        environment["status"] = "stopped-host-address-change"
                        print(f"Stopped {name}: host addresses changed", flush=True)
        except Exception as exc:
            # Do not dump state or requests into the system journal.
            print(f"Address guard failed: {type(exc).__name__}", file=sys.stderr, flush=True)
            raise SystemExit(1) from None
        time.sleep(1)
