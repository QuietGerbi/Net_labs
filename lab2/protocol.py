import struct

MAGIC = b"FTP1"
MAX_NAME_BYTES = 4096
MAX_FILE_SIZE = 1 << 40          
MAX_MESSAGE_BYTES = 1024

STATUS_OK = 0
STATUS_ERROR = 1

_PREFIX = struct.Struct(">4sH")
_SIZE = struct.Struct(">Q")
_RESPONSE = struct.Struct(">BH")


class ProtocolError(Exception):
    """Нарушение протокола или некорректные данные."""


def recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ProtocolError("соединение закрыто раньше времени")
        buf += chunk
    return bytes(buf)


def send_request_header(sock, name, size):
    try:
        raw_name = name.encode("utf-8")
    except UnicodeEncodeError as e:
        raise ProtocolError(f"имя файла нельзя закодировать в UTF-8: {e}")
    if not 0 < len(raw_name) <= MAX_NAME_BYTES:
        raise ProtocolError(f"длина имени файла должна быть 1..{MAX_NAME_BYTES} байт")
    if not 0 <= size <= MAX_FILE_SIZE:
        raise ProtocolError("размер файла превышает 1 ТиБ")
    sock.sendall(_PREFIX.pack(MAGIC, len(raw_name)) + raw_name + _SIZE.pack(size))


def read_request_header(sock):
    magic, name_len = _PREFIX.unpack(recv_exact(sock, _PREFIX.size))
    if magic != MAGIC:
        raise ProtocolError("неверная сигнатура протокола")
    if not 0 < name_len <= MAX_NAME_BYTES:
        raise ProtocolError("недопустимая длина имени файла")
    try:
        name = recv_exact(sock, name_len).decode("utf-8")
    except UnicodeDecodeError:
        raise ProtocolError("имя файла не является корректным UTF-8")
    (size,) = _SIZE.unpack(recv_exact(sock, _SIZE.size))
    if size > MAX_FILE_SIZE:
        raise ProtocolError("заявленный размер файла превышает 1 ТиБ")
    return name, size

def truncate_utf8(text, max_bytes):
    raw = text.encode("utf-8", errors="replace")
    if len(raw) <= max_bytes:
        return raw
    return raw[:max_bytes].decode("utf-8", errors="ignore").encode("utf-8")

def send_response(sock, ok, message=""):
    raw = truncate_utf8(message, MAX_MESSAGE_BYTES)
    status = STATUS_OK if ok else STATUS_ERROR
    sock.sendall(_RESPONSE.pack(status, len(raw)) + raw)


def read_response(sock):
    status, length = _RESPONSE.unpack(recv_exact(sock, _RESPONSE.size))
    if status not in (STATUS_OK, STATUS_ERROR):
        raise ProtocolError(f"неизвестный код статуса ответа: {status}")
    if length > MAX_MESSAGE_BYTES:
        raise ProtocolError(
            f"длина сообщения в ответе превышает {MAX_MESSAGE_BYTES} байт")
    try:
        message = recv_exact(sock, length).decode("utf-8")
    except UnicodeDecodeError:
        raise ProtocolError("сообщение в ответе не является корректным UTF-8")
    return status == STATUS_OK, message
