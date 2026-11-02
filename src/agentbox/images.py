"""Local Dockerfile recipes and images in the dedicated Docker instance."""

import shutil
import tarfile
import tempfile
from pathlib import Path

from . import config
from .errors import AgentboxError


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


def new(name, template="base"):
    path = directory() / config.name(name)
    if template not in ("base", "codex"):
        raise AgentboxError("Unknown image template")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        raise AgentboxError(f"Image recipe already exists: {path}") from None
    source = Path(__file__).parent / "templates" / template
    for file in source.iterdir():
        shutil.copyfile(file, path / file.name)
        (path / file.name).chmod(file.stat().st_mode & 0o777)
    (path / ".dockerignore").write_text(".git\n.env\n.env.*\n")
    return {"name": name, "path": str(path), "template": template}


def archive(name, output):
    """Pack links as links; never follow them to files outside the context."""
    path = recipe(name)

    def include(member):
        if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
            raise AgentboxError(f"Special file in build context: {member.name}")
        return member

    with tarfile.open(fileobj=output, mode="w", dereference=False) as bundle:
        bundle.add(path, arcname=".", filter=include)


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
        raise AgentboxError("Image declares implicit VOLUME mounts; use explicit project mounts")


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


def inspect(docker, installation, name):
    details = managed(docker, installation, name, required=False)
    return {
        "tag": tag(name),
        "status": "built" if details else "unbuilt",
        "id": details["Id"] if details else None,
        "containers": users(docker, details["Id"]) if details else [],
    }


def build(docker, installation, name, source):
    if source is None:
        raise AgentboxError("Image build requires a local build context")
    require_idle(docker, managed(docker, installation, name, required=False))
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
            context,
            timeout=900,
        )
    details = managed(docker, installation, name)
    profile(details)
    return inspect(docker, installation, name)
