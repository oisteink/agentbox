"""Service-user operations behind the fixed local sudo control entry point."""

import ipaddress
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from . import config, images, policy, projects
from .errors import AgentboxError
from .runtime import Docker, local_addresses
from .state import Store, atomic_json


@contextmanager
def defer_interrupts():
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT})
    try:
        yield
    except BaseException:
        try:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous)
        except KeyboardInterrupt:
            pass  # Preserve a mutation/cleanup failure over a queued interrupt.
        raise
    else:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


class Control:
    def __init__(self, settings):
        self.settings = settings
        self.store = Store(Path(settings["home"]) / "state")
        self.docker = Docker(settings["service_uid"], settings["home"])

    def save(self, data):
        atomic_json(self.store.root / "state.json", data)

    def verified(self, data):
        info = self.docker.verify(data.get("daemon_id"))
        data["daemon_id"] = info["ID"]
        return info

    def build_proxy(self, *, if_missing=False):
        image = self.settings["proxy_image"]
        details = images.lookup(self.docker, image)
        if if_missing and details is not None:
            return {"image": image}
        images.require_idle(self.docker, details)
        self.docker.mutate("build", "--tag", image, "/opt/agentbox/proxy", timeout=900)
        return {"image": image}

    def run(self, payload, tokens, *, tty=False):
        environment = config.parse(payload)
        name = environment.name
        identifier = None
        try:
            with defer_interrupts(), self.store.locked() as data:
                self.verified(data)
                if name in data["environments"]:
                    raise AgentboxError("Environment already exists; choose a new temporary name")
                try:
                    entry = self.start(data, payload, tokens)
                except Exception:
                    try:
                        self.remove(data, name)
                    except Exception:
                        raise AgentboxError(
                            "Temporary environment setup and cleanup failed; resources may remain"
                        ) from None
                    raise
                identifier = entry["resources"]["agent"]
                daemon_id = data["daemon_id"]
            return self.execute(name, identifier, list(environment.command), tty, daemon_id)
        finally:
            if identifier is not None:
                self.remove_temporary(name, identifier)

    def remove_temporary(self, name, identifier):
        try:
            with defer_interrupts(), self.store.locked() as current:
                self.verified(current)
                entry = current["environments"].get(name)
                if entry is not None:
                    if entry["resources"].get("agent") != identifier:
                        raise AgentboxError(
                            "Temporary environment name was reused; replacement kept"
                        )
                    self.remove(current, name)
        except Exception as exc:
            detail = str(exc) if isinstance(exc, AgentboxError) else type(exc).__name__
            raise AgentboxError(
                f"Temporary environment cleanup failed: {detail}. Check 'abx status'"
            ) from None

    def execute(self, name, identifier, command, tty, daemon_id):
        self.docker.verify(daemon_id)
        terminal = open("/dev/tty") if tty else None
        try:
            return self.docker.exec_stream(
                identifier, command, self.store.root / "environments" / name, terminal=terminal
            )
        finally:
            if terminal:
                terminal.close()

    def shell(self, request):
        name = config.name(request["name"])
        identifier = None
        try:
            with defer_interrupts(), self.store.locked() as data:
                self.verified(data)
                entry = data["environments"].get(name)
                if not entry or entry["status"] != "running":
                    raise AgentboxError("Environment is not running")
                persistent = entry["config"].get("persistent", True)
                if not persistent and entry.get("shell_active"):
                    raise AgentboxError(
                        "Non-persistent shell already claimed; after a hard interruption, "
                        f"use 'abx remove {name}' before starting again"
                    )
                if entry["host_addresses"] != local_addresses():
                    self.stop(data, name)
                    raise AgentboxError("Host addresses changed; remove and recreate explicitly")
                agent = entry["resources"]["agent"]
                if agent not in self.owned(data, name, "container"):
                    raise AgentboxError("Container ownership changed")
                command = [config.text(arg) for arg in entry["config"]["command"]]
                daemon_id = data["daemon_id"]
                if not persistent:
                    entry["shell_active"] = True
                    identifier = agent
                    self.save(data)
            if not persistent:
                notice = "abx: Non-persistent environment; removed when this shell exits.\n"
                if getattr(self.docker, "output", None):
                    self.docker.output("stderr", notice)
                else:
                    print(notice, file=sys.stderr, end="")
            return self.execute(name, agent, command, request.get("tty") is True, daemon_id)
        finally:
            if identifier is not None:
                self.remove_temporary(name, identifier)

    def labels(self, data, environment):
        return {"agentbox.installation": data["installation"], "agentbox.environment": environment}

    def label_args(self, data, environment, role):
        labels = self.labels(data, environment) | {"agentbox.role": role}
        return [item for key, value in labels.items() for item in ("--label", f"{key}={value}")]

    def owned(self, data, environment, kind):
        args = [kind, "ls", "-q", "--no-trunc"]
        if kind == "container":
            args.append("-a")
        for key, value in self.labels(data, environment).items():
            args.extend(["--filter", f"label={key}={value}"])
        identifiers = self.docker.run(*args).stdout.split()
        for identifier in identifiers:
            details = self.docker.inspect(kind, identifier)
            labels = details.get("Labels") if kind == "network" else details["Config"].get("Labels")
            if any((labels or {}).get(k) != v for k, v in self.labels(data, environment).items()):
                raise AgentboxError("Resource ownership labels disagree")
        return identifiers

    def stop(self, data, environment):
        for identifier in self.owned(data, environment, "container"):
            self.docker.mutate("container", "stop", "--time", "2", identifier)
        if environment in data["environments"]:
            data["environments"][environment]["status"] = "stopped"
        self.save(data)

    def remove(self, data, environment):
        self.stop(data, environment)
        for kind in ("container", "network"):
            for identifier in self.owned(data, environment, kind):
                self.docker.mutate(kind, "rm", identifier)
        data["environments"].pop(environment, None)
        self.save(data)
        directory = self.store.root / "environments" / environment
        if directory.exists():
            shutil.rmtree(directory)

    def project(self, data, action, request):
        if action == "list":
            return data["projects"]
        name = config.name(request["name"])
        if action == "prepare":
            path = Path(request["path"])
            if not path.is_absolute() or ".." in path.parts:
                raise AgentboxError("Invalid project path")
            previous = data["projects"].get(name)
            if previous and previous["path"] != str(path):
                raise AgentboxError("Project name is already registered to a different path")
            for other_name, other in data["projects"].items():
                other_path = Path(other["path"])
                if other_name != name and (
                    path == other_path or path in other_path.parents or other_path in path.parents
                ):
                    raise AgentboxError("Overlapping project registrations are unsupported in MVP")
            self.require_idle(data, name)
            data["projects"][name] = {
                "path": str(path),
                "identity": request["identity"],
                "status": "pending",
            }
            self.save(data)
            return data["projects"][name]
        entry = data["projects"].get(name)
        if not entry:
            raise AgentboxError("Unknown project")
        if action == "check":
            return dict(entry) | {
                "service_access_issues": projects.access_issues(
                    entry["path"], {self.settings["operator_uid"], self.settings["service_uid"]}
                )
            }
        self.require_idle(data, name)
        if action == "finish":
            root = projects.validate_root(entry["path"], self.settings["operator_uid"])
            if projects.identity(root) != entry["identity"]:
                raise AgentboxError("Project root changed")
            nodes = projects.scan(
                root, {self.settings["operator_uid"], self.settings["service_uid"]}
            )
            projects.apply_owned(
                root, nodes, self.settings["service_uid"], self.settings["operator_uid"]
            )
            entry["status"] = "active"
            return entry
        if action in ("prepare-revoke", "prepare-repair"):
            entry["status"] = "pending"
            self.save(data)
            if action == "prepare-repair":
                root = projects.validate_root(entry["path"], self.settings["operator_uid"])
                if projects.identity(root) != entry["identity"]:
                    raise AgentboxError("Project root changed")
                nodes = projects.scan(
                    root,
                    {self.settings["operator_uid"], self.settings["service_uid"]},
                    skip_inaccessible=True,
                )
                projects.apply_owned(
                    root, nodes, self.settings["service_uid"], self.settings["operator_uid"]
                )
            return entry
        if action == "revoked":
            if os.access(entry["path"], os.X_OK):
                raise AgentboxError("Project root still accessible; refusing to claim revocation")
            entry["status"] = "revoked"
            return entry
        raise AgentboxError("Unknown project operation")

    def require_idle(self, data, project):
        for name, environment in data["environments"].items():
            if any(m["project"] == project for m in environment["config"]["mounts"]):
                for identifier in self.owned(data, name, "container"):
                    if self.docker.inspect("container", identifier)["State"]["Running"]:
                        raise AgentboxError(
                            f"Stop every environment using this project first: {name}"
                        )

    def subnets(self):
        networks = self.docker.run("network", "ls", "-q").stdout.split()
        occupied = []
        for identifier in networks:
            for entry in self.docker.inspect("network", identifier)["IPAM"].get("Config") or []:
                if entry.get("Subnet"):
                    occupied.append(ipaddress.ip_network(entry["Subnet"]))
        routes = __import__("subprocess").run(
            ["/usr/sbin/ip", "-j", "route", "show", "table", "all"],
            check=True,
            text=True,
            capture_output=True,
        )
        for route in json.loads(routes.stdout):
            if route.get("dst") and route["dst"] != "default":
                occupied.append(ipaddress.ip_network(route["dst"], strict=False))
        available = []
        for subnet in ipaddress.ip_network(self.settings["network_pool"]).subnets(new_prefix=28):
            if not any(subnet.version == old.version and subnet.overlaps(old) for old in occupied):
                available.append(subnet)
                if len(available) == 2:
                    return available
        raise AgentboxError(
            f"No two collision-free /28 subnets available in network_pool "
            f"{self.settings['network_pool']}; choose an unused IPv4 range in "
            "/etc/agentbox/settings.json (host routes and Docker networks are excluded)"
        )

    def check_mounts(self, data, environment):
        mounts = []
        for mount in environment.mounts:
            project = data["projects"].get(mount.project)
            if not project or project["status"] != "active":
                raise AgentboxError(f"Project is not active: {mount.project}")
            if projects.identity(project["path"]) != project["identity"]:
                raise AgentboxError("Project root changed; register again")
            projects.scan(
                project["path"], {self.settings["operator_uid"], self.settings["service_uid"]}
            )
            root = Path(project["path"])
            if (
                environment.workdir == mount.target
                or Path(mount.target) in Path(environment.workdir).parents
            ):
                relative = Path(environment.workdir).relative_to(mount.target)
                workdir = (root / relative).resolve(strict=True)
                if not workdir.is_relative_to(root) or not workdir.is_dir():
                    raise AgentboxError("Working directory escapes the mounted project")
            value = f"type=bind,src={root},dst={mount.target},bind-recursive=disabled,bind-propagation=rprivate"
            if mount.mode == "ro":
                value += ",readonly"
            mounts.extend(["--mount", value])
        return mounts

    def check_guard(self):
        guard = subprocess.run(
            ["/usr/bin/systemctl", "--user", "is-active", "agentbox-watch.service"],
            env={
                "PATH": "/usr/bin:/bin",
                "HOME": self.settings["home"],
                "XDG_RUNTIME_DIR": f"/run/user/{self.settings['service_uid']}",
                "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{self.settings['service_uid']}/bus",
            },
            text=True,
            capture_output=True,
            check=False,
        )
        if guard.returncode:
            raise AgentboxError("Host address guard is not running")

    def prepare_pki(self, directory):
        for part in ("private", "public"):
            (directory / part).mkdir(mode=0o700, exist_ok=True)
        self.docker.mutate(
            "run",
            "--rm",
            "--network",
            "none",
            "--user",
            "0:0",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--read-only",
            "--mount",
            f"type=bind,src={directory}/private,dst=/private",
            "--mount",
            f"type=bind,src={directory}/public,dst=/public",
            self.settings["proxy_image"],
            "pki",
        )
        (directory / "public").chmod(0o755)

    def drop_proxy(self, data, name):
        entry = data["environments"][name]
        entry["status"] = "proxy-stopped"
        self.save(data)
        for identifier in self.owned(data, name, "container"):
            details = self.docker.inspect("container", identifier)
            if details["Config"]["Labels"].get("agentbox.role") == "proxy":
                self.docker.mutate("container", "rm", "--force", identifier)
        entry["resources"].pop("proxy", None)
        directory = self.store.root / "environments" / name
        for filename in ("ca.snapshot.pem", "ca.snapshot.key"):
            (directory / filename).unlink(missing_ok=True)
        self.save(data)

    def create_proxy(self, data, environment, entry, tokens):
        # Values are never arguments or policy contents; docker inherits only internal names.
        values = policy.token_environment(environment, tokens)
        directory = self.store.root / "environments" / environment.name
        args = [
            "container",
            "create",
            "--name",
            "ab-" + data["installation"][:8] + "-" + environment.name + "-proxy",
            *self.label_args(data, environment.name, "proxy"),
            "--user",
            "10001:10001",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--read-only",
            "--cpus",
            "0.5",
            "--memory",
            "256m",
            "--pids-limit",
            "128",
            "--log-driver=local",
            "--log-opt=max-size=10m",
            "--log-opt=max-file=3",
            "--network",
            f"name={entry['resources']['inside']},ip={entry['proxy_ip']}",
            "--network",
            f"name={entry['resources']['outside']},gw-priority=1",
            "--sysctl",
            "net.ipv4.ip_forward=0",
            "--mount",
            f"type=bind,src={directory}/policy.json,dst=/run/agentbox/policy.json,readonly",
        ]
        if environment.credentials:
            for part in ("pem", "key"):
                snapshot = directory / f"ca.snapshot.{part}"
                snapshot.write_bytes((directory / "private" / f"ca.{part}").read_bytes())
                snapshot.chmod(0o444)
                args += [
                    "--mount",
                    f"type=bind,src={snapshot},dst=/run/agentbox/ca.{part},readonly",
                ]
        for variable in values:
            args += ["--env", variable]
        args += [self.settings["proxy_image"]]
        proxy = self.docker.mutate(*args, extra_env=values).stdout.strip()
        entry["resources"]["proxy"] = proxy
        self.save(data)
        self.docker.mutate("container", "start", proxy)
        for _ in range(30):
            check = self.docker.run("exec", proxy, "agentbox-proxy", "check", check=False)
            if check.returncode == 0:
                return
            if not self.docker.inspect("container", proxy)["State"]["Running"]:
                break
            time.sleep(0.2)
        raise AgentboxError("Proxy failed readiness check")

    def apply_proxy(self, data, environment, tokens):
        name = environment.name
        entry = data["environments"].get(name)
        if not entry or entry.get("proxy_format") != 2:
            raise AgentboxError(
                "Placeholder environment required; recreate legacy environments explicitly (remove deletes login)"
            )
        self.check_guard()
        if (
            entry["host_addresses"] != local_addresses()
            or entry["status"] == "stopped-host-address-change"
        ):
            self.stop(data, name)
            entry["status"] = "stopped-host-address-change"
            self.save(data)
            raise AgentboxError("Host addresses changed; explicit recreation required")
        normalized = json.loads(json.dumps(environment.to_dict()))
        try:
            for key in set(normalized) - {"credentials", "allow"}:
                if normalized[key] != entry["config"][key]:
                    raise AgentboxError(
                        "proxy apply cannot change image, projects or agent profile"
                    )
            policy.validate_placeholders(environment, entry.get("placeholders"))
            self.check_mounts(data, environment)
            owned = self.owned(data, name, "network")
            if any(entry["resources"].get(role) not in owned for role in ("inside", "outside")):
                raise AgentboxError("Environment networks are missing")
        except AgentboxError as exc:
            raise AgentboxError(
                f"{exc}. Proxy configuration not changed; use "
                f"'abx proxy stop {name}' to revoke existing access"
            ) from exc
        # Stop before token validation or resolution; later failures must not retain old credentials.
        self.drop_proxy(data, name)
        try:
            policy.token_environment(environment, tokens)
            policy.validate_token_availability(environment, entry["placeholders"], tokens)
            addresses = local_addresses()
            pinned = policy.resolve(environment.allow, addresses)
            rendered, _, digest = policy.render(
                environment.allow,
                pinned,
                entry["proxy_ip"],
                addresses,
                environment.credentials,
                entry["placeholders"],
            )
            directory = self.store.root / "environments" / name
            self.prepare_pki(directory)
            path = directory / "policy.json"
            atomic_json(path, json.loads(rendered))
            path.chmod(0o444)
            entry.update(config=normalized, policy=digest, pinned=pinned, status="proxy-updating")
            self.save(data)
            self.create_proxy(data, environment, entry, tokens)
            agent = entry["resources"].get("agent")
            entry["status"] = (
                "running"
                if self.docker.inspect("container", agent)["State"]["Running"]
                else "proxy-ready"
            )
            self.save(data)
            return entry
        except Exception:
            self.drop_proxy(data, name)
            raise

    def start(self, data, payload, tokens=None):
        self.check_guard()
        environment = config.parse(payload)
        name = environment.name
        normalized = json.loads(json.dumps(environment.to_dict()))
        image = images.managed(self.docker, data["installation"], environment.image)
        images.profile(image)
        previous = data["environments"].get(name)
        if previous:
            if previous.get("proxy_format") != 2:
                raise AgentboxError(
                    "Legacy environment: stop and explicitly recreate; remove deletes agent login"
                )
            if (
                previous["host_addresses"] != local_addresses()
                or previous["status"] == "stopped-host-address-change"
            ):
                self.stop(data, name)
                previous["status"] = "stopped-host-address-change"
                self.save(data)
                raise AgentboxError("Host addresses changed; remove and recreate explicitly")
            if previous["config"] != normalized:
                raise AgentboxError(
                    "Configuration changed; use proxy apply for network/token rules, or recreate for other changes"
                )
            self.check_mounts(data, environment)
            agent = previous["resources"].get("agent")
            if agent not in self.owned(data, name, "container"):
                raise AgentboxError("Agent container is missing; explicit recreation required")
            proxy = previous["resources"].get("proxy")
            if (
                previous["status"] == "running"
                and proxy in self.owned(data, name, "container")
                and self.docker.inspect("container", agent)["State"]["Running"]
                and self.docker.inspect("container", proxy)["State"]["Running"]
            ):
                return previous
            self.apply_proxy(data, environment, tokens or {})
            self.docker.mutate("container", "start", agent)
            previous["status"] = "running"
            self.save(data)
            return previous
        mounts = self.check_mounts(data, environment)
        # Resolve on the trusted host and pin one verified address per name. No
        # proxy DNS fallback means a later DNS rebind cannot change the destination.
        addresses = local_addresses()
        pinned = policy.resolve(environment.allow, addresses)
        inside_subnet, outside_subnet = self.subnets()
        proxy_ip = str(inside_subnet.network_address + 2)
        policy.token_environment(environment, tokens or {})
        placeholders = policy.placeholders(environment, tokens or {})
        rendered, _, digest = policy.render(
            environment.allow, pinned, proxy_ip, addresses, environment.credentials, placeholders
        )
        directory = self.store.root / "environments" / name
        directory.mkdir(parents=True, mode=0o700)
        self.prepare_pki(directory)
        atomic_json(directory / "policy.json", json.loads(rendered))
        (directory / "policy.json").chmod(0o444)
        prefix = "ab-" + data["installation"][:8] + "-" + name
        entry = {
            "config": normalized,
            "status": "creating",
            "policy": digest,
            "proxy_format": 2,
            "placeholders": placeholders,
            "proxy_ip": proxy_ip,
            "pinned": pinned,
            "host_addresses": addresses,
            "resources": {},
        }
        data["environments"][name] = entry
        self.save(data)
        try:
            for role, subnet in (("inside", inside_subnet), ("outside", outside_subnet)):
                args = [
                    "network",
                    "create",
                    *self.label_args(data, name, role),
                    "--subnet",
                    str(subnet),
                ]
                if role == "inside":
                    args += [
                        "--internal",
                        "-o",
                        "com.docker.network.bridge.gateway_mode_ipv4=isolated",
                    ]
                identifier = self.docker.mutate(*args, prefix + "-" + role).stdout.strip()
                entry["resources"][role] = identifier
                self.save(data)
            common = [
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--log-driver=local",
                "--log-opt=max-size=10m",
                "--log-opt=max-file=3",
            ]
            self.create_proxy(data, environment, entry, tokens or {})
            command = [
                "container",
                "create",
                "--name",
                prefix + "-agent",
                *common,
                *self.label_args(data, name, "agent"),
                "--user",
                "0:0",
                "--init",
                "--security-opt",
                f"seccomp={self.settings['seccomp']}",
                "--network",
                entry["resources"]["inside"],
                "--dns",
                "127.0.0.1",
                "--sysctl",
                "net.ipv6.conf.all.disable_ipv6=1",
                "--sysctl",
                "net.ipv6.conf.default.disable_ipv6=1",
                "--cpus",
                str(environment.resources.cpus),
                "--memory",
                environment.resources.memory,
                "--pids-limit",
                str(environment.resources.pids),
                "--workdir",
                environment.workdir,
                "--env",
                "HOME=/home/agent",
                "--env",
                "LANG=C.UTF-8",
                *mounts,
            ]
            command.extend(
                ["--mount", f"type=bind,src={directory}/public,dst=/run/agentbox-ca,readonly"]
            )
            for variable in (
                "SSL_CERT_FILE",
                "CURL_CA_BUNDLE",
                "REQUESTS_CA_BUNDLE",
                "CODEX_CA_CERTIFICATE",
            ):
                command.extend(["--env", f"{variable}=/run/agentbox-ca/bundle.pem"])
            command.extend(["--env", "NODE_EXTRA_CA_CERTS=/run/agentbox-ca/ca.pem"])
            for variable in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
                command.extend(["--env", f"{variable}=http://{proxy_ip}:3128"])
            command.extend(["--env", f"GIT_CONFIG_COUNT={len(environment.mounts)}"])
            for index, mount in enumerate(environment.mounts):
                command.extend(
                    [
                        "--env",
                        f"GIT_CONFIG_KEY_{index}=safe.directory",
                        "--env",
                        f"GIT_CONFIG_VALUE_{index}={mount.target}",
                    ]
                )
            for variable, placeholder in placeholders.items():
                command.extend(["--env", f"{variable}={placeholder}"])
            command.extend(["--entrypoint", "/bin/sh", image["Id"], "-c", "exec sleep infinity"])
            agent = self.docker.mutate(*command).stdout.strip()
            entry["resources"]["agent"] = agent
            self.save(data)
            self.docker.mutate("container", "start", agent)
            entry["status"] = "running"
            self.save(data)
            return entry
        except Exception:
            try:
                self.remove(data, name)
            except Exception:
                entry["status"] = "failed"
                data["environments"][name] = entry
                self.save(data)
            raise

    def dispatch(self, request, context=None):
        action = request["action"]
        if action == "shell":
            return self.shell(request)
        if action == "run":
            return self.run(
                request["config"], request.get("tokens", {}), tty=request.get("tty") is True
            )
        with self.store.locked() as data:
            info = self.verified(data)
            if action == "doctor":
                return {
                    "daemon_id": info["ID"],
                    "version": info["ServerVersion"],
                    "rootless": True,
                    "cgroup": info["CgroupDriver"],
                    "state": str(self.store.root),
                    "host_addresses": local_addresses(),
                }
            if action == "project":
                return self.project(data, request["operation"], request)
            if action == "image":
                operation = request.get("operation")
                if operation == "ls":
                    names = request["names"]
                    if not isinstance(names, list):
                        raise AgentboxError("Expected local image names")
                    return {
                        config.name(name): images.inspect(self.docker, data["installation"], name)
                        for name in names
                    }
                name = config.name(request["name"])
                if operation == "build":
                    return images.build(self.docker, data["installation"], name, context)
                if operation == "inspect":
                    return images.inspect(self.docker, data["installation"], name)
                if operation == "rm":
                    details = images.managed(self.docker, data["installation"], name)
                    images.require_idle(self.docker, details)
                    self.docker.mutate("image", "rm", images.tag(name))
                    return {"name": name, "status": "removed", "recipe_retained": True}
                raise AgentboxError("Unknown image operation")
            if action == "start":
                return self.start(data, request["config"], request.get("tokens", {}))
            if action == "proxy":
                operation = request.get("operation")
                if operation == "build":
                    return self.build_proxy()
                if operation == "apply":
                    return self.apply_proxy(
                        data, config.parse(request["config"]), request.get("tokens", {})
                    )
                name = config.name(request["name"])
                entry = data["environments"].get(name)
                if not entry or entry.get("proxy_format") != 2:
                    raise AgentboxError("Unknown or legacy environment")
                if operation == "stop":
                    self.drop_proxy(data, name)
                elif operation == "rotate-ca":
                    self.stop(data, name)
                    self.drop_proxy(data, name)
                    directory = self.store.root / "environments" / name
                    for part in ("key", "pem"):
                        (directory / "private" / f"ca.{part}").unlink(missing_ok=True)
                    self.prepare_pki(directory)
                    entry["status"] = "stopped"
                    self.save(data)
                else:
                    raise AgentboxError("Unknown proxy operation")
                return {"name": name, "status": entry["status"]}
            if action == "status":
                result = {}
                for name, entry in data["environments"].items():
                    snapshot = dict(entry)
                    observed = {}
                    for role in ("agent", "proxy"):
                        try:
                            identifier = entry["resources"].get(role)
                            details = (
                                self.docker.inspect("container", identifier) if identifier else None
                            )
                            observed[role] = details["State"]["Status"] if details else "missing"
                        except AgentboxError:
                            observed[role] = "missing"
                    snapshot["containers"] = observed
                    if entry["status"] == "running" and set(observed.values()) != {"running"}:
                        snapshot["status"] = "degraded"
                    result[name] = snapshot
                return result
            if action in ("stop", "remove"):
                name = config.name(request["name"])
                entry = data["environments"].get(name)
                if action == "stop" and entry and not entry["config"].get("persistent", True):
                    action = "remove"
                getattr(self, action)(data, name)
                return {"name": name, "status": "stopped" if action == "stop" else "removed"}
            if action in ("exec", "logs", "login-api-key"):
                name = config.name(request["name"])
                entry = data["environments"].get(name)
                if not entry or (action != "logs" and entry["status"] != "running"):
                    raise AgentboxError("Environment is not running")
                if action != "logs" and entry["host_addresses"] != local_addresses():
                    self.stop(data, name)
                    raise AgentboxError(
                        "Host addresses changed; environment stopped, start it again"
                    )
                role = "proxy" if request.get("proxy") else "agent"
                identifier = entry["resources"][role]
                if identifier not in self.owned(data, name, "container"):
                    raise AgentboxError("Container ownership changed")
                if action == "logs":
                    if not request.get("proxy"):
                        path = self.store.root / "environments" / name / "agent.log"
                        return path.read_text(errors="replace")[-65536:] if path.exists() else ""
                    return self.docker.run("logs", "--tail", "200", identifier).stdout
                if action == "login-api-key":
                    key = request["key"]
                    if not isinstance(key, str) or not key or len(key) > 16384:
                        raise AgentboxError("Invalid key input")
                    login = self.docker.run(
                        "exec",
                        "-i",
                        identifier,
                        "codex",
                        "login",
                        "--with-api-key",
                        source=key + "\n",
                        check=False,
                    )
                    if login.returncode:
                        raise AgentboxError("Codex credential setup failed; output withheld")
                    return {"status": "credentials supplied to Codex via stdin"}
                command = request.get("command") or entry["config"]["command"]
                if not isinstance(command, list) or not command:
                    raise AgentboxError("Expected command argument list")
                command = [config.text(arg) for arg in command]
                tty = request.get("tty") is True
            else:
                raise AgentboxError("Unknown control operation")
        # Do not hold the global operation lock for the duration of a shell session.
        return self.execute(name, identifier, command, tty, data["daemon_id"])
