import socket

import pytest

from agentbox.config import Rule
from agentbox.errors import AgentboxError
from agentbox.policy import render, resolve


def resolver(*addresses):
    return lambda *args: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, 443)) for a in addresses]


@pytest.mark.parametrize(
    "addresses",
    [
        ("127.0.0.1",),
        ("10.0.0.2",),
        ("169.254.169.254",),
        ("93.184.216.34", "127.0.0.1"),
        ("::1",),
        ("224.0.0.1",),
        ("ff02::1",),
        ("fec0::abcd",),
    ],
)
def test_any_nonpublic_answer_rejects_entire_destination(addresses):
    with pytest.raises(AgentboxError):
        resolve([Rule("api.example.com", 443)], [], resolver(*addresses))


def test_host_public_address_is_rejected():
    with pytest.raises(AgentboxError):
        resolve([Rule("api.example.com", 443)], ["93.184.216.34"], resolver("93.184.216.34"))


def test_rules_do_not_form_cross_product():
    rules = [Rule("api.example.com", 443), Rule("downloads.example.com", 80)]
    config, hosts, digest = render(
        rules,
        {
            "api.example.com": "93.184.216.34",
            "downloads.example.com": "1.1.1.1",
        },
        "172.30.240.2",
        [],
    )
    assert "http_access allow host0 port0 CONNECT" in config
    assert "http_access allow host1 port1 !CONNECT" in config
    assert "hosts_file /etc/squid/agentbox-hosts" in config
    assert "93.184.216.34 api.example.com\n" in hosts
    assert config.index("http_access deny !known") < config.index("http_access deny prohibited")
    assert "%ru" not in config
    assert len(digest) == 64


def test_empty_policy_denies_everything():
    config, hosts, _ = render([], {}, "172.30.240.2", [])
    assert "http_access allow" not in config
    assert config.endswith("http_access deny all\n")
    assert hosts == ""
