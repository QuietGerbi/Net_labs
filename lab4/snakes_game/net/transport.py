from __future__ import annotations

import logging
import socket
from typing import Iterable, List, Set, Tuple

from .. import constants as C
from ..model import Endpoint

log = logging.getLogger(__name__)

RECV_BUFFER = 65535
MAX_READS_PER_CALL = 256


def _recv_all(sock: socket.socket) -> List[Tuple[bytes, Endpoint]]:
    out: List[Tuple[bytes, Endpoint]] = []
    for _ in range(MAX_READS_PER_CALL):
        try:
            data, addr = sock.recvfrom(RECV_BUFFER)
        except (BlockingIOError, InterruptedError):
            break
        except OSError:
            continue
        out.append((data, (addr[0], addr[1])))
    return out


class UdpSocket:

    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", 0))
        self.sock.setblocking(False)
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)

    @property
    def port(self) -> int:
        return self.sock.getsockname()[1]

    def fileno(self) -> int:
        return self.sock.fileno()

    def sendto(self, data: bytes, ep: Endpoint) -> bool:
        try:
            self.sock.sendto(data, ep)
            return True
        except OSError as e:
            log.debug("sendto %s: %s", ep, e)
            return False

    def send_multicast(self, data: bytes, interface_ips: Iterable[str]) -> int:
        sent = 0
        for ip in interface_ips:
            try:
                self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
                self.sock.sendto(data, (C.MULTICAST_GROUP, C.MULTICAST_PORT))
                sent += 1
            except OSError as e:
                log.debug("multicast via %s: %s", ip, e)
        return sent

    def recv_all(self) -> List[Tuple[bytes, Endpoint]]:
        return _recv_all(self.sock)

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class MulticastReceiver:

    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        self.sock.bind(("", C.MULTICAST_PORT))
        self.sock.setblocking(False)
        self._joined: Set[str] = set()

    def fileno(self) -> int:
        return self.sock.fileno()

    def join_interfaces(self, interface_ips: Iterable[str]) -> None:
        group = socket.inet_aton(C.MULTICAST_GROUP)
        for ip in interface_ips:
            if ip in self._joined:
                continue
            try:
                mreq = group + socket.inet_aton(ip)
                self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
                self._joined.add(ip)
            except OSError as e:
                log.debug("join multicast on %s: %s", ip, e)

    def recv_all(self) -> List[Tuple[bytes, Endpoint]]:
        return _recv_all(self.sock)

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass
