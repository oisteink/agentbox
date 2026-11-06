"""Local Dockerfile recipes and images in the dedicated Docker instance."""

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from . import config
from .errors import AgentboxError

TEMPLATES = ("base", "codex", "opencode", "claude-code")


def directory():
    return config.environment_directory().parent / "images"


def recipe(name):
    path = directory() / config.name(name)
    if path.is_symlink() or not (path / "Dockerfile").is_file():
        raise AgentboxError(f"Local Dockerfile missing: {path / 'Dockerfile'}")
    return path


def names():
    return sorted(
        p.name
        for p in directory().glob("*")
        if config.NAME.fullmatch(p.name) and not p.is_symlink() and (p / "Dockerfile").is_file()
    )


def checked_digest(value):
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise AgentboxError("Expected a recipe digest", code="invalid_request")
    return value


def bundled():
    return Path(__file__).parent / "templates"


def template_names():
    return sorted(set(TEMPLATES) | set(names()))


def template_path(name):
    name = config.name(name)
    local = directory() / name
    if local.exists() or local.is_symlink():
        return recipe(name)
    if name in TEMPLATES:
        return bundled() / name
    raise AgentboxError("Unknown image template", code="image_template_not_found")


def new(name, template=None):
    path = directory() / config.name(name)
    if template is None:
        default = directory() / "default"
        template = "default" if default.exists() or default.is_symlink() else "base"
    source = template_path(template)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        raise AgentboxError(f"Image recipe already exists: {path}") from None
    try:
        shutil.copytree(source, path, symlinks=True, dirs_exist_ok=True)
    except OSError:
        shutil.rmtree(path)
        raise
    return {"name": name, "path": str(path), "template": template}


def edit(name, emit=None):
    path = recipe(name).resolve()
    editor = (
        os.environ.get("VISUAL", "").strip() or os.environ.get("EDITOR", "").strip() or "editor"
    )
    command = [*shlex.split(editor), str(path / "Dockerfile")]
    before = fingerprint(name)
    if emit:
        from .process import run

        code = run(command, emit, cwd=path)
    else:
        code = subprocess.run(command, cwd=path, check=False).returncode
    return {
        "name": name,
        "path": str(path),
        "changed": fingerprint(name) != before,
        "exit_code": code,
    }


def archive(name, output):
    """Pack links as links; never follow them to files outside the context."""
    path = recipe(name)

    def include(member):
        if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
            raise AgentboxError(f"Special file in build context: {member.name}")
        return member

    with tarfile.open(fileobj=output, mode="w", dereference=False) as bundle:
        bundle.add(path, arcname=".", filter=include)


def fingerprint_archive(source):
    digest = hashlib.sha256()
    offset = source.tell()
    try:
        with tarfile.open(fileobj=source, mode="r:") as bundle:
            for member in bundle:
                if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                    raise AgentboxError("Invalid or unsafe build context")
                header = [
                    member.name,
                    member.type.decode("ascii"),
                    member.mode & 0o777,
                    member.linkname,
                    member.size if member.isfile() else 0,
                ]
                digest.update(json.dumps(header, ensure_ascii=True).encode() + b"\0")
                if member.isfile():
                    with bundle.extractfile(member) as content:
                        while block := content.read(65536):
                            digest.update(block)
    except (tarfile.TarError, OSError):
        raise AgentboxError("Invalid or unsafe build context") from None
    finally:
        source.seek(offset)
    return digest.hexdigest()


def fingerprint(name):
    with tempfile.TemporaryFile() as context:
        archive(name, context)
        context.seek(0)
        return fingerprint_archive(context)


def tag(name):
    return f"agentbox-image-{config.name(name)}:local"


def lookup(docker, reference):
    identifiers = docker.run("image", "ls", "-q", "--no-trunc", reference).stdout.split()
    return docker.inspect("image", identifiers[0]) if identifiers else None


def users(docker, identifier):
    result = []
    for container in docker.run("container", "ls", "-aq", "--no-trunc").stdout.split():
        details = docker.inspect("container", container)
        if details["Image"] == identifier:
            result.append(details["Name"].lstrip("/"))
    return sorted(result)


def require_idle(docker, details):
    active = users(docker, details["Id"]) if details else []
    if active:
        raise AgentboxError(
            "Image is in use by containers (including stopped): " + ", ".join(active)
        )


def profile(details):
    if details.get("Architecture") not in ("amd64", "arm64"):
        raise AgentboxError("Only 64-bit amd64 and arm64 image profiles are supported")
    if details["Config"].get("Volumes"):
        raise AgentboxError("Image declares implicit VOLUME mounts; use explicit registered mounts")


def managed(docker, installation, name, *, required=True):
    details = lookup(docker, tag(name))
    if details:
        labels = details["Config"].get("Labels") or {}
        if (
            labels.get("agentbox.installation") != installation
            or labels.get("agentbox.image") != name
        ):
            raise AgentboxError(f"Image tag is not owned by this recipe: {tag(name)}")
    elif required:
        raise AgentboxError(f"Image is not built; run 'abx image build {name}'")
    return details


def recipe_users(docker, installation, name, details, environments):
    known = {
        entry.get("resources", {}).get("agent"): environment
        for environment, entry in environments.items()
        if entry["config"]["image"] == name
    }
    result = []
    for identifier in docker.run("container", "ls", "-aq", "--no-trunc").stdout.split():
        container = docker.inspect("container", identifier)
        profile = container.get("Config", {})
        labels = profile.get("Labels") or {}
        own = (
            labels.get("agentbox.installation") == installation
            and labels.get("agentbox.image") == name
            and labels.get("agentbox.role") == "agent"
            and labels.get("agentbox.environment")
        )
        if (
            identifier in known
            or own
            or profile.get("Image") == tag(name)
            or (details and container["Image"] == details["Id"])
        ):
            result.append(
                {
                    "id": identifier,
                    "name": container["Name"].lstrip("/"),
                    "environment": known.get(identifier)
                    or (labels.get("agentbox.environment") if own else None),
                    "running": container["State"]["Running"],
                }
            )
    return result


def require_recipe_idle(docker, installation, name, details, environments, *, running_only):
    used = recipe_users(docker, installation, name, details, environments)
    blocked = [entry for entry in used if entry["running"] or not running_only]
    if blocked:
        raise AgentboxError(
            "Image is in use: " + ", ".join(entry["name"] for entry in blocked),
            code="image_in_use",
            details={"users": blocked},
        )


def inspect(docker, installation, name, *, environments=None, digest=None, users=True):
    details = managed(docker, installation, name, required=False)
    built_digest = (
        (details["Config"].get("Labels") or {}).get("agentbox.recipe-digest") if details else None
    )
    result = {
        "tag": tag(name),
        "status": "unbuilt"
        if not details
        else ("stale" if digest is not None and digest != built_digest else "built"),
        "id": details["Id"] if details else None,
        "digest": built_digest,
    }
    if users:
        used = recipe_users(docker, installation, name, details, environments or {})
        result["containers"] = sorted(entry["name"] for entry in used)
        result["environments"] = sorted(
            {entry["environment"] for entry in used if entry["environment"]}
        )
    return result


def build(docker, installation, name, source, *, environments=None, if_needed=False):
    if source is None:
        raise AgentboxError("Image build requires a local build context")
    details = managed(docker, installation, name, required=False)
    digest = fingerprint_archive(source) if if_needed else None
    if (
        if_needed
        and details
        and (details["Config"].get("Labels") or {}).get("agentbox.recipe-digest") == digest
    ):
        profile(details)
        return inspect(docker, installation, name, environments=environments)
    require_recipe_idle(docker, installation, name, details, environments or {}, running_only=True)
    digest = digest or fingerprint_archive(source)
    # A directory context lets Docker apply .dockerignore itself. BuildKit's
    # uploaded tar context bypasses that filtering.
    with tempfile.TemporaryDirectory(prefix="agentbox-build-") as context:
        try:
            with tarfile.open(fileobj=source, mode="r:") as bundle:
                bundle.extractall(context, filter="data")
        except (tarfile.TarError, OSError):
            raise AgentboxError("Invalid or unsafe build context") from None
        if not (Path(context) / "Dockerfile").is_file():
            raise AgentboxError("Build context requires a Dockerfile")
        docker.mutate(
            "build",
            "--tag",
            tag(name),
            "--label",
            f"agentbox.installation={installation}",
            "--label",
            f"agentbox.image={name}",
            "--label",
            "agentbox.role=",
            "--label",
            "agentbox.environment=",
            "--label",
            f"agentbox.recipe-digest={digest}",
            context,
            timeout=900,
        )
    details = managed(docker, installation, name)
    profile(details)
    return inspect(docker, installation, name, environments=environments)
