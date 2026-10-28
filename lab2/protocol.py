import struct

MAX_NAME_BYTES = 4096
MAX_FILE_SIZE = 1 << 40

STATUS_ERROR = 0
STATUS_OK = 1

_NAME_LEN = struct.Struct(">H")
_SIZE = struct.Struct(">Q")


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
    sock.sendall(_NAME_LEN.pack(len(raw_name)) + raw_name + _SIZE.pack(size))


def read_request_header(sock):
    (name_len,) = _NAME_LEN.unpack(recv_exact(sock, _NAME_LEN.size))
    if not 0 < name_len <= MAX_NAME_BYTES:
        raise ProtocolError(f"недопустимая длина имени файла: {name_len}")
    try:
        name = recv_exact(sock, name_len).decode("utf-8")
    except UnicodeDecodeError:
        raise ProtocolError("имя файла не является корректным UTF-8")
    (size,) = _SIZE.unpack(recv_exact(sock, _SIZE.size))
    if size > MAX_FILE_SIZE:
        raise ProtocolError("заявленный размер файла превышает 1 ТиБ")
    return name, size


def send_response(sock, ok, message=""):
    sock.sendall(bytes([STATUS_OK if ok else STATUS_ERROR]))


def read_response(sock):
    (status,) = recv_exact(sock, 1)
    if status == STATUS_OK:
        return True, "сервер подтвердил сохранение файла"
    if status == STATUS_ERROR:
        return False, "сервер сообщил об ошибке (подробности в логе сервера)"
    raise ProtocolError(f"неизвестный код статуса ответа: {status}")
