"""Разбор и формирование сообщений SOCKS5 (RFC 1928). Без работы с сокетами."""

import socket
import struct

VER = 5
METHOD_NO_AUTH = 0x00
METHOD_NONE_ACCEPTABLE = 0xFF
CMD_CONNECT = 0x01
ATYP_IPV4 = 0x01
ATYP_DOMAIN = 0x03

REP_OK = 0x00
REP_FAIL = 0x01
REP_NETWORK = 0x03
REP_HOST = 0x04
REP_REFUSED = 0x05
REP_TTL = 0x06
REP_CMD = 0x07
REP_ATYP = 0x08


class ProtocolError(Exception):
    """rep=None — просто закрыть соединение, иначе отправить ответ с этим кодом."""

    def __init__(self, rep=None):
        super().__init__(rep)
        self.rep = rep


def parse_greeting(buf):
    """None — данных мало; иначе (сколько байт съедено, предложен ли метод 0x00)."""
    if len(buf) < 2:
        return None
    if buf[0] != VER:
        raise ProtocolError()
    n = buf[1]
    if len(buf) < 2 + n:
        return None
    return 2 + n, METHOD_NO_AUTH in bytes(buf[2:2 + n])


def parse_request(buf):
    """None — данных мало; иначе (съедено, atyp, host, port).
    host — str для IPv4 и bytes для доменного имени."""
    if len(buf) < 4:
        return None
    if buf[0] != VER:
        raise ProtocolError()
    if buf[1] != CMD_CONNECT:
        raise ProtocolError(REP_CMD)
    atyp = buf[3]
    if atyp == ATYP_IPV4:
        need = 10
    elif atyp == ATYP_DOMAIN:
        if len(buf) < 5:
            return None
        need = 7 + buf[4]
    else:
        raise ProtocolError(REP_ATYP)
    if len(buf) < need:
        return None
    (port,) = struct.unpack("!H", bytes(buf[need - 2:need]))
    if atyp == ATYP_IPV4:
        host = socket.inet_ntoa(bytes(buf[4:8]))
    else:
        host = bytes(buf[5:5 + buf[4]])
    return need, atyp, host, port


def greeting_reply(no_auth_ok):
    return bytes([VER, METHOD_NO_AUTH if no_auth_ok else METHOD_NONE_ACCEPTABLE])


def build_reply(rep, ip="0.0.0.0", port=0):
    return bytes([VER, rep, 0x00, ATYP_IPV4]) + socket.inet_aton(ip) + struct.pack("!H", port)
