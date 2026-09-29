import socket
import struct
import sys
import time
import threading
import uuid
from datetime import datetime


class MulticastDiscovery:
    ANNOUNCE_INTERVAL = 2.0
    PEER_TIMEOUT = 6.0
    BUFFER_SIZE = 1024

    IPV4_MULTICAST_MIN = "224.0.0.0"
    IPV4_MULTICAST_MAX = "239.255.255.255"

    def __init__(self, group_addr: str, port: int = 60000):
        if isinstance(port, bool) or not isinstance(port, int):
            raise TypeError(
                f"Порт должен быть int, получено {type(port).__name__}"
            )
        
        if not (1 <= port <= 65535):
            raise ValueError(
                f"Некорректный порт: {port}. Допустимый диапазон: 1..65535"
            )
        
        self.group_addr = group_addr
        self.port = port

        self.instance_id = str(uuid.uuid4())

        self.family, self.is_ipv6 = self._validate_group_addr(group_addr)

        self.peers = {}
        self.peers_lock = threading.Lock()

        self.running = True

        self.sock = socket.socket(self.family, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass

        if self.is_ipv6:
            self.sock.bind(("::", port))
        else:
            self.sock.bind(("", port))

        self._join_group()

        if self.is_ipv6:
            self.sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_HOPS, 1)
        else:
            self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
            try:
                self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_ALL, 0)
            except (AttributeError, OSError):
                pass

        self.sock.settimeout(0.5)

    def _validate_group_addr(self, group_addr: str):
        try:
            packed = socket.inet_pton(socket.AF_INET, group_addr)
            family = socket.AF_INET
            is_ipv6 = False
        except OSError:
            try:
                packed = socket.inet_pton(socket.AF_INET6, group_addr)
                family = socket.AF_INET6
                is_ipv6 = True
            except OSError:
                raise ValueError(f"Некорректный IP-адрес: {group_addr}")

        if is_ipv6:
            if packed[0] != 0xFF:
                raise ValueError(
                    f"Адрес {group_addr} не является multicast "
                    f"(IPv6 multicast должен начинаться с ff00::/8)"
                )
        else:
            first_octet = packed[0]
            if not (0xE0 <= first_octet <= 0xEF):
                raise ValueError(
                    f"Адрес {group_addr} не является multicast "
                    f"(допустимый диапазон: {self.IPV4_MULTICAST_MIN} - "
                    f"{self.IPV4_MULTICAST_MAX})"
                )

        return family, is_ipv6

    def _join_group(self):
        if self.is_ipv6:
            group_bin = socket.inet_pton(socket.AF_INET6, self.group_addr)
            self.if_index = 0

            for index, name in socket.if_nameindex():
                mreq = group_bin + struct.pack("@I", index)
                try:
                    self.sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_JOIN_GROUP, mreq)
                    self.if_index = index
                    break
                except OSError:
                    continue

            if self.if_index == 0:
                raise OSError("Не найден интерфейс с поддержкой IPv6 multicast")
        else:
            mreq = socket.inet_aton(self.group_addr) + struct.pack("=I", socket.INADDR_ANY)
            self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

    def _make_message(self, msg_type: str) -> bytes:
        return f"{msg_type}|{self.instance_id}".encode("utf-8")

    def _dest(self):
        if self.is_ipv6:
            return (self.group_addr, self.port, 0, self.if_index)
        return (self.group_addr, self.port)

    def _send(self, msg_type: str):
        try:
            self.sock.sendto(self._make_message(msg_type), self._dest())
        except OSError as e:
            print(f"[!] Ошибка отправки {msg_type}: {e}", file=sys.stderr)

    def _sender_loop(self):
        self._send("ANNOUNCE")
        while self.running:
            time.sleep(self.ANNOUNCE_INTERVAL)
            self._send("ANNOUNCE")

    def _receiver_loop(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(self.BUFFER_SIZE)
            except socket.timeout:
                continue
            except OSError:
                if self.running:
                    continue
                break

            self._handle_message(data, addr)

    def _handle_message(self, data: bytes, addr):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return

        if "|" not in text:
            return
        msg_type, instance_id = text.split("|", 1)
        if instance_id == self.instance_id:
            return

        ip = addr[0]
        now = time.monotonic()

        if msg_type == "ANNOUNCE":
            with self.peers_lock:
                self.peers[instance_id] = (ip, now)

        elif msg_type == "BYE":
            with self.peers_lock:
                self.peers.pop(instance_id, None)

    def _prune_loop(self):
        while self.running:
            time.sleep(1.0)
            now = time.monotonic()
            with self.peers_lock:
                dead = [pid for pid, (_, ts) in self.peers.items()
                        if now - ts > self.PEER_TIMEOUT]
                for pid in dead:
                    del self.peers[pid]

    def _report_loop(self):
        prev_peers = frozenset()

        while self.running:
            time.sleep(0.5)
            with self.peers_lock:
                current_items = [
                    (pid, ip) for pid, (ip, _) in self.peers.items()
                ]

            current_peers = frozenset(current_items)

            if current_peers != prev_peers:
                prev_peers = current_peers
                ips = sorted({ip for _, ip in current_items})
                self._print_peers(ips, len(current_items))

    def _print_peers(self, ips, count):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"\n[{ts}] Мой ID: {self.instance_id[:8]}")
        if count == 0:
            print("  Живых копий не обнаружено.")
        else:
            print(f"  Живых копий: {count}, уникальных IP: {len(ips)}")
            for ip in ips:
                print(f"    - {ip}")
        sys.stdout.flush()

    def run(self):
        print(f"=== Multicast Discovery ===")
        print(f"Группа: {self.group_addr}:{self.port}")
        print(f"Протокол: {'IPv6' if self.is_ipv6 else 'IPv4'}")
        print(f"ID инстанса: {self.instance_id}")
        print("Для выхода нажмите Ctrl+C\n")

        threads = [
            threading.Thread(target=self._receiver_loop, daemon=True),
            threading.Thread(target=self._sender_loop, daemon=True),
            threading.Thread(target=self._prune_loop, daemon=True),
            threading.Thread(target=self._report_loop, daemon=True),
        ]
        for t in threads:
            t.start()

        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\nЗавершение...")
        finally:
            self.stop()

    def stop(self):
        if not self.running:
            return
        self.running = False
        self._send("BYE")
        try:
            self.sock.close()
        except OSError:
            pass