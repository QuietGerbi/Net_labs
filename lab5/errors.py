"""Сопоставление системных ошибок с кодами ответа SOCKS5."""

import errno

from socks5 import REP_FAIL, REP_NETWORK, REP_HOST, REP_REFUSED

# connect_ex() вернул это — соединение устанавливается асинхронно
CONNECT_IN_PROGRESS = {
    errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EAGAIN,
    getattr(errno, "WSAEWOULDBLOCK", -1), getattr(errno, "EALREADY", -1),
}
_NET_ERRS = {errno.ENETUNREACH, getattr(errno, "ENETDOWN", -1)}
_HOST_ERRS = {errno.EHOSTUNREACH, getattr(errno, "EHOSTDOWN", -1), errno.ETIMEDOUT}


def rep_for_errno(err):
    if err == errno.ECONNREFUSED:
        return REP_REFUSED
    if err in _NET_ERRS:
        return REP_NETWORK
    if err in _HOST_ERRS:
        return REP_HOST
    return REP_FAIL
