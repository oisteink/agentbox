# Moby seccomp baseline

Source: [moby/profiles](https://github.com/moby/profiles/tree/4b8214fc4971e06172938a1f1554ccff6647ee80).

- Revision: `4b8214fc4971e06172938a1f1554ccff6647ee80`.
- File: `seccomp/default.json`, stored unchanged as `moby-default.json`.
- SHA-256: `6416b47770785a41ac59073cdc77d9fe98517df2799dc83ef207e622de3053f6`.
- License: Apache 2.0, included in `LICENSE`.

The generator in `src/agentbox/seccomp.py` removes filesystem Unix sockets, reconnectable datagram
socket pairs, the legacy socket syscall multiplexer and io_uring operations.
It retains connected stream socket pairs for private process communication.
The profile is exercised by the rootless lab and installed-CLI integration tests.
