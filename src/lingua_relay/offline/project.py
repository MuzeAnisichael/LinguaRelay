from __future__ import annotations

import sqlite3
import threading
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class OfflineProject:
    id: str
    title: str
    kind: str
    source_path: Path | None
    audio_path: Path | None
    source_language: str
    target_language: str
    status: str
    progress: float
    error: str
    duration_ms: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class Cue:
    id: int | None
    project_id: str
    position: int
    start_ms: int
    end_ms: int
    source_text: str
    translated_text: str
    confidence: float | None = None
    words_json: str = "[]"


class OfflineProjectStore:
    """SQLite catalog plus per-project media directories.

    SQLite is only opened for the duration of each operation, which keeps the
    UI and processing worker independent and makes abrupt shutdown recovery
    straightforward.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.database_path = self.root / "projects.sqlite3"
        self._lock = threading.RLock()
        self._initialize()

    def project_dir(self, project_id: str) -> Path:
        if not project_id or any(char not in "0123456789abcdef-" for char in project_id.lower()):
            raise ValueError("invalid project id")
        target = (self.root / project_id).resolve(strict=False)
        if target.parent != self.root.resolve(strict=False):
            raise ValueError("project path escaped the projects directory")
        target.mkdir(parents=True, exist_ok=True)
        return target

    def create_project(
        self,
        *,
        title: str,
        kind: str,
        source_language: str,
        target_language: str,
        source_path: str | Path | None = None,
        status: str = "ready",
    ) -> OfflineProject:
        if kind not in {"recording", "audio", "video"}:
            raise ValueError(f"unsupported project kind: {kind}")
        project_id = str(uuid.uuid4())
        timestamp = _now()
        normalized_title = title.strip() or f"LinguaRelay {timestamp[:19]}"
        source = str(Path(source_path).resolve()) if source_path else None
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO projects (
                    id, title, kind, source_path, audio_path, source_language,
                    target_language, status, progress, error, duration_ms,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, NULL, ?, ?, ?, 0, '', 0, ?, ?)
                """,
                (
                    project_id,
                    normalized_title,
                    kind,
                    source,
                    source_language,
                    target_language,
                    status,
                    timestamp,
                    timestamp,
                ),
            )
        self.project_dir(project_id)
        return self.get_project(project_id)

    def get_project(self, project_id: str) -> OfflineProject:
        with self._lock, closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        if row is None:
            raise KeyError(project_id)
        return _project_from_row(row)

    def list_projects(self, *, limit: int = 500) -> tuple[OfflineProject, ...]:
        with self._lock, closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT * FROM projects ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return tuple(_project_from_row(row) for row in rows)

    def update_project(self, project_id: str, **changes: object) -> OfflineProject:
        allowed = {
            "title",
            "source_path",
            "audio_path",
            "source_language",
            "target_language",
            "status",
            "progress",
            "error",
            "duration_ms",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"unsupported project fields: {', '.join(sorted(unknown))}")
        if not changes:
            return self.get_project(project_id)
        values = {
            key: str(value) if key in {"source_path", "audio_path"} and value is not None else value
            for key, value in changes.items()
        }
        values["updated_at"] = _now()
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self._lock, closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                f"UPDATE projects SET {assignments} WHERE id = ?",  # noqa: S608
                (*values.values(), project_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(project_id)
        return self.get_project(project_id)

    def replace_cues(self, project_id: str, cues: list[Cue] | tuple[Cue, ...]) -> None:
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM cues WHERE project_id = ?", (project_id,))
            connection.executemany(
                """
                INSERT INTO cues (
                    project_id, position, start_ms, end_ms, source_text,
                    translated_text, confidence, words_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        project_id,
                        index,
                        cue.start_ms,
                        cue.end_ms,
                        cue.source_text,
                        cue.translated_text,
                        cue.confidence,
                        cue.words_json,
                    )
                    for index, cue in enumerate(cues)
                ],
            )

    def list_cues(self, project_id: str) -> tuple[Cue, ...]:
        with self._lock, closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT * FROM cues WHERE project_id = ? ORDER BY position, id",
                (project_id,),
            ).fetchall()
        return tuple(_cue_from_row(row) for row in rows)

    def update_cue(
        self,
        cue_id: int,
        *,
        start_ms: int,
        end_ms: int,
        source_text: str,
        translated_text: str,
    ) -> None:
        if start_ms < 0 or end_ms <= start_ms:
            raise ValueError("cue end must be after its non-negative start")
        with self._lock, closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                UPDATE cues SET start_ms = ?, end_ms = ?, source_text = ?, translated_text = ?
                WHERE id = ?
                """,
                (start_ms, end_ms, source_text.strip(), translated_text.strip(), cue_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(cue_id)

    def add_interruption(
        self, project_id: str, *, started_at: str, ended_at: str, real_duration_ms: int
    ) -> None:
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO interruptions (project_id, started_at, ended_at, real_duration_ms)
                VALUES (?, ?, ?, ?)
                """,
                (project_id, started_at, ended_at, max(0, real_duration_ms)),
            )

    def _initialize(self) -> None:
        with self._lock, closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    source_path TEXT,
                    audio_path TEXT,
                    source_language TEXT NOT NULL,
                    target_language TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress REAL NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cues (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    start_ms INTEGER NOT NULL,
                    end_ms INTEGER NOT NULL,
                    source_text TEXT NOT NULL,
                    translated_text TEXT NOT NULL,
                    confidence REAL,
                    words_json TEXT NOT NULL DEFAULT '[]'
                );
                CREATE TABLE IF NOT EXISTS interruptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    started_at TEXT NOT NULL,
                    ended_at TEXT NOT NULL,
                    real_duration_ms INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS cues_project_position
                    ON cues(project_id, position);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection


def _project_from_row(row: sqlite3.Row) -> OfflineProject:
    return OfflineProject(
        id=str(row["id"]),
        title=str(row["title"]),
        kind=str(row["kind"]),
        source_path=Path(row["source_path"]) if row["source_path"] else None,
        audio_path=Path(row["audio_path"]) if row["audio_path"] else None,
        source_language=str(row["source_language"]),
        target_language=str(row["target_language"]),
        status=str(row["status"]),
        progress=float(row["progress"]),
        error=str(row["error"]),
        duration_ms=int(row["duration_ms"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _cue_from_row(row: sqlite3.Row) -> Cue:
    return Cue(
        id=int(row["id"]),
        project_id=str(row["project_id"]),
        position=int(row["position"]),
        start_ms=int(row["start_ms"]),
        end_ms=int(row["end_ms"]),
        source_text=str(row["source_text"]),
        translated_text=str(row["translated_text"]),
        confidence=float(row["confidence"]) if row["confidence"] is not None else None,
        words_json=str(row["words_json"]),
    )


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")
