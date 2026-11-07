"""Cross-process guard for the isolated classroom Demo database."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


DEMO_DIRECTORY = Path(__file__).resolve().parents[1] / ".demo"
DEMO_DATABASE = DEMO_DIRECTORY / "campushands.db"
LOCK_FILE = DEMO_DIRECTORY / "backend.lock"


class DemoLockHeld(RuntimeError):
    pass


@contextmanager
def demo_database_lock(database_file: str | None = None) -> Iterator[None]:
    """Hold a process lock only for the fixed Demo DB; other DBs are untouched."""
    if database_file is not None and Path(database_file).resolve() != DEMO_DATABASE.resolve():
        yield
        return
    if DEMO_DIRECTORY.is_symlink() or LOCK_FILE.is_symlink():
        raise DemoLockHeld("Demo lock path is a symbolic link")
    DEMO_DIRECTORY.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise DemoLockHeld("Demo database is in use by another process") from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
