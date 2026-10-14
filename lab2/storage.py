import os

_FORBIDDEN = '<>:"|?*'
_MAX_BASE_BYTES = 240    


def _truncate_utf8(text, max_bytes):
    return text.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")


def sanitize_filename(name):
    name = name.replace("\\", "/").split("/")[-1]
    name = "".join("_" if (ch in _FORBIDDEN or ch < " " or ch == "\x7f") else ch
                   for ch in name)
    name = name.strip().rstrip(". ")
    if name in ("", ".", ".."):
        name = "file"
    stem, ext = os.path.splitext(name)
    ext = _truncate_utf8(ext, 32)
    stem = _truncate_utf8(stem, _MAX_BASE_BYTES - len(ext.encode("utf-8")))
    return (stem or "file") + ext


def _is_inside(directory, path):
    directory = os.path.realpath(directory)
    path = os.path.realpath(path)
    return os.path.commonpath([directory, path]) == directory


def create_upload_file(uploads_dir, requested_name):
    safe = sanitize_filename(requested_name)
    stem, ext = os.path.splitext(safe)
    flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL
             | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))

    for i in range(100000):
        candidate = safe if i == 0 else f"{stem} ({i}){ext}"
        path = os.path.join(uploads_dir, candidate)
        if not _is_inside(uploads_dir, path) or os.path.dirname(
                os.path.abspath(path)) != os.path.abspath(uploads_dir):
            raise OSError("недопустимый путь назначения")
        try:
            fd = os.open(path, flags, 0o644)
        except FileExistsError:
            continue
        return os.fdopen(fd, "wb"), path
    raise OSError("не удалось подобрать свободное имя файла")
