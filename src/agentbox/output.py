"""Shared public results, human rendering and noninteractive confirmation."""

import json
import sys

from .errors import AgentboxError


def success(data=None, exit_code=None):
    result = {"type": "result", "ok": True, "data": data}
    if exit_code is not None:
        result["exit_code"] = exit_code
        if exit_code:
            result.update(
                ok=False,
                error={
                    "code": "interrupted" if exit_code == 130 else "command_failed",
                    "message": "Interrupted" if exit_code == 130 else "Command failed",
                },
            )
    return result


def failure(code, message, *, details=None, exit_code=None):
    result = {"type": "result", "ok": False, "error": {"code": code, "message": message}}
    if details is not None:
        result["error"]["details"] = details
    if exit_code is not None:
        result["exit_code"] = exit_code
    return result


def write_frame(frame):
    print(json.dumps(frame, ensure_ascii=True), flush=True)


def confirm(message, affected, *, json_mode=False, yes=False):
    if yes:
        return
    if not json_mode and sys.stdin.isatty() and input(f"{message} [y/N] ").lower() == "y":
        return
    raise AgentboxError(message, code="confirmation_required", details={"affected": affected})


def human(data, *, table=False):
    if isinstance(data, str):
        print(data, end="" if data.endswith("\n") else "\n")
    elif table and isinstance(data, dict):
        last = "IMAGE" if table == "status" else "PATH"
        rows = [["NAME", "STATUS", last]]
        for name, entry in data.items():
            value = (
                entry.get("config", {}).get("image", "—")
                if table == "status"
                else entry.get("path", "—")
            )
            rows.append([name, str(entry.get("status", "—")), str(value)])
        widths = [max(len(row[i]) for row in rows) for i in range(3)]
        for row in rows:
            print("  ".join(value.ljust(width) for value, width in zip(row, widths)).rstrip())
    elif isinstance(data, dict | list):

        def fields(value, indent=0):
            prefix = " " * indent
            pairs = value.items() if isinstance(value, dict) else (("-", item) for item in value)
            for key, item in pairs:
                if isinstance(item, dict | list) and item:
                    print(f"{prefix}{key}:")
                    fields(item, indent + 2)
                else:
                    print(f"{prefix}{key}: {item}")

        fields(data)
    elif data is not None:
        print(data)


class Output:
    def __init__(self, json_mode=False):
        self.json_mode = json_mode

    def event(self, stream, data):
        if self.json_mode:
            write_frame({"type": "output", "stream": stream, "data": data})
        else:
            target = sys.stderr if stream == "stderr" else sys.stdout
            target.write(data)
            target.flush()

    def finish(self, frame, *, table=False):
        if self.json_mode:
            write_frame(frame)
            return 0
        if not frame["ok"]:
            print(f"abx: {frame['error']['message']}", file=sys.stderr)
        elif "exit_code" not in frame:
            human(frame.get("data"), table=table)
        return frame.get("exit_code", 0 if frame["ok"] else 2)
