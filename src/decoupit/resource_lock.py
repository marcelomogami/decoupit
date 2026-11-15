"""Cross-process serialization for heavy local processing."""

from __future__ import annotations

import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO


@contextmanager
def exclusive_heavy_job(database_path: Path) -> Iterator[IO[bytes]]:
    lock_path = database_path.parent / "heavy-job.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        yield lock_file
