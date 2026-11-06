"""Strict environment configuration. No Docker flags or shell evaluation."""

import ipaddress
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

import yaml

from .errors import AgentboxError

NAME = re.compile(r"[a-z][a-z0-9-]{0,47}\Z")
MEMORY = re.compile(r"[1-9][0-9]*[mg]\Z")
VARIABLE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z")
RESERVED_VARIABLES = {
    "HOME",
    "PATH",
    "LANG",
    "LANGUAGE",
    "SHELL",
    "USER",
    "LOGNAME",
    "IFS",
    "ENV",
    "BASH_ENV",
    "CDPATH",
    "TMPDIR",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "CURL_CA_BUNDLE",
    "REQUESTS_CA_BUNDLE",
    "CODEX_CA_CERTIFICATE",
    "CODEX_HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_RUNTIME_DIR",
}
RESERVED_PREFIXES = ("AGENTBOX_", "LD_", "DYLD_", "PYTHON", "NODE_", "GIT_CONFIG_", "LC_")
AUTH_HEADERS = {"authorization", "x-api-key", "context7_api_key"}


class StrictLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise AgentboxError("YAML keys must be unique strings (merge keys are unsupported)")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def fields(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise AgentboxError(f"Expected fields {sorted(allowed)}; required: {sorted(required)}")
    return value


def name(value):
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise AgentboxError(
            "Names must use lowercase letters, digits and hyphens; max 48 characters"
        )
    return value


def text(value):
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
        raise AgentboxError("Expected nonempty text without control characters")
    return value


def hostname(value):
    value = text(value).lower().rstrip(".")
    if len(value) > 253 or "." not in value:
        raise AgentboxError("Use an exact fully qualified DNS name")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        pass
    else:
        raise AgentboxError("IP literals are not permitted")
    if any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in value.split(".")
    ):
        raise AgentboxError("Invalid DNS name; wildcards and implicit subdomains are unsupported")
    return value


def target(value):
    value = text(value)
    path = PurePosixPath(value)
    if not path.is_absolute() or ".." in path.parts or str(path) != value or "," in value:
        raise AgentboxError("Mount targets must be normalized absolute paths without commas")
    reserved = [
        "/etc",
        "/proc",
        "/sys",
        "/dev",
        "/run",
        "/var",
        "/usr",
        "/bin",
        "/sbin",
        "/lib",
        "/lib64",
        "/tmp",
    ]
    if value in ("/", "/home") or any(
        path == PurePosixPath(p) or PurePosixPath(p) in path.parents for p in reserved
    ):
        raise AgentboxError("Mount target overlaps a reserved container path")
    return value


@dataclass(frozen=True)
class Mount:
    source: str
    target: str
    mode: str = "rw"


@dataclass(frozen=True)
class Rule:
    host: str
    port: int


@dataclass(frozen=True)
class Resources:
    cpus: float = 2.0
    memory: str = "4g"
    pids: int = 512


def credential_variable(raw):
    parts = [part.strip() for part in text(raw).split("=")]
    if len(parts) not in (1, 2) or any(not VARIABLE.fullmatch(part) for part in parts):
        raise AgentboxError("Expected token variable or client_variable=host_variable")
    client, source = parts[0], parts[-1]
    if client.upper() in RESERVED_VARIABLES or client.upper().startswith(RESERVED_PREFIXES):
        raise AgentboxError("Token client variable overlaps a reserved runtime name")
    return client if client == source else f"{client}={source}"


@dataclass(frozen=True)
class Credential:
    host: str
    port: int
    header: str
    env: str

    @property
    def client_env(self):
        return self.env.partition("=")[0]

    @property
    def source_env(self):
        return self.env.partition("=")[2] or self.env


@dataclass(frozen=True)
class Environment:
    name: str
    image: str
    workdir: str
    command: tuple[str, ...]
    mounts: tuple[Mount, ...]
    allow: tuple[Rule, ...]
    resources: Resources
    credentials: tuple[Credential, ...] = ()
    persistent: bool = True

    def to_dict(self):
        return asdict(self)


