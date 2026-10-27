#!/usr/bin/env python3
import socket
import sys
import time

HOST = "api.binance.com"
PORT = 443


def main():
    start = time.perf_counter()
    print(f"Checking DNS for {HOST}:{PORT} ...")
    try:
        infos = socket.getaddrinfo(HOST, PORT, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        print(f"DNS lookup failed: {exc}")
        print("")
        print("Manual fixes:")
        print("  1. Set DNS servers to 1.1.1.1 or 8.8.8.8")
        print("  2. Flush local DNS cache")
        print("  3. Disable VPN/antivirus HTTPS scanning")
        print("  4. Move the bot to a VPS or a machine with clean outbound DNS")
        sys.exit(2)

    elapsed_ms = (time.perf_counter() - start) * 1000.0
    resolved = sorted({item[4][0] for item in infos})
    print(f"Resolver: {socket.getfqdn()}")
    print(f"Latency: {elapsed_ms:.1f} ms")
    print(f"Result: {HOST} resolved to {resolved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())