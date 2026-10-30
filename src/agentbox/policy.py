"""Resolve destinations once and pin public IPv4 addresses in Squid's hosts file."""

import hashlib
import ipaddress
import json
import socket

from .errors import AgentboxError

PROHIBITED = (
    "0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 "
    "172.16.0.0/12 192.0.0.0/24 192.0.2.0/24 192.168.0.0/16 "
    "198.18.0.0/15 198.51.100.0/24 203.0.113.0/24 224.0.0.0/4 240.0.0.0/4 ::/0"
)


def public_address(address):
    return address.is_global and not any(
        (
            address.is_multicast,
            address.is_reserved,
            address.is_unspecified,
            address.is_loopback,
            address.is_link_local,
            getattr(address, "is_site_local", False),
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
            raise AgentboxError(f"An IPv4 address is required in this MVP: {host}")
        pinned[host] = ipv4[0]
    return pinned


def render(rules, pinned, proxy_ip, local_addresses):
    ipaddress.IPv4Address(proxy_ip)
    if {r.host for r in rules} != set(pinned):
        raise AgentboxError("Policy names and pinned destinations disagree")
    for address in pinned.values():
        if not public_address(ipaddress.IPv4Address(address)):
            raise AgentboxError("Proxy destinations must be public IPv4 addresses")
    lines = [
        f"http_port {proxy_ip}:3128",
        "visible_hostname agentbox",
        "pid_filename /tmp/squid.pid",
        "cache_log /dev/stderr",
        "cache_store_log none",
        # Destination + outcome only. Never log URL paths, queries or authorization fields.
        "logformat safe %ts.%03tu %Ss %>Hs %rm %>rd",
        "access_log stdio:/dev/stdout safe",
        "cache deny all",
        "hosts_file /etc/squid/agentbox-hosts",
        "dns_nameservers 127.0.0.1",
        "acl CONNECT method CONNECT",
        "acl http_port port 80",
        "acl tls_port port 443",
        "acl permitted_ports port 80 443",
        f"acl prohibited dst {PROHIBITED}",
    ]
    if local_addresses:
        validated = " ".join(str(ipaddress.ip_address(a)) for a in sorted(local_addresses))
        lines.append(f"acl host_addresses dst {validated}")
    for index, rule in enumerate(rules):
        lines.extend(
            [f"acl host{index} dstdomain -n {rule.host}", f"acl port{index} port {rule.port}"]
        )
    lines.extend(
        [
            "http_access deny !permitted_ports",
            "http_access deny CONNECT !tls_port",
            "http_access deny !CONNECT !http_port",
        ]
    )
    if rules:
        lines.append("acl known dstdomain -n " + " ".join(sorted(pinned)))
        lines.append("http_access deny !known")
        lines.append("http_access deny prohibited")
        if local_addresses:
            lines.append("http_access deny host_addresses")
        for index, rule in enumerate(rules):
            method = "CONNECT" if rule.port == 443 else "!CONNECT"
            lines.append(f"http_access allow host{index} port{index} {method}")
    lines.append("http_access deny all")
    configuration = "\n".join(lines) + "\n"
    hosts = "".join(f"{address} {host}\n" for host, address in sorted(pinned.items()))
    digest = hashlib.sha256(json.dumps([configuration, hosts], sort_keys=True).encode()).hexdigest()
    return configuration, hosts, digest
