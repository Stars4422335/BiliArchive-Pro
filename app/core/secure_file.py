import os
import tempfile


def _set_permissions(path, mode):
    """Best-effort permissions; Windows still follows directory ACLs."""
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def atomic_write_text(path, content, encoding="utf-8"):
    """Atomically replace a sensitive text file without leaving partial output."""
    absolute_path = os.path.abspath(path)
    directory = os.path.dirname(absolute_path)
    os.makedirs(directory, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.",
        suffix=".tmp",
        dir=directory,
        text=True,
    )
    handle = None
    try:
        handle = os.fdopen(fd, "w", encoding=encoding, newline="\n")
        fd = None
        with handle:
            handle.write(content)
        handle = None
        _set_permissions(temp_path, 0o600)
        os.replace(temp_path, absolute_path)
        _set_permissions(absolute_path, 0o600)
    except Exception:
        if handle is not None:
            handle.close()
        if fd is not None:
            os.close(fd)
        try:
            os.remove(temp_path)
        except FileNotFoundError:
            pass
        raise


def atomic_write_bytes(path, content, mode=0o600):
    """Atomically replace a sensitive binary file after fully writing it."""
    absolute_path = os.path.abspath(path)
    directory = os.path.dirname(absolute_path)
    os.makedirs(directory, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.",
        suffix=".tmp",
        dir=directory,
    )
    handle = None
    try:
        handle = os.fdopen(fd, "wb")
        fd = None
        with handle:
            handle.write(content)
        handle = None
        _set_permissions(temp_path, mode)
        os.replace(temp_path, absolute_path)
        _set_permissions(absolute_path, mode)
    except Exception:
        if handle is not None:
            handle.close()
        if fd is not None:
            os.close(fd)
        try:
            os.remove(temp_path)
        except FileNotFoundError:
            pass
        raise
