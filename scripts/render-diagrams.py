#!/usr/bin/env python3
"""Render named PlantUML blocks in Markdown to adjacent diagrams/ files."""

import argparse
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("documents", nargs="*", type=Path)
    renderer = parser.add_mutually_exclusive_group()
    renderer.add_argument("--plantuml", default="plantuml")
    renderer.add_argument("--jar", type=Path, help="Use a specific PlantUML jar through Java")
    parser.add_argument("--format", choices=("svg", "png"), default="svg")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    documents = args.documents or [root / "docs/architecture-c4.md"]
    jobs = {}
    for document in documents:
        blocks = re.findall(r"```plantuml\n(.*?)\n```", document.read_text(encoding="utf-8"), re.S)
        if not blocks:
            parser.error(f"No PlantUML blocks in {document}")
        for block in blocks:
            name = re.match(r"@startuml ([a-z0-9][a-z0-9-]*)\n", block)
            if not name:
                parser.error(f"Expected @startuml NAME in {document}")
            target = document.resolve().parent / "diagrams" / f"{name[1]}.{args.format}"
            if target in jobs:
                parser.error(f"Duplicate diagram name: {target}")
            jobs[target] = block
    env = dict(os.environ)
    env.pop("DISPLAY", None)
    command = (
        ["java", "-Djava.awt.headless=true", "-jar", str(args.jar)] if args.jar else [args.plantuml]
    )
    for target, block in jobs.items():
        result = subprocess.run(
            [*command, "-charset", "UTF-8", f"-t{args.format}", "-nometadata", "-pipe"],
            input=block.encode("utf-8"),
            capture_output=True,
            env=env,
            check=False,
        )
        if result.returncode:
            raise SystemExit(
                result.stderr.decode("utf-8", errors="replace").strip()
                or f"PlantUML failed for {target}"
            )
        if args.format == "svg":
            if ET.fromstring(result.stdout).tag != "{http://www.w3.org/2000/svg}svg":
                raise SystemExit(f"Expected SVG for {target}")
        elif not result.stdout.startswith(b"\x89PNG\r\n\x1a\n"):
            raise SystemExit(f"Expected PNG for {target}")
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(result.stdout)
        print(target.relative_to(root) if target.is_relative_to(root) else target)


if __name__ == "__main__":
    main()
