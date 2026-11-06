"""Drain a process while optionally forwarding input, without input threads."""

import codecs
import os
import selectors
import signal
import subprocess
import sys


def pump(process, emit, *, source=None, prefix=b"", interrupt=None):
    """Keep bounded buffers; detect child exit even when input stays open."""
    decoders = {
        name: codecs.getincrementaldecoder("utf-8")("replace") for name in ("stdout", "stderr")
    }
    interrupted = False
    with selectors.PollSelector() as selector:
        for name in decoders:
            pipe = getattr(process, name)
            if pipe is not None:
                selector.register(pipe, selectors.EVENT_READ, name)
        pending = prefix
        input_open = source is not None
        if input_open and not pending:
            selector.register(source, selectors.EVENT_READ, "input")
        if process.stdin:
            os.set_blocking(process.stdin.fileno(), False)
            if pending:
                selector.register(process.stdin, selectors.EVENT_WRITE, "write")
            elif not input_open:
                process.stdin.close()
        outputs = sum(getattr(process, name) is not None for name in decoders)
        while outputs or process.poll() is None:
            try:
                events = selector.select(timeout=0.2)
                for key, _ in events:
                    if key.data == "input":
                        pending = os.read(key.fd, 65536)
                        selector.unregister(key.fileobj)
                        if not pending:
                            input_open = False
                            if process.stdin and not process.stdin.closed:
                                process.stdin.close()
                        elif process.stdin and not process.stdin.closed:
                            selector.register(process.stdin, selectors.EVENT_WRITE, "write")
                    elif key.data == "write":
                        try:
                            pending = pending[os.write(key.fd, pending) :]
                        except BrokenPipeError:
                            pending = b""
                            input_open = False
                            if source is not None:
                                try:
                                    selector.unregister(source)
                                except KeyError:
                                    pass
                        if not pending:
                            selector.unregister(key.fileobj)
                            if input_open:
                                selector.register(source, selectors.EVENT_READ, "input")
                            else:
                                process.stdin.close()
                    else:
                        block = os.read(key.fd, 65536)
                        text = decoders[key.data].decode(block, final=not block)
                        if text:
                            emit(key.data, text)
                        if not block:
                            selector.unregister(key.fileobj)
                            key.fileobj.close()
                            outputs -= 1
            except KeyboardInterrupt:
                interrupted = True
                if interrupt:
                    interrupt(process)
                else:
                    process.send_signal(signal.SIGINT)
        if process.stdin and not process.stdin.closed:
            process.stdin.close()
        while True:
            try:
                code = process.wait()
                return 130 if interrupted else code
            except KeyboardInterrupt:
                interrupted = True
                process.send_signal(signal.SIGINT)


def run(command, emit, *, cwd=None):
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    return pump(process, emit, source=sys.stdin.buffer)
