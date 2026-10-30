"""Service-user operations behind the fixed local sudo control entry point."""

import ipaddress
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from . import config, policy, projects
from .errors import AgentboxError
from .runtime import Docker, local_addresses
from .state import Store, atomic_json


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
        raise AgentboxError("No collision-free subnets available in the configured pool")

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

    def start(self, data, payload):
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
        environment = config.parse(payload)
        name = environment.name
        normalized = json.loads(json.dumps(environment.to_dict()))
        previous = data["environments"].get(name)
        if previous:
            running = any(
                self.docker.inspect("container", i)["State"]["Running"]
                for i in self.owned(data, name, "container")
            )
            if running:
                healthy = all(role in previous["resources"] for role in ("agent", "proxy"))
                if healthy:
                    healthy = all(
                        self.docker.inspect("container", previous["resources"][role])["State"][
                            "Running"
                        ]
                        for role in ("agent", "proxy")
                    )
                if previous["config"] == normalized and previous["status"] == "running" and healthy:
                    return previous
                raise AgentboxError(
                    "Environment exists or is degraded; stop it before starting again"
                )
            if previous["status"] in ("stopped", "running"):
                if (
                    previous["config"] != normalized
                    or previous["host_addresses"] != local_addresses()
                ):
                    raise AgentboxError(
                        "Configuration or host addresses changed; remove and recreate explicitly"
                    )
                self.check_mounts(data, environment)
                for role in ("proxy", "agent"):
                    identifier = previous["resources"][role]
                    if identifier not in self.owned(data, name, "container"):
                        raise AgentboxError(
                            "Stopped environment is incomplete; remove and recreate it"
                        )
                    self.docker.mutate("container", "start", identifier)
                previous["status"] = "running"
                self.save(data)
                return previous
            if previous["status"] == "stopped-host-address-change":
                raise AgentboxError("Host addresses changed; remove and recreate explicitly")
            self.remove(data, name)
        mounts = self.check_mounts(data, environment)
        image = self.docker.inspect("image", environment.image)
        if image.get("Architecture") not in ("amd64", "arm64"):
            raise AgentboxError("Only 64-bit amd64 and arm64 image profiles are supported")
        if image["Config"].get("Volumes"):
            raise AgentboxError(
                "Image declares implicit VOLUME mounts; use an explicit image profile"
            )
        # Resolve on the trusted host and pin one verified address per name. No
        # proxy DNS fallback means a later DNS rebind cannot change the destination.
        addresses = local_addresses()
        pinned = policy.resolve(environment.allow, addresses)
        inside_subnet, outside_subnet = self.subnets()
        proxy_ip = str(inside_subnet.network_address + 2)
        rendered, hosts, digest = policy.render(environment.allow, pinned, proxy_ip, addresses)
        directory = self.store.root / "environments" / name
        directory.mkdir(parents=True, mode=0o700)
        for filename, content in (("squid.conf", rendered), ("hosts", hosts)):
            path = directory / filename
            path.write_text(content)
            path.chmod(0o644)  # Proxy UID can read the file through the explicit bind mount.
        prefix = "ab-" + data["installation"][:8] + "-" + name
        entry = {
            "config": normalized,
            "status": "creating",
            "policy": digest,
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
            proxy_args = [
                "container",
                "create",
                "--name",
                prefix + "-proxy",
                *common,
                *self.label_args(data, name, "proxy"),
                "--user",
                "proxy",
                "--read-only",
                "--cpus",
                "0.5",
                "--memory",
                "256m",
                "--pids-limit",
                "128",
                "--network",
                f"name={entry['resources']['inside']},ip={proxy_ip}",
                "--network",
                f"name={entry['resources']['outside']},gw-priority=1",
                "--sysctl",
                "net.ipv4.ip_forward=0",
                "--tmpfs",
                "/tmp:mode=1777,nosuid,nodev,noexec",
                "--mount",
                f"type=bind,src={directory}/squid.conf,dst=/etc/squid/squid.conf,readonly",
                "--mount",
                f"type=bind,src={directory}/hosts,dst=/etc/squid/agentbox-hosts,readonly",
                self.settings["proxy_image"],
            ]
            proxy = self.docker.mutate(*proxy_args).stdout.strip()
            entry["resources"]["proxy"] = proxy
            self.save(data)
            self.docker.mutate("container", "start", proxy)
            for _ in range(30):
                check = self.docker.run(
                    "exec",
                    proxy,
                    "curl",
                    "-s",
                    "--max-time",
                    "1",
                    "-o",
                    "/dev/null",
                    "-w",
                    "%{http_code}",
                    "--proxy",
                    f"http://{proxy_ip}:3128",
                    "http://unlisted.agentbox.invalid/",
                    check=False,
                )
                if check.returncode == 0 and check.stdout == "403":
                    break
                time.sleep(0.2)
            else:
                raise AgentboxError("Proxy failed readiness check; agent was not started")
            self.docker.run("exec", proxy, "squid", "-k", "parse")
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

    def dispatch(self, request):
        action = request["action"]
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
            if action == "start":
                return self.start(data, request["config"])
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
            if action == "build-images":
                for image, directory in (
                    ("agentbox-dev:local", "images/dev"),
                    (self.settings["proxy_image"], "proxy"),
                ):
                    self.docker.mutate(
                        "build", "--tag", image, str(Path("/opt/agentbox") / directory), timeout=900
                    )
                return {"images": ["agentbox-dev:local", self.settings["proxy_image"]]}
            if action == "pull-image":
                image = config.text(request["image"])
                if not config.IMAGE.fullmatch(image):
                    raise AgentboxError("Invalid image reference")
                self.docker.mutate("image", "pull", image, timeout=900)
                return {"image": image}
            if action in ("stop", "remove"):
                name = config.name(request["name"])
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
        self.docker.verify(data["daemon_id"])
        terminal = open("/dev/tty") if tty else None
        try:
            # stdin is the completed JSON request pipe unless a TTY is selected.
            return self.docker.exec_stream(
                identifier, command, self.store.root / "environments" / name, terminal=terminal
            )
        finally:
            if terminal:
                terminal.close()
