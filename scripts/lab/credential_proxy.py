#!/usr/bin/env python3
"""Installed Go-proxy acceptance checks; synthetic tokens, disposable VM only."""

import io
import json
import os
import pwd
import shutil
import socket
import subprocess
import tarfile
import tempfile
import time
import uuid
from pathlib import Path

import yaml


def run(*args, check=True, **kwargs):
    result = subprocess.run(
        args, text=True, capture_output=True, check=False, timeout=120, **kwargs
    )
    if check and result.returncode:
        raise RuntimeError("Lab command failed: " + result.stderr.strip())
    return result


def main():
    if os.geteuid() != 0 or socket.gethostname() != "agentbox-lab":
        raise SystemExit("Run as root only in disposable agentbox-lab")
    service, operator = pwd.getpwnam("agentbox"), pwd.getpwnam("developer")
    suffix = uuid.uuid4().hex[:6]
    namespace, veth, peer = "abc" + suffix, "abh" + suffix, "abp" + suffix
    base = Path(tempfile.mkdtemp(prefix="credential-fixture-"))
    base.chmod(0o755)
    project = Path(tempfile.mkdtemp(prefix="credential-project-", dir="/home/developer"))
    os.chown(project, operator.pw_uid, operator.pw_gid)
    names = ["credential-first-" + suffix, "credential-second-" + suffix]
    registered = "credential-project-" + suffix
    settings_path = Path("/etc/agentbox/settings.json")
    settings_before = settings_path.read_text()
    hosts_before = Path("/etc/hosts").read_text()
    fixture = None
    result = {
        "scope": "installed Agentbox, actual Go container, rootless Docker in Ubuntu lab",
        "checks": {},
    }
    checks = result["checks"]

    def docker(*args, check=True, source=None):
        return run(
            "runuser",
            "-u",
            "agentbox",
            "--",
            "env",
            "HOME=/var/lib/agentbox",
            f"XDG_RUNTIME_DIR=/run/user/{service.pw_uid}",
            "docker",
            "--host",
            f"unix:///run/user/{service.pw_uid}/docker.sock",
            *args,
            check=check,
            input=source,
        )

    def app(*args, token="synthetic-token-a", check=True):
        env = os.environ.copy()
        env.pop("FIXTURE_TOKEN", None)
        env.pop("EMPTY_TOKEN", None)
        if token is not None:
            env["FIXTURE_TOKEN"] = token
        return run(
            "runuser",
            "-u",
            "developer",
            "--",
            "env",
            "HOME=/home/developer",
            "/usr/local/bin/abx",
            *args,
            check=check,
            env=env,
        )

    def http_events():
        return [
            json.loads(line)
            for line in (base / "events.jsonl").read_text().splitlines()
            if line.startswith("{") and json.loads(line).get("kind") == "http"
        ]

    placeholders = {}

    def request(name, url="https://allowed.agentbox.test/", *extra, check=True):
        credential_headers = ("authorization:", "context7_api_key:", "context7-api-key:")
        explicit = any(str(value).lower().startswith(credential_headers) for value in extra)
        if url.startswith("https://allowed.agentbox.test/") and not explicit:
            extra = ("-H", "Authorization: " + placeholders[name], *extra)
        return app(
            "exec", name, "--", "curl", "--fail", "-sS", "--max-time", "8", *extra, url, check=check
        )

    try:
        for args in [
            ("netns", "add", namespace),
            ("link", "add", veth, "type", "veth", "peer", "name", peer),
            ("link", "set", peer, "netns", namespace),
            ("address", "add", "198.18.241.1/30", "dev", veth),
            ("link", "set", veth, "up"),
            ("netns", "exec", namespace, "ip", "address", "add", "198.18.241.2/30", "dev", peer),
            ("netns", "exec", namespace, "ip", "link", "set", peer, "up"),
            ("netns", "exec", namespace, "ip", "link", "set", "lo", "up"),
            ("netns", "exec", namespace, "ip", "address", "add", "93.184.216.34/32", "dev", "lo"),
            ("route", "add", "93.184.216.34/32", "via", "198.18.241.2", "dev", veth),
            ("netns", "exec", namespace, "ip", "route", "add", "default", "via", "198.18.241.1"),
        ]:
            run("ip", *args)
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
            "/CN=Agentbox lab fixture",
            "-addext",
            "basicConstraints=critical,CA:TRUE",
            "-addext",
            "keyUsage=critical,digitalSignature,keyEncipherment,keyCertSign,cRLSign",
            "-addext",
            "subjectAltName=DNS:allowed.agentbox.test,DNS:tunnel.agentbox.test,DNS:denied.agentbox.test",
            "-keyout",
            str(base / "key.pem"),
            "-out",
            str(base / "cert.pem"),
        )
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
            raise RuntimeError("fixture did not start")
        control = run(
            "curl",
            "--fail",
            "-sS",
            "--noproxy",
            "*",
            "--resolve",
            "allowed.agentbox.test:443:93.184.216.34",
            "--cacert",
            str(base / "cert.pem"),
            "https://allowed.agentbox.test/",
        )
        assert "controlled-endpoint" in control.stdout
        checks["positive_fixture_control"] = True
        # Only the lab derivative trusts this synthetic upstream root. No production bypass.
        context = io.BytesIO()
        with tarfile.open(fileobj=context, mode="w") as archive:
            data = b"FROM agentbox-proxy:local\nUSER 0\nCOPY cert.pem /fixture.pem\nRUN cat /fixture.pem >> /etc/ssl/certs/ca-certificates.crt\nUSER 10001:10001\n"
            info = tarfile.TarInfo("Dockerfile")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
            archive.add(base / "cert.pem", arcname="cert.pem")
        # Binary tar needs a binary subprocess, not the text helper.
        subprocess.run(
            [
                "runuser",
                "-u",
                "agentbox",
                "--",
                "env",
                "HOME=/var/lib/agentbox",
                f"XDG_RUNTIME_DIR=/run/user/{service.pw_uid}",
                "docker",
                "--host",
                f"unix:///run/user/{service.pw_uid}/docker.sock",
                "build",
                "-t",
                "agentbox-proxy:trusted-lab",
                "-",
            ],
            input=context.getvalue(),
            capture_output=True,
            check=True,
            timeout=120,
        )
        settings = json.loads(settings_before)
        settings["proxy_image"] = "agentbox-proxy:trusted-lab"
        settings_path.write_text(json.dumps(settings))
        Path("/etc/hosts").write_text(
            hosts_before
            + "\n93.184.216.34 allowed.agentbox.test tunnel.agentbox.test denied.agentbox.test\n"
        )
        app("project", "add", registered, "--path", str(project))
        configs = []
        for index, name in enumerate(names):
            data = {
                "name": name,
                "image": "agentbox-dev:local",
                "command": ["bash"],
                "mounts": [{"project": registered, "target": "/workspace"}],
                "network": {
                    "allow": [
                        {"host": "allowed.agentbox.test", "port": 443},
                        {"host": "allowed.agentbox.test", "port": 80},
                        {"host": "tunnel.agentbox.test", "port": 443},
                    ]
                },
                "credentials": [
                    {
                        "host": "allowed.agentbox.test",
                        "port": 443,
                        "header": "Authorization",
                        "env": "hf_token=FIXTURE_TOKEN" if index == 0 else "FIXTURE_TOKEN",
                    }
                ],
            }
            path = project / (name + ".yaml")
            path.write_text(yaml.safe_dump(data))
            os.chown(path, operator.pw_uid, operator.pw_gid)
            started = json.loads(
                app(
                    "start", str(path), token="synthetic-token-" + ("a" if index == 0 else "b")
                ).stdout
            )
            client_variable = "hf_token" if index == 0 else "FIXTURE_TOKEN"
            placeholders[name] = app("exec", name, "--", "printenv", client_variable).stdout.strip()
            assert placeholders[name] == started["placeholders"][client_variable]
            if index == 0:
                assert (
                    app("exec", name, "--", "printenv", "FIXTURE_TOKEN", check=False).returncode
                    != 0
                )
            assert placeholders[name].startswith("abx-") and "synthetic" not in placeholders[name]
            configs.append((path, data, started))
        assert len(set(placeholders.values())) == 2
        checks["generated_agent_environment_placeholders"] = True
        first = names[0]
        for name, expected in zip(names, ("synthetic-token-a", "synthetic-token-b"), strict=True):
            response = request(name, "https://allowed.agentbox.test/", "-v", check=False)
            if response.returncode:
                result["failed_client"] = response.stdout + response.stderr
                state = json.loads(app("status").stdout)[name]
                result["failed_proxy_logs"] = docker(
                    "logs", state["resources"]["proxy"], check=False
                ).stdout
                diagnostic = docker(
                    "run",
                    "--rm",
                    "--network",
                    state["resources"]["outside"],
                    "--mount",
                    f"type=bind,src={base}/cert.pem,dst=/fixture.pem,readonly",
                    "agentbox-dev:lab",
                    "curl",
                    "-v",
                    "--max-time",
                    "5",
                    "--noproxy",
                    "*",
                    "--resolve",
                    "allowed.agentbox.test:443:93.184.216.34",
                    "--cacert",
                    "/fixture.pem",
                    "https://allowed.agentbox.test/",
                    check=False,
                )
                result["outside_control"] = {
                    "exit": diagnostic.returncode,
                    "stderr": diagnostic.stderr,
                }
                raise AssertionError("initial proxied request failed; diagnostics recorded")
            assert "controlled-endpoint" in response.stdout
            assert http_events()[-1]["authorization"] == [expected]
        checks["two_environments_scoped_tokens"] = True
        for flags in [("-H", "Authorization: " + placeholders[first]), ("--http2",)]:
            request(first, "https://allowed.agentbox.test/", *flags)
            assert http_events()[-1]["authorization"] == ["synthetic-token-a"]
        checks["header_replace_and_http2"] = True
        for value in ("", "another-value"):
            request(first, "https://allowed.agentbox.test/", "-H", "Authorization: " + value)
            assert http_events()[-1]["authorization"] == ([value] if value else [])
        request(
            first,
            "https://allowed.agentbox.test/",
            "-H",
            "Authorization: Bearer " + placeholders[first],
        )
        assert http_events()[-1]["authorization"] == ["Bearer synthetic-token-a"]
        for value in (
            placeholders[first][:20],
            placeholders[names[1]],
            "prefix " + placeholders[first],
            placeholders[first] + " " + placeholders[first],
        ):
            before = len(http_events())
            assert (
                request(
                    first,
                    "https://allowed.agentbox.test/",
                    "-H",
                    "Authorization: " + value,
                    check=False,
                ).returncode
                != 0
            )
            assert len(http_events()) == before
        checks["exact_matching_no_unconditional_injection"] = True
        for url, flags in [
            (
                "https://allowed.agentbox.test/",
                ("-H", "Authorization: one", "-H", "aUtHoRiZaTiOn: two"),
            ),
            ("https://allowed.agentbox.test/", ("--http2", "-H", "Host: tunnel.agentbox.test")),
            ("https://denied.agentbox.test/", ()),
            ("https://sub.allowed.agentbox.test/", ()),
            ("https://93.184.216.34/", ()),
            ("https://allowed.agentbox.test:8443/", ()),
            ("http://93.184.216.34/", ("--noproxy", "*")),
        ]:
            before = len(http_events())
            assert request(first, url, *flags, check=False).returncode != 0
            assert len(http_events()) == before, (url, flags)
        checks["negative_requests_no_upstream_http"] = True
        # Prove the fixture really reflects TRACE before testing proxy rejection.
        reflection = run(
            "curl",
            "--fail",
            "-sS",
            "--noproxy",
            "*",
            "--resolve",
            "allowed.agentbox.test:443:93.184.216.34",
            "--cacert",
            str(base / "cert.pem"),
            "-X",
            "TRACE",
            "-H",
            "Authorization: fixture-control",
            "https://allowed.agentbox.test/",
        )
        assert "fixture-control" in reflection.stdout
        for flags in [
            ("-X", "TRACE"),
            ("-X", "TRACK"),
            ("-X", "REFLECT"),
            (
                "--http1.1",
                "--data-binary",
                "payload",
                "-H",
                "Transfer-Encoding: chunked",
                "-H",
                "Trailer: Authorization",
            ),
            ("--http2", "--data-binary", "payload", "-H", "Trailer: Authorization"),
        ]:
            before = len(http_events())
            response = request(first, "https://allowed.agentbox.test/", *flags, check=False)
            assert response.returncode != 0 and "synthetic-token" not in response.stdout
            assert len(http_events()) == before
        checks["reflection_methods_and_declared_trailers_blocked"] = True
        path, original, _ = configs[0]
        alias_config = json.loads(json.dumps(original))
        alias_config["credentials"][0]["header"] = "CONTEXT7_API_KEY"
        path.write_text(yaml.safe_dump(alias_config))
        app("proxy", "apply", str(path))
        request(
            first,
            "https://allowed.agentbox.test/",
            "-H",
            "Context7-Api-Key: " + placeholders[first],
        )
        assert http_events()[-1]["api_key"] == ["synthetic-token-a"]
        assert http_events()[-1]["api_key_alias"] == []
        for protocol in ("--http1.1", "--http2"):
            before = len(http_events())
            response = request(
                first,
                "https://allowed.agentbox.test/",
                protocol,
                "-H",
                "Context7-Api-Key: one",
                "-H",
                "CONTEXT7_API_KEY: two",
                check=False,
            )
            assert response.returncode != 0 and len(http_events()) == before
        path.write_text(yaml.safe_dump(original))
        app("proxy", "apply", str(path))
        checks["normalized_header_aliases"] = True
        multi = json.loads(json.dumps(original))
        multi["credentials"].append(multi["credentials"][0] | {"host": "tunnel.agentbox.test"})
        path.write_text(yaml.safe_dump(multi))
        app("proxy", "apply", str(path))
        request(
            first, "https://tunnel.agentbox.test/", "-H", "Authorization: " + placeholders[first]
        )
        assert http_events()[-1]["authorization"] == ["synthetic-token-a"]
        path.write_text(yaml.safe_dump(original))
        app("proxy", "apply", str(path))
        checks["one_placeholder_multiple_destinations"] = True
        request(first, "http://allowed.agentbox.test/")
        assert http_events()[-1]["authorization"] == []
        request(first, "https://tunnel.agentbox.test/")
        assert http_events()[-1]["authorization"] == []
        request(first, "https://allowed.agentbox.test/redirect", "-L")
        assert (
            http_events()[-1]["host"] == "tunnel.agentbox.test"
            and http_events()[-1]["authorization"] == []
        )
        checks["plain_http_tunnel_redirect"] = True
        # No token in config/state, agent environment or mounted private paths.
        state = json.loads(app("status").stdout)[first]
        agent_id = state["resources"]["agent"]
        metadata = json.loads(docker("container", "inspect", agent_id).stdout)[0]
        assert "synthetic-token" not in json.dumps(state) + json.dumps(metadata["Config"]["Env"])
        assert (
            app("exec", first, "--", "test", "-e", "/run/agentbox/ca.key", check=False).returncode
            != 0
        )
        fingerprint = app("exec", first, "--", "sha256sum", "/run/agentbox-ca/ca.pem").stdout
        app(
            "exec",
            first,
            "--",
            "sh",
            "-c",
            "mkdir -p /home/agent/.codex; echo preserved > /home/agent/.codex/lab-marker",
        )
        app("proxy", "apply", str(configs[0][0]), token="synthetic-token-rotated")
        request(first)
        assert http_events()[-1]["authorization"] == ["synthetic-token-rotated"]
        assert json.loads(app("status").stdout)[first]["resources"]["agent"] == agent_id
        assert (
            app("exec", first, "--", "cat", "/home/agent/.codex/lab-marker").stdout.strip()
            == "preserved"
        )
        assert (
            app("exec", first, "--", "sha256sum", "/run/agentbox-ca/ca.pem").stdout == fingerprint
        )
        assert (
            app("exec", first, "--", "printenv", "hf_token").stdout.strip() == placeholders[first]
        )
        checks["proxy_rotation_preserves_home_and_ca"] = True
        assert app("proxy", "apply", str(configs[0][0]), token=None, check=False).returncode != 0
        stopped = json.loads(app("status").stdout)[first]
        assert stopped["status"] == "proxy-stopped" and "proxy" not in stopped["resources"]
        # Direct docker exec observes the still-live agent without requiring a healthy proxy.
        assert (
            docker(
                "exec",
                agent_id,
                "curl",
                "--fail",
                "-sS",
                "--max-time",
                "2",
                "https://allowed.agentbox.test/",
                check=False,
            ).returncode
            != 0
        )
        checks["missing_token_removes_old_proxy"] = True
        checks["alias_and_short_form_source_lookup"] = True
        app("start", str(configs[0][0]))
        request(first)
        # Persisted pin survives host lookup change. Control-side apply rejects the new private IP.
        Path("/etc/hosts").write_text(
            hosts_before + "\n127.0.0.1 allowed.agentbox.test\n93.184.216.34 tunnel.agentbox.test\n"
        )
        request(first)
        assert app("proxy", "apply", str(configs[0][0]), check=False).returncode != 0
        Path("/etc/hosts").write_text(
            hosts_before
            + "\n93.184.216.34 allowed.agentbox.test tunnel.agentbox.test denied.agentbox.test\n"
        )
        app("start", str(configs[0][0]))
        checks["pinned_dns_and_private_resolution_rejected"] = True
        # Compare timestamps in the same VM while reading stdout incrementally.
        arguments = [
            "runuser",
            "-u",
            "developer",
            "--",
            "env",
            "HOME=/home/developer",
            "/usr/local/bin/abx",
            "exec",
            first,
            "--",
            "curl",
            "--fail",
            "-sSN",
            "--max-time",
            "20",
            "https://allowed.agentbox.test/stream",
        ]
        delays = []
        with subprocess.Popen(
            arguments, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        ) as process:
            for line in process.stdout:
                if line.startswith("data:"):
                    delays.append(time.monotonic() - float(line.split()[2]))
            assert process.wait(timeout=5) == 0
        assert len(delays) == 10 and max(delays) < 2
        checks["sse_delays_seconds"] = delays
        node = """
const http = require('http'), tls = require('tls');
const proxy = new URL(process.env.HTTPS_PROXY);
const timeout = setTimeout(() => process.exit(1), 8000);
const req = http.request({hostname: proxy.hostname, port: proxy.port, method: 'CONNECT', path: 'allowed.agentbox.test:443'});
req.on('error', () => process.exit(1));
req.on('connect', (res, socket) => {
  if (res.statusCode !== 200) process.exit(1);
  const secured = tls.connect({socket, servername: 'allowed.agentbox.test'}, () => {
    secured.write('GET / HTTP/1.1\\r\\nHost: allowed.agentbox.test\\r\\nConnection: close\\r\\n\\r\\n');
  });
  secured.on('error', () => process.exit(1));
  let data = '';
  secured.on('data', chunk => {
    data += chunk;
    if (data.includes('\\r\\n')) process.exit(/^HTTP\\/1\\.[01] 200/.test(data) ? 0 : 1);
  });
});
req.end();
"""
        app(
            "exec",
            first,
            "--",
            "python3",
            "-c",
            "import urllib.request;print(urllib.request.urlopen('https://allowed.agentbox.test/').status)",
        )
        app("exec", first, "--", "node", "-e", " ".join(node.splitlines()))
        checks["curl_python_node_ca"] = True
        # Explicit removal permits an ordinary tunnel; missing token did not.
        path, original, _ = configs[0]
        without_rule = dict(original, credentials=[])
        path.write_text(yaml.safe_dump(without_rule))
        app("proxy", "apply", str(path), token=None)
        request(first)
        assert http_events()[-1]["authorization"] == [placeholders[first]]
        path.write_text(yaml.safe_dump(original))
        app("proxy", "apply", str(path))
        request(first)
        assert http_events()[-1]["authorization"] == ["synthetic-token-a"]
        checks["explicit_rule_removal_and_restore"] = True
        # Valid chain, wrong upstream name: no HTTP may be forwarded.
        Path("/etc/hosts").write_text(
            Path("/etc/hosts").read_text() + "\n93.184.216.34 invalid.agentbox.test\n"
        )
        invalid = json.loads(json.dumps(original))
        invalid["network"]["allow"].append({"host": "invalid.agentbox.test", "port": 443})
        invalid["credentials"].append(
            {
                "host": "invalid.agentbox.test",
                "port": 443,
                "header": "Authorization",
                "env": original["credentials"][0]["env"],
            }
        )
        path.write_text(yaml.safe_dump(invalid))
        app("proxy", "apply", str(path))
        before = len(http_events())
        assert request(first, "https://invalid.agentbox.test/", check=False).returncode != 0
        assert len(http_events()) == before
        path.write_text(yaml.safe_dump(original))
        app("proxy", "apply", str(path))
        checks["upstream_name_validation"] = True
        logs = app("logs", first, "--proxy").stdout
        assert "synthetic-token" not in logs and "private-query" not in logs
        checks["safe_proxy_logs"] = True
        old_ca = app("exec", first, "--", "cat", "/run/agentbox-ca/ca.pem").stdout
        old_ca_path = project / "old-ca.pem"
        old_ca_path.write_text(old_ca)
        os.chown(old_ca_path, operator.pw_uid, operator.pw_gid)
        app("proxy", "rotate-ca", first)
        app("start", str(configs[0][0]))
        assert (
            app("exec", first, "--", "sha256sum", "/run/agentbox-ca/ca.pem").stdout != fingerprint
        )
        assert (
            app("exec", first, "--", "cat", "/home/agent/.codex/lab-marker").stdout.strip()
            == "preserved"
        )
        request(first)
        before = len(http_events())
        assert (
            request(
                first,
                "https://allowed.agentbox.test/",
                "--cacert",
                "/workspace/old-ca.pem",
                check=False,
            ).returncode
            != 0
        )
        assert len(http_events()) == before
        checks["ca_rotation_preserves_home"] = True
        # New environments accept absent/empty sources; availability changes
        # must remove the old proxy before requiring explicit recreation.
        empty_name = "credential-empty-" + suffix
        names.append(empty_name)
        empty_config = json.loads(json.dumps(configs[0][1]))
        empty_config["name"] = empty_name
        empty_config["credentials"].append(
            empty_config["credentials"][0] | {"header": "X-API-Key", "env": "EMPTY_TOKEN"}
        )
        empty_path = project / (empty_name + ".yaml")
        empty_path.write_text(yaml.safe_dump(empty_config))
        os.chown(empty_path, operator.pw_uid, operator.pw_gid)
        empty_state = json.loads(app("start", str(empty_path), token=None).stdout)
        assert empty_state["placeholders"] == {"hf_token": "", "EMPTY_TOKEN": ""}
        for variable in ("hf_token", "EMPTY_TOKEN"):
            assert app("exec", empty_name, "--", "printenv", variable).stdout.strip() == ""
        placeholders[empty_name] = ""
        request(empty_name)
        assert http_events()[-1]["authorization"] == [] and http_events()[-1]["api_key"] == []
        proxy_metadata = json.loads(
            docker("container", "inspect", empty_state["resources"]["proxy"]).stdout
        )[0]
        assert not any(v.startswith("AGENTBOX_TOKEN_") for v in proxy_metadata["Config"]["Env"])
        checks["missing_sources_create_multiple_empty_client_variables"] = True
        assert app("proxy", "apply", str(empty_path), check=False).returncode != 0
        assert "proxy" not in json.loads(app("status").stdout)[empty_name]["resources"]
        app("remove", empty_name)
        active_state = json.loads(app("start", str(empty_path)).stdout)
        placeholders[empty_name] = active_state["placeholders"]["hf_token"]
        assert placeholders[empty_name] and active_state["placeholders"]["EMPTY_TOKEN"] == ""
        request(empty_name)
        assert http_events()[-1]["authorization"] == ["synthetic-token-a"]
        assert http_events()[-1]["api_key"] == []
        checks["active_and_empty_sources_share_destination"] = True
        app("stop", empty_name)
        before = len(http_events())
        assert app("start", str(empty_path), token="", check=False).returncode != 0
        stopped_empty = json.loads(app("status").stdout)[empty_name]
        assert (
            stopped_empty["status"] == "proxy-stopped" and "proxy" not in stopped_empty["resources"]
        )
        docker("container", "start", stopped_empty["resources"]["agent"])
        assert (
            docker(
                "exec",
                stopped_empty["resources"]["agent"],
                "curl",
                "--fail",
                "-sS",
                "--max-time",
                "2",
                "https://allowed.agentbox.test/",
                check=False,
            ).returncode
            != 0
        )
        assert len(http_events()) == before
        checks["availability_change_on_resume_removes_old_proxy"] = True
        app("remove", empty_name)
        recreated = json.loads(app("start", str(empty_path), token="").stdout)
        assert recreated["placeholders"] == {"hf_token": "", "EMPTY_TOKEN": ""}
        placeholders[empty_name] = ""
        request(empty_name)
        assert http_events()[-1]["authorization"] == []
        app("stop", empty_name)
        app("start", str(empty_path), token="")
        assert app("exec", empty_name, "--", "printenv", "hf_token").stdout.strip() == ""
        checks["empty_source_recreation_and_restart"] = True
        result["checks_passed"] = True
    finally:
        errors = []

        def cleanup(operation):
            try:
                operation()
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")

        for name in names:
            cleanup(lambda name=name: app("remove", name))
        # Setup can fail before registration; an absent registration is not a leak.
        try:
            entries = json.loads(app("project", "list").stdout)
            if registered in entries and entries[registered]["status"] != "revoked":
                cleanup(lambda: app("project", "revoke", registered))
        except Exception as exc:
            errors.append(f"project list: {exc}")
        cleanup(lambda: settings_path.write_text(settings_before))
        cleanup(lambda: Path("/etc/hosts").write_text(hosts_before))
        if fixture:
            cleanup(fixture.terminate)
            cleanup(lambda: fixture.wait(timeout=5))
            events.close()
        if run("ip", "link", "show", "dev", veth, check=False).returncode == 0:
            cleanup(lambda: run("ip", "link", "del", veth))
        try:
            if namespace in {
                line.split()[0] for line in run("ip", "netns", "list").stdout.splitlines()
            }:
                cleanup(lambda: run("ip", "netns", "del", namespace))
        except Exception as exc:
            errors.append(f"netns list: {exc}")
        if not errors:
            cleanup(lambda: shutil.rmtree(base))
            cleanup(lambda: shutil.rmtree(project))
        result["cleanup_errors"] = errors
        result["passed"] = bool(result.get("checks_passed")) and not errors
        print(json.dumps(result, indent=2, sort_keys=True))
        if errors:
            raise RuntimeError("Proxy lab cleanup failed: " + "; ".join(errors))


if __name__ == "__main__":
    main()
