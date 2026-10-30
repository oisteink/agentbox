#!/usr/bin/env python3
"""Real rootless proxy checks against a controlled network-namespace endpoint."""

import json
import os
import pwd
import shutil
import socket
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import yaml


def run(*args, check=True, **kw):
    return subprocess.run(args, text=True, capture_output=True, check=check, **kw)


def main():
    if os.geteuid() != 0 or socket.gethostname() != "agentbox-lab":
        raise SystemExit("Run only as root in agentbox-lab")
    uid = pwd.getpwnam("agentbox").pw_uid
    token = uuid.uuid4().hex[:6]
    prefix = "ab-proxy-" + token
    namespace = "ab-" + token
    veth = "abh" + token
    peer = "abp" + token
    base = Path(tempfile.mkdtemp(prefix=prefix, dir="/var/lib/agentbox"))
    os.chmod(base, 0o755)
    containers = []
    networks = []
    fixture = None
    result = {}
    app_environment = None
    app_project = None
    app_root = None
    hosts_before = None

    def docker(*args, check=True, **kw):
        return run(
            "runuser",
            "-u",
            "agentbox",
            "--",
            "env",
            "-i",
            "PATH=/usr/bin:/bin",
            "HOME=/var/lib/agentbox",
            f"XDG_RUNTIME_DIR=/run/user/{uid}",
            "docker",
            "--host",
            f"unix:///run/user/{uid}/docker.sock",
            *args,
            check=check,
            **kw,
        )

    def client(*args, check=True):
        return docker(
            "run",
            "--rm",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--network",
            networks[0],
            "--dns",
            "93.184.216.34",
            "--mount",
            f"type=bind,src={base}/cert.pem,dst=/fixture-ca.pem,readonly",
            "agentbox-dev:lab",
            *args,
            check=check,
            timeout=30,
        )

    try:
        # A synthetic globally-routable address is assigned only inside the
        # endpoint namespace. No production policy exception is introduced.
        run("ip", "netns", "add", namespace)
        run("ip", "link", "add", veth, "type", "veth", "peer", "name", peer)
        run("ip", "link", "set", peer, "netns", namespace)
        run("ip", "address", "add", "198.18.241.1/30", "dev", veth)
        run("ip", "link", "set", veth, "up")
        run(
            "ip", "netns", "exec", namespace, "ip", "address", "add", "198.18.241.2/30", "dev", peer
        )
        run("ip", "netns", "exec", namespace, "ip", "link", "set", peer, "up")
        run("ip", "netns", "exec", namespace, "ip", "link", "set", "lo", "up")
        run(
            "ip",
            "netns",
            "exec",
            namespace,
            "ip",
            "address",
            "add",
            "93.184.216.34/32",
            "dev",
            "lo",
        )
        run("ip", "route", "add", "93.184.216.34/32", "via", "198.18.241.2", "dev", veth)
        run(
            "ip", "netns", "exec", namespace, "ip", "route", "add", "default", "via", "198.18.241.1"
        )
        run(
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=allowed.agentbox.test",
            "-addext",
            "subjectAltName=DNS:allowed.agentbox.test",
            "-keyout",
            str(base / "key.pem"),
            "-out",
            str(base / "cert.pem"),
        )
        os.chmod(base / "cert.pem", 0o644)
        events = (base / "events.jsonl").open("w")
        fixture = subprocess.Popen(
            [
                "ip",
                "netns",
                "exec",
                namespace,
                "python3",
                str(Path(__file__).with_name("fixture.py")),
                str(base / "cert.pem"),
                str(base / "key.pem"),
            ],
            stdout=events,
            stderr=events,
        )
        for _ in range(50):
            if '"ready"' in (base / "events.jsonl").read_text():
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Fixture did not start")
        control = run(
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--noproxy",
            "*",
            "--resolve",
            "allowed.agentbox.test:443:93.184.216.34",
            "--cacert",
            str(base / "cert.pem"),
            "https://allowed.agentbox.test/",
            timeout=10,
        )
        assert "agentbox-controlled-endpoint" in control.stdout
        result["control_https"] = True

        (base / "hosts").write_text(
            "93.184.216.34 allowed.agentbox.test\n127.0.0.1 internal.agentbox.test\n"
        )
        (base / "squid.conf").write_text("""http_port 172.30.242.2:3128
visible_hostname agentbox-lab-proxy
pid_filename /tmp/squid.pid
cache_log /dev/stderr
cache_store_log none
logformat safe %ts.%03tu %>a %Ss %>Hs %rm %ru
access_log stdio:/dev/stdout safe
cache deny all
hosts_file /etc/squid/agentbox-hosts
dns_nameservers 127.0.0.1
acl CONNECT method CONNECT
acl ports80 port 80
acl ports443 port 443
acl permitted_ports port 80 443
acl prohibited dst 0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.0.0.0/24 192.0.2.0/24 192.168.0.0/16 198.18.0.0/15 198.51.100.0/24 203.0.113.0/24 224.0.0.0/4 240.0.0.0/4 ::/0
acl allowed dstdomain -n allowed.agentbox.test
acl internal_name dstdomain -n internal.agentbox.test
acl known dstdomain -n allowed.agentbox.test internal.agentbox.test
http_access deny !permitted_ports
http_access deny CONNECT !ports443
http_access deny !CONNECT !ports80
http_access deny !known
http_access deny prohibited
http_access allow allowed ports443 CONNECT
http_access allow internal_name ports443 CONNECT
http_access deny all
""")
        for name in ("hosts", "squid.conf"):
            os.chmod(base / name, 0o644)
        for suffix, options in (
            (
                "inside",
                [
                    "--internal",
                    "--subnet",
                    "172.30.242.0/28",
                    "-o",
                    "com.docker.network.bridge.gateway_mode_ipv4=isolated",
                ],
            ),
            ("outside", []),
        ):
            name = prefix + "-" + suffix
            docker("network", "create", *options, name)
            networks.append(name)

        proxy = prefix + "-proxy"
        docker(
            "create",
            "--name",
            proxy,
            "--user",
            "proxy",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--cpus",
            "0.5",
            "--memory",
            "256m",
            "--pids-limit",
            "128",
            "--network",
            f"name={networks[0]},ip=172.30.242.2",
            "--network",
            f"name={networks[1]},gw-priority=1",
            "--sysctl",
            "net.ipv4.ip_forward=0",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,noexec,mode=1777",
            "--mount",
            f"type=bind,src={base}/squid.conf,dst=/etc/squid/squid.conf,readonly",
            "--mount",
            f"type=bind,src={base}/hosts,dst=/etc/squid/agentbox-hosts,readonly",
            "agentbox-proxy:lab",
        )
        containers.append(proxy)
        docker("start", proxy)
        for _ in range(15):
            check = client(
                "curl",
                "-sS",
                "--max-time",
                "2",
                "--proxy",
                "http://172.30.242.2:3128",
                "--cacert",
                "/fixture-ca.pem",
                "https://allowed.agentbox.test/",
                check=False,
            )
            if check.returncode == 0 and "agentbox-controlled-endpoint" in check.stdout:
                break
            time.sleep(0.2)
        else:
            raise RuntimeError(
                "Proxy failed: " + docker("logs", proxy).stdout + docker("logs", proxy).stderr
            )
        result["allowed_https"] = True

        for label, url in (
            ("denied_domain", "https://denied.agentbox.test/"),
            ("denied_http_port_pair", "http://allowed.agentbox.test/"),
            ("denied_subdomain", "https://sub.allowed.agentbox.test/"),
            ("denied_ip_literal", "https://93.184.216.34/"),
            ("denied_internal_resolution", "https://internal.agentbox.test/"),
        ):
            denied = client(
                "curl",
                "--fail",
                "-sS",
                "--max-time",
                "3",
                "--proxy",
                "http://172.30.242.2:3128",
                "--cacert",
                "/fixture-ca.pem",
                url,
                check=False,
            )
            assert denied.returncode != 0, (label, denied.stdout)
            result[label] = {"blocked": True, "error": denied.stderr.strip()}

        direct = client(
            "curl",
            "--fail",
            "-sS",
            "--max-time",
            "3",
            "--noproxy",
            "*",
            "http://93.184.216.34/",
            check=False,
        )
        assert direct.returncode != 0
        result["direct_http_blocked"] = True

        before = (base / "events.jsonl").read_text().count('"kind": "dns"')
        dns = client("dig", "+time=1", "+tries=1", "outside.agentbox.test", check=False)
        after = (base / "events.jsonl").read_text().count('"kind": "dns"')
        result["internal_dns"] = {
            "exit": dns.returncode,
            "observed_external_queries": after - before,
        }
        assert after == before, "Embedded Docker resolver leaked DNS to external fixture"

        # Prove the fixture DNS is alive from the externally connected proxy namespace.
        dns_control = docker(
            "run",
            "--rm",
            "--network",
            networks[1],
            "agentbox-dev:lab",
            "dig",
            "+time=1",
            "+tries=1",
            "@93.184.216.34",
            "control.agentbox.test",
        )
        assert "NXDOMAIN" in dns_control.stdout
        assert (base / "events.jsonl").read_text().count('"kind": "dns"') > after
        result["dns_control"] = True

        # Exercise the installed production policy generator and CLI against
        # the same live endpoints, without weakening address validation.
        developer = pwd.getpwnam("developer")

        def app(*args, check=True):
            return run(
                "runuser",
                "-u",
                "developer",
                "--",
                "env",
                "HOME=/home/developer",
                "/usr/local/bin/agentbox",
                *args,
                check=check,
                timeout=120,
            )

        app_root = Path(tempfile.mkdtemp(prefix="agentbox-proxy-app-", dir="/home/developer"))
        os.chown(app_root, developer.pw_uid, developer.pw_gid)
        shutil.copyfile(base / "cert.pem", app_root / "cert.pem")
        os.chown(app_root / "cert.pem", developer.pw_uid, developer.pw_gid)
        hosts_before = Path("/etc/hosts").read_text()
        endpoint_hosts = "\n93.184.216.34 allowed.agentbox.test downloads.agentbox.test\n"
        Path("/etc/hosts").write_text(hosts_before + endpoint_hosts)
        app_project = "proxy-project-" + token
        app_environment = "proxy-env-" + token
        app("project", "add", app_project, "--path", str(app_root))
        config = {
            "name": app_environment,
            "image": "agentbox-dev:local",
            "command": ["bash"],
            "mounts": [{"project": app_project, "target": "/workspace"}],
            "network": {
                "allow": [
                    {"host": "allowed.agentbox.test", "port": 443},
                    {"host": "downloads.agentbox.test", "port": 80},
                ]
            },
            "resources": {"cpus": 0.5, "memory": "256m", "pids": 64},
        }
        cfg_path = app_root / "environment.yaml"
        cfg_path.write_text(yaml.safe_dump(config))
        os.chown(cfg_path, developer.pw_uid, developer.pw_gid)
        started = json.loads(app("start", app_environment, "--config", str(cfg_path)).stdout)
        production_request = (
            "exec",
            app_environment,
            "--",
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--max-time",
            "5",
            "--cacert",
            "/workspace/cert.pem",
            "https://allowed.agentbox.test/?private-query=do-not-log",
        )
        assert "agentbox-controlled-endpoint" in app(*production_request).stdout
        result["installed_cli_allowed_https"] = True
        plain = app(
            "exec",
            app_environment,
            "--",
            "curl",
            "--fail",
            "--silent",
            "--max-time",
            "5",
            "http://downloads.agentbox.test/",
        )
        assert "agentbox-controlled-endpoint" in plain.stdout
        result["installed_cli_allowed_http"] = True
        cross_pair = app(
            "exec",
            app_environment,
            "--",
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--max-time",
            "5",
            "http://allowed.agentbox.test/",
            check=False,
        )
        assert cross_pair.returncode != 0 and "403" in cross_pair.stdout + cross_pair.stderr
        result["installed_cli_port_pair_enforced"] = True
        denied = app(
            "exec",
            app_environment,
            "--",
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--max-time",
            "5",
            "https://denied.agentbox.test/",
            check=False,
        )
        assert denied.returncode != 0 and "403" in denied.stdout + denied.stderr
        result["installed_cli_denied_domain"] = True

        # A post-start DNS rebind must not change the address Squid connects to.
        Path("/etc/hosts").write_text(
            hosts_before + "\n127.0.0.1 allowed.agentbox.test\n"
            "93.184.216.34 downloads.agentbox.test\n"
        )
        assert "agentbox-controlled-endpoint" in app(*production_request).stdout
        result["installed_cli_dns_pinning"] = True
        Path("/etc/hosts").write_text(hosts_before + endpoint_hosts)
        access_log = app("logs", app_environment, "--proxy").stdout
        assert "allowed.agentbox.test" in access_log and "private-query" not in access_log
        result["installed_cli_proxy_log_minimized"] = True
        docker("stop", "--time", "2", started["resources"]["proxy"])
        assert app(*production_request, check=False).returncode != 0
        result["installed_cli_proxy_failure_blocks"] = True
        app("stop", app_environment)
        app("start", app_environment, "--config", str(cfg_path))

        # Changing host addresses invalidates the stored destination exclusions.
        run("ip", "address", "add", "198.18.244.1/32", "dev", "lo")
        try:
            for _ in range(30):
                status = json.loads(app("status").stdout)[app_environment]["status"]
                if status == "stopped-host-address-change":
                    break
                time.sleep(0.2)
            else:
                raise AssertionError("Host address guard did not stop environment")
            result["installed_cli_address_guard"] = True
        finally:
            run("ip", "address", "del", "198.18.244.1/32", "dev", "lo")

        docker("stop", "--time", "2", proxy)
        down = client(
            "curl",
            "--fail",
            "-sS",
            "--max-time",
            "3",
            "--proxy",
            "http://172.30.242.2:3128",
            "https://allowed.agentbox.test/",
            check=False,
        )
        assert down.returncode != 0
        result["proxy_down_blocks"] = True
    finally:
        if app_environment:
            app("remove", app_environment, check=False)
        if app_project:
            app("project", "revoke", app_project, check=False)
        if hosts_before is not None:
            Path("/etc/hosts").write_text(hosts_before)
        if app_root:
            shutil.rmtree(app_root)
        for name in reversed(containers):
            result["proxy_logs"] = docker("logs", name, check=False).stdout[-3000:]
            docker("rm", "-f", name, check=False)
        for network in reversed(networks):
            docker("network", "rm", network, check=False)
        if fixture:
            fixture.terminate()
            fixture.wait(timeout=5)
        if (base / "events.jsonl").exists():
            result["fixture_events"] = (base / "events.jsonl").read_text()
        run("ip", "link", "del", veth, check=False)
        run("ip", "netns", "del", namespace, check=False)
        shutil.rmtree(base)
        print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
