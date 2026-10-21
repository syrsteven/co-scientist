"""Read-only, optimistic cross-store snapshot for observational trace exports.

Never joins scientific transactions or mutates the source. Concurrent commits
are reported as busy; no mixed-time documents are published.
"""

import sqlite3
from contextlib import ExitStack, contextmanager
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from co_scientist.adapters.persistence.sqlite import SqliteUnitOfWork


@contextmanager
def readonly_uow(path):
    path = Path(path).resolve(strict=True)
    engine = create_engine(
        "sqlite://", creator=lambda: sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    )
    view = object.__new__(SqliteUnitOfWork)
    view.engine = engine
    view.session_factory = sessionmaker(engine, expire_on_commit=False)
    # The real path is needed because the engine deliberately has no write URL.
    view.trace_database_path = path
    try:
        yield view
    finally:
        engine.dispose()


def artifact_fingerprint(stores):
    return {
        str(path): sha256(path.read_bytes()).hexdigest()
        for store in stores
        for path in sorted(store.root.glob("raw/**/*.manifest.json"))
    }


@contextmanager
def trace_snapshot(uow, artifacts, transport_artifacts):
    """Pin immutable SQLite backups; check data_version + artifact manifests.

    A source connection remains open from before each backup until after all
    references are checked. data_version detects even a commit that restores
    the same values. No reader takes a scientific write/driver lock.
    """
    source = getattr(uow, "trace_database_path", None) or uow.engine.url.database
    if not source or source == ":memory:":
        raise ValueError("trace snapshot requires an existing file-backed database")
    stores = [artifacts] + ([transport_artifacts] if transport_artifacts else [])
    paths = [Path(source).resolve(strict=True)]
    if transport_artifacts is not None:
        paths.append((transport_artifacts.root.parent / "dispatch.sqlite3").resolve(strict=True))
    with ExitStack() as stack, TemporaryDirectory(prefix="co-scientist-trace-") as temporary:
        before = artifact_fingerprint(stores)
        connections, versions, copies = [], [], []
        for number, path in enumerate(paths):
            connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
            stack.callback(connection.close)
            connections.append(connection)
            versions.append(connection.execute("PRAGMA data_version").fetchone()[0])
            copy = Path(temporary) / f"snapshot-{number}.db"
            with sqlite3.connect(copy) as destination:
                connection.backup(destination)
            copies.append(copy)
        ledger = None
        if len(copies) == 2:
            with sqlite3.connect(copies[1]) as db:
                db.row_factory = sqlite3.Row
                ledger = {
                    "path": str(paths[1]),
                    "policy": [dict(r) for r in db.execute("SELECT * FROM policy")],
                    "attempts": [
                        dict(r) for r in db.execute("SELECT * FROM attempts ORDER BY started,id")
                    ],
                }
        with readonly_uow(copies[0]) as view:
            yield view, ledger
        if before != artifact_fingerprint(stores) or any(
            connection.execute("PRAGMA data_version").fetchone()[0] != version
            for connection, version in zip(connections, versions, strict=True)
        ):
            raise ValueError(
                "trace snapshot changed during export; busy, retry at a stable boundary"
            )
