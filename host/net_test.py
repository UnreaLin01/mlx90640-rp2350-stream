"""UDP throughput test against the net_test firmware (M6).

Sends one small packet to the board, which then sends UDP packets back as
fast as it can for a few seconds. Each packet starts with a 4-byte counter,
so packets that go missing can be counted.

The PC sends first on purpose: the board learns where to send, and the
answers belong to a connection the PC started, so the Windows firewall
lets them in without a new rule.

Usage:
    host/.venv/Scripts/python host/net_test.py [--ip 192.168.1.200] [--wait 8]
"""

import argparse
import socket
import struct
import sys
import time

PAYLOAD_LEN = 1024


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ip", default="192.168.1.200")
    ap.add_argument("--port", type=int, default=5005)
    ap.add_argument("--wait", type=float, default=8.0, help="seconds to keep receiving")
    args = ap.parse_args()

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("0.0.0.0", 0))
    s.settimeout(1.0)
    print(f"local port {s.getsockname()[1]} -> {args.ip}:{args.port}")
    s.sendto(b"START", (args.ip, args.port))

    seqs = []
    total_bytes = 0
    t_first = t_last = None
    deadline = time.perf_counter() + args.wait
    while time.perf_counter() < deadline:
        try:
            data, _ = s.recvfrom(2048)
        except socket.timeout:
            if t_first is not None:
                break               # burst finished
            continue
        now = time.perf_counter()
        if t_first is None:
            t_first = now
        t_last = now
        total_bytes += len(data)
        if len(data) >= 4:
            seqs.append(struct.unpack_from("<I", data)[0])
    s.close()

    if not seqs:
        print("FAIL: no packets received (is net_test running? cable? IP?)")
        return 1

    duration = max(t_last - t_first, 1e-6)
    sent = seqs[-1] - seqs[0] + 1
    lost = sent - len(seqs)
    out_of_order = sum(1 for a, b in zip(seqs, seqs[1:]) if b <= a)
    print(f"received {len(seqs)} packets, {total_bytes / 1024:.0f} kB in {duration:.3f} s")
    print(f"throughput: {total_bytes / duration / 1e6 * 8:.2f} Mbit/s "
          f"({total_bytes / duration / 1024:.0f} kB/s)")
    print(f"board sent {sent} packets (by counter), lost {lost} "
          f"({100 * lost / sent:.2f}%), out of order {out_of_order}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
