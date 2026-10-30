#!/usr/bin/env python3
"""Generate the restrictive agent profile from the checksummed Moby baseline."""

import hashlib
import json
from pathlib import Path

BASE_SHA256 = "6416b47770785a41ac59073cdc77d9fe98517df2799dc83ef207e622de3053f6"


def generate(baseline):
    if hashlib.sha256(baseline).hexdigest() != BASE_SHA256:
        raise ValueError("Unexpected Moby profile baseline")
    profile = json.loads(baseline)
    rules = []
    for rule in profile["syscalls"]:
        rule["names"] = [
            n
            for n in rule["names"]
            if n
            not in {
                "socketcall",
                "socketpair",
                "io_uring_setup",
                "io_uring_enter",
                "io_uring_register",
            }
        ]
        if not rule["names"]:
            continue
        if rule["names"] == ["socket"] and rule.get("args") == [
            {"index": 0, "value": 3, "op": "SCMP_CMP_LT"}
        ]:
            rule["args"] = [{"index": 0, "value": 2, "op": "SCMP_CMP_EQ"}]
        rules.append(rule)
    # Connected stream pairs support asyncio/subprocess IPC but cannot be
    # reconnected to a filesystem socket. Datagram pairs can, and stay denied.
    rules.append(
        {
            "names": ["socketpair"],
            "action": "SCMP_ACT_ALLOW",
            "args": [
                {"index": 0, "value": 1, "op": "SCMP_CMP_EQ"},
                {"index": 1, "value": 15, "valueTwo": 1, "op": "SCMP_CMP_MASKED_EQ"},
            ],
        }
    )
    profile["syscalls"] = rules
    return profile


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    print(json.dumps(generate((root / "security/vendor/moby-default.json").read_bytes()), indent=2))
