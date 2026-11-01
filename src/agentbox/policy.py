"""Resolve once and generate a token-free policy with pinned public IPv4 addresses."""

import hashlib
import ipaddress
import json
import re
import secrets
import socket

from .errors import AgentboxError

PROHIBITED = (
    "0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 "
    "172.16.0.0/12 192.0.0.0/24 192.0.2.0/24 192.168.0.0/16 "
    "198.18.0.0/15 198.51.100.0/24 203.0.113.0/24 224.0.0.0/4 240.0.0.0/4"
)


def public_address(address):
    return (
        address.is_global
        and not (
            address.version == 4
            and any(address in ipaddress.ip_network(block) for block in PROHIBITED.split())
        )
        and not any(
            (
                address.is_multicast,
                address.is_reserved,
                address.is_unspecified,
                address.is_loopback,
                address.is_link_local,
                getattr(address, "is_site_local", False),
            )
        )
    )


def resolve(rules, local_addresses, resolver=socket.getaddrinfo):
    pinned = {}
    local = {ipaddress.ip_address(address) for address in local_addresses}
    for host in sorted({rule.host for rule in rules}):
        try:
            answers = {
                ipaddress.ip_address(item[4][0])
                for item in resolver(host, 443, socket.AF_UNSPEC, socket.SOCK_STREAM)
            }
        except (OSError, ValueError) as exc:
            raise AgentboxError(f"Cannot resolve allowed destination: {host}") from exc
        if not answers or any(
            not public_address(address) or address in local for address in answers
        ):
            raise AgentboxError(f"Allowed name resolves to a prohibited or local address: {host}")
        ipv4 = sorted(str(address) for address in answers if address.version == 4)
        if not ipv4:
            raise AgentboxError(f"An IPv4 address is required: {host}")
        pinned[host] = ipv4[0]
    return pinned


def token_environment(environment, values):
    sources = {rule.source_env for rule in environment.credentials}
    if not isinstance(values, dict) or not set(values) <= sources:
        raise AgentboxError("Token variables are invalid or unexpected")
    for variable, value in values.items():
        if (
            not isinstance(value, str)
            or len(value.encode()) > 16384
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
        ):
            raise AgentboxError(f"Invalid token variable: {variable}")
    bindings = {c.client_env: c.source_env for c in environment.credentials}
    return {
        f"AGENTBOX_TOKEN_{index}": values[source]
        for index, (_, source) in enumerate(sorted(bindings.items()))
        if values.get(source, "")
    }


PLACEHOLDER = re.compile(r"abx-[0-9a-f]{64}\Z")


def placeholders(environment, values):
    bindings = {c.client_env: c.source_env for c in environment.credentials}
    return {
        client: "abx-" + secrets.token_hex(32) if values.get(source, "") else ""
        for client, source in sorted(bindings.items())
    }


def validate_placeholders(environment, mapping):
    required = {c.client_env for c in environment.credentials}
    if (
        not isinstance(mapping, dict)
        or not required <= set(mapping)
        or any(
            not isinstance(v, str) or (v and not PLACEHOLDER.fullmatch(v)) for v in mapping.values()
        )
        or len({v for v in mapping.values() if v}) != sum(bool(v) for v in mapping.values())
    ):
        raise AgentboxError(
            "Missing or invalid placeholder mapping; recreate environment for new token variables"
        )


def validate_token_availability(environment, mapping, values):
    if any(
        bool(mapping[c.client_env]) != bool(values.get(c.source_env, ""))
        for c in environment.credentials
    ):
        raise AgentboxError(
            "Token availability changed; proxy stopped. Recreate environment "
            "to update agent variables (remove deletes home/login)"
        )


def render(rules, pinned, proxy_ip, local_addresses, credentials=(), placeholders=None):
    ipaddress.IPv4Address(proxy_ip)
    if {r.host for r in rules} != set(pinned):
        raise AgentboxError("Policy names and pinned destinations disagree")
    for address in pinned.values():
        if not public_address(ipaddress.IPv4Address(address)) or address in local_addresses:
            raise AgentboxError("Proxy destinations must be public non-host IPv4 addresses")
    placeholders = placeholders or {}
    if any(c.client_env not in placeholders for c in credentials):
        raise AgentboxError("Missing token placeholder mapping")
    variables = {
        name: f"AGENTBOX_TOKEN_{i}"
        for i, name in enumerate(sorted({c.client_env for c in credentials}))
    }
    document = {
        "version": 3,
        "listen": f"{proxy_ip}:3128",
        "host_addresses": local_addresses,
        "destinations": [
            {
                "host": rule.host,
                "port": rule.port,
                "ip": pinned[rule.host],
                "credentials": [
                    {
                        "header": c.header,
                        "env": variables[c.client_env],
                        "placeholder": placeholders[c.client_env],
                    }
                    for c in credentials
                    if c.host == rule.host and c.port == rule.port
                ],
            }
            for rule in rules
        ],
    }
    configuration = json.dumps(document, sort_keys=True, indent=2) + "\n"
    return configuration, "", hashlib.sha256(configuration.encode()).hexdigest()
