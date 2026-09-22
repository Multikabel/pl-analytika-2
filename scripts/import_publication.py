"""Publish an already committed import and its exports, restoring on exceptions.

This is exception recovery, not crash-atomic publication for concurrent readers.
run() holds import_lock throughout validation, staging, publication and recovery.
"""
from contextlib import contextmanager
import errno
from pathlib import Path
import os
import shutil
import time


@contextmanager
def import_lock(database):
    """Serialize processes using a stable lock file beside the resolved database.

    Never unlink the file: waiters must continue locking the same inode. The OS
    releases the lock when the handle closes, including after process exit.
    """
    database = Path(database).resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    with open(str(database) + ".import.lock", "a+b") as handle:
        if os.name == "nt":
            import msvcrt
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            while True:
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as error:
                    if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise
                    time.sleep(.05)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def publish_import(database, tables, staged_database, staged_tables, backup_dir):
    database, tables, backup_dir = map(Path, (database, tables, backup_dir))
    files = [(p, tables / p.name) for p in sorted(Path(staged_tables).glob("*.csv"))]
    files.append((Path(staged_database), database))
    backup_dir.mkdir()
    backups = {}
    # Complete all backups before replacing even the first published file.
    for index, (_, target) in enumerate(files):
        backup = backup_dir / str(index)
        if target.exists():
            shutil.copy2(target, backup)
            backups[target] = backup
        else:
            backups[target] = None
    attempted = []
    try:
        for source, target in files:
            attempted.append(target)
            os.replace(source, target)
    except BaseException:
        errors = []
        for target in reversed(attempted):
            try:
                backup = backups[target]
                if backup is None:
                    target.unlink(missing_ok=True)
                else:
                    os.replace(backup, target)
            except OSError as error:
                errors.append(f"{target}: {error}")
        if errors:
            # Caller retains the staging directory when recovery itself fails.
            raise ImportRecoveryError(
                f"Import recovery failed; backups retained at {backup_dir}: {'; '.join(errors)}")
        raise


class ImportRecoveryError(RuntimeError):
    pass
