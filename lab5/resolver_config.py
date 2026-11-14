"""Определение адреса DNS-резолвера."""

import ipaddress
import os
import re
import subprocess
import sys


def parse_hostport(text):
    """'1.1.1.1:53' -> ('1.1.1.1', 53). ValueError при неверном формате."""
    host, _, port = text.rpartition(":")
    ipaddress.IPv4Address(host)
    port = int(port)
    if not 1 <= port <= 65535:
        raise ValueError("port")
    return host, port


def system_resolver():
    """Системный DNS (IPv4) и порт 53."""
    try:
        with open("/etc/resolv.conf") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2 and parts[0] == "nameserver":
                    try:
                        return str(ipaddress.IPv4Address(parts[1])), 53
                    except ValueError:
                        continue
    except OSError:
        pass
    if os.name == "nt":
        try:
            out = subprocess.run(["ipconfig", "/all"], capture_output=True, text=True,
                                 timeout=5, errors="replace").stdout
            m = re.search(r"DNS[^:\n]*:\s*(\d+\.\d+\.\d+\.\d+)", out)
            if m:
                return m.group(1), 53
        except Exception:
            pass
    print("Не удалось определить системный DNS, используется 8.8.8.8:53", file=sys.stderr)
    return "8.8.8.8", 53
