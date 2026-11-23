from __future__ import annotations

import socket
from typing import List


def _fallback() -> List[str]:
    ips: List[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.append(info[4][0])
    except OSError:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 9))
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    ips.append("127.0.0.1")
    return ips


def local_ipv4_addresses() -> List[str]:
    ips: List[str] = []
    try:
        import psutil

        stats = psutil.net_if_stats()
        for name, addrs in psutil.net_if_addrs().items():
            st = stats.get(name)
            if st is not None and not st.isup:
                continue
            for a in addrs:
                if a.family == socket.AF_INET and a.address:
                    ips.append(a.address)
    except Exception:
        ips = _fallback()
    seen, result = set(), []
    for ip in ips:
        if ip not in seen and not ip.startswith("0."):
            seen.add(ip)
            result.append(ip)
    return result
