"""Ядро прокси: цикл селектора, рукопожатие, DNS, подключение, передача данных."""

import errno
import ipaddress
import random
import selectors
import socket
import struct

import config
import dns_message
import socks5
from errors import CONNECT_IN_PROGRESS, rep_for_errno
from session import (Session, GREETING, REQUEST, RESOLVING, CONNECTING, RELAY, CLOSING)
from timers import Timers

EV_R = selectors.EVENT_READ
EV_W = selectors.EVENT_WRITE

_LISTEN = object()
_DNS = object()


class Proxy:
    def __init__(self, port, resolver):
        self.resolver = resolver
        self.sel = selectors.DefaultSelector()
        self.timers = Timers()
        self.pending = {}          # dns id -> Session

        self.lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.lsock.bind(("0.0.0.0", port))
        self.lsock.listen(config.LISTEN_BACKLOG)
        self.lsock.setblocking(False)
        self.sel.register(self.lsock, EV_R, _LISTEN)

        self.dsock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.dsock.setblocking(False)
        self.sel.register(self.dsock, EV_R, _DNS)

    # ------------------------------------------------------------- главный цикл
    def run(self):
        while True:
            for key, mask in self.sel.select(self.timers.next_timeout()):
                data = key.data
                if data is _LISTEN:
                    self.on_accept()
                elif data is _DNS:
                    self.on_dns()
                else:
                    s, is_client = data
                    if s.closed:
                        continue
                    if is_client:
                        self.on_client(s, mask)
                    else:
                        self.on_remote(s, mask)
            for s in self.timers.pop_expired():
                self.on_timeout(s)

    def on_timeout(self, s):
        if s.state in (GREETING, REQUEST):
            self.close(s)
        elif s.state == RESOLVING:
            if s.attempts < config.DNS_ATTEMPTS:
                self.send_dns(s)
            else:
                self.pending.pop(s.dns_id, None)
                s.dns_id = None
                self.reply_error(s, socks5.REP_HOST)
        elif s.state == CONNECTING:
            s.last_rep = socks5.REP_HOST
            self.drop_remote(s)
            self.connect_next(s)

    # ------------------------------------------------------------- accept
    def on_accept(self):
        for _ in range(64):
            try:
                conn, _ = self.lsock.accept()
            except OSError:        # в т.ч. BlockingIOError — очередь пуста
                return
            conn.setblocking(False)
            try:
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
            s = Session(conn)
            self.timers.set(s, config.HANDSHAKE_TIMEOUT)
            self.update(s)

    # ------------------------------------------------------------- подписки селектора
    @staticmethod
    def client_events(s):
        ev = 0
        if s.state in (GREETING, REQUEST):
            ev |= EV_R
        elif s.state == RELAY and not s.c_eof and len(s.c2r) < config.BUF_SIZE:
            ev |= EV_R
        if s.r2c:
            ev |= EV_W
        return ev

    @staticmethod
    def remote_events(s):
        if s.rsock is None:
            return 0
        if s.state == CONNECTING:
            return EV_W
        ev = 0
        if s.state == RELAY:
            if not s.r_eof and len(s.r2c) < config.BUF_SIZE:
                ev |= EV_R
            if s.c2r:
                ev |= EV_W
        return ev

    def _sync(self, sock, cur, want, data):
        if want == cur:
            return cur
        if want == 0:
            self.sel.unregister(sock)
        elif cur == 0:
            self.sel.register(sock, want, data)
        else:
            self.sel.modify(sock, want, data)
        return want

    def update(self, s):
        if s.closed:
            return
        s.cmask = self._sync(s.csock, s.cmask, self.client_events(s), (s, True))
        if s.rsock is not None:
            s.rmask = self._sync(s.rsock, s.rmask, self.remote_events(s), (s, False))

    def drop_remote(self, s):
        if s.rsock is None:
            return
        if s.rmask:
            try:
                self.sel.unregister(s.rsock)
            except (KeyError, ValueError):
                pass
        s.rmask = 0
        try:
            s.rsock.close()
        except OSError:
            pass
        s.rsock = None

    def close(self, s):
        if s.closed:
            return
        s.closed = True
        self.timers.cancel(s)
        if s.dns_id is not None:
            self.pending.pop(s.dns_id, None)
        self.drop_remote(s)
        if s.cmask:
            try:
                self.sel.unregister(s.csock)
            except (KeyError, ValueError):
                pass
        s.cmask = 0
        try:
            s.csock.close()
        except OSError:
            pass
        s.c2r.clear()
        s.r2c.clear()

    # ------------------------------------------------------------- события сокетов
    def on_client(self, s, mask):
        if mask & EV_R:
            if s.state in (GREETING, REQUEST):
                self.read_handshake(s)
            elif s.state == RELAY:
                self.relay_read(s, True)
        if s.closed:
            return
        self.progress(s)

    def on_remote(self, s, mask):
        if s.state == CONNECTING:
            self.finish_connect(s)
            return
        if s.state == RELAY and mask & EV_R:
            self.relay_read(s, False)
        if s.closed:
            return
        self.progress(s)

    # ------------------------------------------------------------- рукопожатие
    def read_handshake(self, s):
        try:
            data = s.csock.recv(config.HS_RECV_SIZE)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            self.close(s)
            return
        if not data:
            self.close(s)
            return
        s.hs.extend(data)
        self.parse_handshake(s)

    def parse_handshake(self, s):
        hs = s.hs
        try:
            if s.state == GREETING:
                res = socks5.parse_greeting(hs)
                if res is None:
                    return
                used, no_auth_ok = res
                del hs[:used]
                s.r2c.extend(socks5.greeting_reply(no_auth_ok))
                if not no_auth_ok:
                    s.state = CLOSING
                    self.timers.cancel(s)
                    return
                s.state = REQUEST
            res = socks5.parse_request(hs)
            if res is None:
                return
        except socks5.ProtocolError as e:
            if e.rep is None:
                self.close(s)
            else:
                self.reply_error(s, e.rep)
            return
        used, atyp, host, s.port = res
        del hs[:used]
        s.c2r.extend(hs)           # данные, присланные клиентом сразу вслед за запросом
        hs.clear()
        self.start_connect(s, atyp, host)

    def reply_error(self, s, rep):
        if s.closed:
            return
        self.timers.cancel(s)
        self.drop_remote(s)
        s.r2c.extend(socks5.build_reply(rep))
        s.state = CLOSING
        self.progress(s)

    # ------------------------------------------------------------- резолвинг
    def start_connect(self, s, atyp, host):
        if atyp == socks5.ATYP_IPV4:
            s.addrs = [host]
            self.connect_next(s)
            return
        try:
            name = dns_message.decode_hostname(host)
        except ValueError:
            self.reply_error(s, socks5.REP_HOST)
            return
        try:                       # доменное имя может оказаться IPv4-литералом
            s.addrs = [str(ipaddress.IPv4Address(name))]
            self.connect_next(s)
            return
        except ValueError:
            pass
        try:
            s.qwire = dns_message.encode_name(name)
        except (ValueError, UnicodeError):
            self.reply_error(s, socks5.REP_HOST)
            return
        s.qname = name.rstrip(".").lower()
        s.state = RESOLVING
        s.attempts = 0
        while True:
            qid = random.getrandbits(16)
            if qid not in self.pending:
                break
        s.dns_id = qid
        self.pending[qid] = s
        self.update(s)             # пока резолвим, клиента не слушаем
        self.send_dns(s)

    def send_dns(self, s):
        s.attempts += 1
        try:
            self.dsock.sendto(dns_message.build_query(s.dns_id, s.qwire), self.resolver)
        except OSError:
            pass                   # потерянный запрос = сработает тайм-аут и повтор
        self.timers.set(s, config.DNS_TIMEOUT)

    def on_dns(self):
        for _ in range(256):
            try:
                data, addr = self.dsock.recvfrom(4096)
            except (BlockingIOError, InterruptedError):
                return
            except ConnectionError:
                continue           # Windows: ICMP port unreachable
            except OSError:
                return
            if addr != self.resolver or len(data) < 2:
                continue
            (qid,) = struct.unpack("!H", data[:2])
            s = self.pending.get(qid)
            if s is None or s.closed or s.state != RESOLVING:
                continue
            addrs = dns_message.parse_response(data, s.qname)
            if addrs is None:
                continue
            del self.pending[qid]
            s.dns_id = None
            self.timers.cancel(s)
            if not addrs:
                self.reply_error(s, socks5.REP_HOST)
                continue
            s.addrs = addrs
            self.connect_next(s)

    # ------------------------------------------------------------- подключение к серверу
    def connect_next(self, s):
        while s.addrs:
            ip = s.addrs.pop(0)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setblocking(False)
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
            try:
                err = sock.connect_ex((ip, s.port))
            except OSError as e:
                err = e.errno or errno.EIO
            if err == 0:
                s.rsock = sock
                self.connected(s)
                return
            if err in CONNECT_IN_PROGRESS:
                s.rsock = sock
                s.state = CONNECTING
                self.timers.set(s, config.CONNECT_TIMEOUT)
                self.update(s)
                return
            s.last_rep = rep_for_errno(err)
            sock.close()
        self.reply_error(s, s.last_rep)

    def finish_connect(self, s):
        try:
            err = s.rsock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        except OSError as e:
            err = e.errno or errno.EIO
        if err == 0:
            self.connected(s)
        else:
            s.last_rep = rep_for_errno(err)
            self.drop_remote(s)
            self.connect_next(s)

    def connected(self, s):
        try:
            host, port = s.rsock.getsockname()[:2]
            reply = socks5.build_reply(socks5.REP_OK, host, port)
        except (OSError, ValueError):
            reply = socks5.build_reply(socks5.REP_OK)
        s.r2c.extend(reply)
        s.state = RELAY
        self.timers.cancel(s)
        self.progress(s)

    # ------------------------------------------------------------- передача данных
    def relay_read(self, s, from_client):
        src, buf = (s.csock, s.c2r) if from_client else (s.rsock, s.r2c)
        if len(buf) >= config.BUF_SIZE:
            return
        try:
            data = src.recv(config.BUF_SIZE)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            self.close(s)
            return
        if data:
            buf.extend(data)
        elif from_client:
            s.c_eof = True
        else:
            s.r_eof = True

    def flush(self, s, to_client):
        sock, buf = (s.csock, s.r2c) if to_client else (s.rsock, s.c2r)
        if not buf or sock is None:
            return
        try:
            n = sock.send(buf)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            self.close(s)
            return
        del buf[:n]

    @staticmethod
    def _shutdown_wr(sock):
        try:
            sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass

    def progress(self, s):
        """Отправляет накопленное, обрабатывает half-close и обновляет подписки."""
        if s.closed:
            return
        self.flush(s, True)
        if s.closed:
            return
        if s.state == RELAY:
            self.flush(s, False)
            if s.closed:
                return
            if s.c_eof and not s.c2r and not s.r_shut:
                s.r_shut = True
                self._shutdown_wr(s.rsock)
            if s.r_eof and not s.r2c and not s.c_shut:
                s.c_shut = True
                self._shutdown_wr(s.csock)
            if s.c_eof and s.r_eof and not s.c2r and not s.r2c:
                self.close(s)
                return
        elif s.state == CLOSING and not s.r2c:
            self._shutdown_wr(s.csock)
            self.close(s)
            return
        self.update(s)