def parse(data):
    fields(
        data,
        {
            "name",
            "image",
            "workdir",
            "command",
            "mounts",
            "network",
            "resources",
            "credentials",
            "persistent",
        },
        {"name", "image", "mounts"},
    )
    persistent = data.get("persistent", True)
    if type(persistent) is not bool:
        raise AgentboxError("persistent must be a boolean")
    image = name(data["image"])
    command = data.get("command", ["bash"])
    if not isinstance(command, list) or not 1 <= len(command) <= 128:
        raise AgentboxError("Command must be a nonempty argument list")
    command = tuple(text(arg) for arg in command)
    mounts = data["mounts"]
    if not isinstance(mounts, list) or not 1 <= len(mounts) <= 32:
        raise AgentboxError("Choose between 1 and 32 mount mounts")
    parsed_mounts = []
    for entry in mounts:
        fields(entry, {"source", "target", "mode"}, {"source", "target"})
        mode = entry.get("mode", "rw")
        if mode not in ("rw", "ro"):
            raise AgentboxError("Mount mode must be rw or ro")
        mount = Mount(name(entry["source"]), target(entry["target"]), mode)
        current = PurePosixPath(mount.target)
        if any(
            current == PurePosixPath(old.target)
            or current in PurePosixPath(old.target).parents
            or PurePosixPath(old.target) in current.parents
            for old in parsed_mounts
        ):
            raise AgentboxError("Mount targets must not overlap")
        parsed_mounts.append(mount)
    workdir = text(data.get("workdir", parsed_mounts[0].target))
    workpath = PurePosixPath(workdir)
    if (
        not any(
            workpath == PurePosixPath(m.target) or PurePosixPath(m.target) in workpath.parents
            for m in parsed_mounts
        )
        or ".." in workpath.parts
        or str(workpath) != workdir
    ):
        raise AgentboxError("Working directory must be inside a registered mount")
    network = fields(data.get("network", {}), {"allow"})
    entries = network.get("allow", [])
    if not isinstance(entries, list) or len(entries) > 128:
        raise AgentboxError("network.allow must be a list with at most 128 rules")
    rules = []
    for entry in entries:
        fields(entry, {"host", "port"}, {"host", "port"})
        if type(entry["port"]) is not int or entry["port"] not in (80, 443):
            raise AgentboxError("Only integer ports 80 and 443 are supported")
        rule = Rule(hostname(entry["host"]), entry["port"])
        if rule in rules:
            raise AgentboxError("Duplicate destination rule")
        rules.append(rule)
    credentials = data.get("credentials", [])
    if not isinstance(credentials, list) or len(credentials) > 32:
        raise AgentboxError("credentials must be a list with at most 32 rules")
    parsed_credentials = []
    bindings = {}
    seen = set()
    for entry in credentials:
        fields(entry, {"host", "port", "header", "env"}, {"host", "port", "header", "env"})
        host = hostname(entry["host"])
        header = text(entry["header"]).lower()
        variable = credential_variable(entry["env"])
        if (
            type(entry["port"]) is not int
            or entry["port"] != 443
            or Rule(host, 443) not in rules
            or header not in AUTH_HEADERS
            or (host, header) in seen
        ):
            raise AgentboxError("Invalid, duplicate or unlisted credential rule")
        seen.add((host, header))
        credential = Credential(host, 443, header, variable)
        if bindings.get(credential.client_env, credential.source_env) != credential.source_env:
            raise AgentboxError("A token client variable must have one host source")
        bindings[credential.client_env] = credential.source_env
        parsed_credentials.append(credential)
    raw = fields(data.get("resources", {}), {"cpus", "memory", "pids"})
    cpus, memory, pids = raw.get("cpus", 2.0), raw.get("memory", "4g"), raw.get("pids", 512)
    if type(cpus) not in (int, float) or not 0.1 <= cpus <= 128:
        raise AgentboxError("cpus must be a number between 0.1 and 128")
    if not isinstance(memory, str) or not MEMORY.fullmatch(memory):
        raise AgentboxError("memory must be a positive size with m or g suffix")
    if type(pids) is not int or not 16 <= pids <= 65536:
        raise AgentboxError("pids must be an integer between 16 and 65536")
    return Environment(
        name(data["name"]),
        image,
        workdir,
        command,
        tuple(parsed_mounts),
        tuple(rules),
        Resources(float(cpus), memory, pids),
        tuple(parsed_credentials),
        persistent,
    )


def environment_directory():
    return (
        Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "agentbox/environments"
    )


def resolve_file(value):
    text = str(value)
    path = Path(text).expanduser()
    if "/" in text or (path.suffix and path.exists()):
        return path
    if path.suffix in (".yaml", ".yml"):
        candidates = [environment_directory() / path.name]
    else:
        name(text)
        candidates = [environment_directory() / f"{text}{suffix}" for suffix in (".yaml", ".yml")]
    matches = [candidate for candidate in candidates if candidate.is_file()]
    if len(matches) > 1:
        raise AgentboxError("Multiple configuration files match; specify an explicit YAML path")
    if matches:
        return matches[0]
    raise AgentboxError(f"Configuration not found: {text}; also searched {environment_directory()}")


def load(path):
    try:
        source = resolve_file(path).read_text()
        if len(source) > 65536:
            raise AgentboxError("Configuration is too large")
        return parse(yaml.load(source, Loader=StrictLoader))
    except AgentboxError as exc:
        raise AgentboxError(str(exc), code="invalid_configuration") from None
    except (OSError, yaml.YAMLError, RecursionError) as exc:
        raise AgentboxError(
            f"Cannot load configuration: {type(exc).__name__}", code="invalid_configuration"
        ) from None
