#!/usr/bin/env python3
"""HTTP/TLS/DNS fixture, started only in the disposable lab's endpoint netns."""

import http.server
import json
import socketserver
import ssl
import struct
import sys
import threading


def event(kind, **values):
    print(json.dumps({"kind": kind, **values}), flush=True)


class HTTP(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        event("http", port=self.server.server_port, path=self.path)
        body = b"agentbox-controlled-endpoint\n"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


class DNS(socketserver.BaseRequestHandler):
    def handle(self):
        request, sock = self.request
        event("dns", query=request[12:].hex())
        # NXDOMAIN, echo question; sufficient to prove packets reached the resolver.
        if len(request) >= 12:
            end = 12
            while end < len(request) and request[end]:
                end += request[end] + 1
            end += 5  # terminating zero, QTYPE and QCLASS; omit any EDNS record
            header = request[:2] + struct.pack("!HHHHH", 0x8183, 1, 0, 0, 0)
            sock.sendto(header + request[12:end], self.client_address)


def main():
    plain = http.server.ThreadingHTTPServer(("0.0.0.0", 80), HTTP)
    https = http.server.ThreadingHTTPServer(("0.0.0.0", 443), HTTP)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(sys.argv[1], sys.argv[2])
    https.socket = context.wrap_socket(https.socket, server_side=True)
    dns = socketserver.UDPServer(("93.184.216.34", 53), DNS)
    for service in (plain, https, dns):
        threading.Thread(target=service.serve_forever, daemon=True).start()
    event("ready")
    threading.Event().wait()


if __name__ == "__main__":
    main()
