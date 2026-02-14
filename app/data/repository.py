import sqlite3
from typing import Iterable, List, Optional

import sqlite_vec

from app.data.schema import SCHEMA_SQL


class Repository:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._load_sqlite_vec()
        self._init_schema()

    @property
    def db_path(self) -> str:
        return self._db_path

    def close(self) -> None:
        self._conn.close()

    def _init_schema(self) -> None:
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()
        # Migration: add is_favourite column for databases created before it existed.
        try:
            self._conn.execute(
                "ALTER TABLE notes ADD COLUMN is_favourite INTEGER NOT NULL DEFAULT 0"
            )
            self._conn.commit()
        except Exception:
            pass  # column already exists

    def _load_sqlite_vec(self) -> None:
        try:
            self._conn.enable_load_extension(True)
            sqlite_vec.load(self._conn)
            self._conn.enable_load_extension(False)
            self._conn.execute("SELECT vec_version()")
        except Exception as exc:
            raise RuntimeError(
                "sqlite-vec is required for RAG vector search, but could not be loaded in SQLite"
            ) from exc

    def create_note(self, title: str, content: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO notes(title, content, is_markdown) VALUES (?, ?, ?)",
            (title, content, 1),
        )
        self._conn.commit()
        assert cur.lastrowid is not None
        return int(cur.lastrowid)

    def update_note(self, note_id: int, title: str, content: str) -> None:
        self._conn.execute(
            """
            UPDATE notes
            SET title = ?, content = ?, is_markdown = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (title, content, 1, note_id),
        )
        self._conn.commit()

    def delete_note(self, note_id: int) -> None:
        self._conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        self._conn.commit()

    def get_note(self, note_id: int) -> Optional[dict]:
        cur = self._conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def list_notes(
        self,
        filter_tag_ids: Optional[Iterable[int]] = None,
        without_labels: bool = False,
    ) -> List[dict]:
        ids = list(filter_tag_ids) if filter_tag_ids else []

        if without_labels:
            cur = self._conn.execute(
                """
                SELECT n.*
                FROM notes n
                LEFT JOIN note_tags nt ON nt.note_id = n.id
                WHERE nt.note_id IS NULL
                ORDER BY n.updated_at DESC
                """
            )
        elif ids:
            placeholders = ",".join(["?"] * len(ids))
            query = f"""
                SELECT n.*
                FROM notes n
                JOIN note_tags nt ON nt.note_id = n.id
                WHERE nt.tag_id IN ({placeholders})
                GROUP BY n.id
                HAVING COUNT(DISTINCT nt.tag_id) = ?
                ORDER BY n.updated_at DESC
            """
            cur = self._conn.execute(query, (*ids, len(ids)))
        else:
            cur = self._conn.execute("SELECT * FROM notes ORDER BY updated_at DESC")
        return [dict(row) for row in cur.fetchall()]

    def list_notes_for_embedding(self) -> List[dict]:
        cur = self._conn.execute("SELECT id, title, content, is_markdown FROM notes")
        return [dict(row) for row in cur.fetchall()]

    def list_notes_with_embeddings(self) -> List[dict]:
        cur = self._conn.execute(
            """
            SELECT n.id, n.title, n.content, n.is_markdown, ne.vector_json
            FROM notes n
            LEFT JOIN note_embeddings ne ON ne.note_id = n.id
            """
        )
        return [dict(row) for row in cur.fetchall()]

    def search_notes_by_embedding(
        self, query_vector_json: str, top_k: int
    ) -> List[dict]:
        cur = self._conn.execute(
            """
            SELECT
                n.id,
                n.title,
                n.content,
                n.is_markdown,
                vec_distance_cosine(ne.vector_json, ?) AS cosine_distance
            FROM notes n
            JOIN note_embeddings ne ON ne.note_id = n.id
            ORDER BY cosine_distance ASC
            LIMIT ?
            """,
            (query_vector_json, top_k),
        )
        return [dict(row) for row in cur.fetchall()]

    def list_tags(self) -> List[dict]:
        cur = self._conn.execute("SELECT * FROM tags ORDER BY name COLLATE NOCASE")
        return [dict(row) for row in cur.fetchall()]

    def get_note_tags(self, note_id: int) -> List[dict]:
        cur = self._conn.execute(
            """
            SELECT t.*
            FROM tags t
            JOIN note_tags nt ON nt.tag_id = t.id
            WHERE nt.note_id = ?
            ORDER BY t.name COLLATE NOCASE
            """,
            (note_id,),
        )
        return [dict(row) for row in cur.fetchall()]

    def ensure_tag(self, name: str) -> int:
        name = name.strip()
        if not name:
            raise ValueError("Tag name is empty")
        cur = self._conn.execute("SELECT id FROM tags WHERE name = ?", (name,))
        row = cur.fetchone()
        if row:
            return int(row["id"])
        cur = self._conn.execute("INSERT INTO tags(name) VALUES (?)", (name,))
        self._conn.commit()
        assert cur.lastrowid is not None
        return int(cur.lastrowid)

    def set_note_tags(self, note_id: int, tag_names: Iterable[str]) -> None:
        tag_ids = []
        for name in tag_names:
            tag_id = self.ensure_tag(name)
            tag_ids.append(tag_id)

        self._conn.execute("DELETE FROM note_tags WHERE note_id = ?", (note_id,))
        self._conn.executemany(
            "INSERT OR IGNORE INTO note_tags(note_id, tag_id) VALUES (?, ?)",
            [(note_id, tag_id) for tag_id in tag_ids],
        )
        self._conn.commit()

    def toggle_favourite(self, note_id: int) -> bool:
        """Toggle the is_favourite flag. Returns the new value."""
        cur = self._conn.execute(
            "SELECT is_favourite FROM notes WHERE id = ?", (note_id,)
        )
        row = cur.fetchone()
        if row is None:
            return False
        new_val = 0 if row["is_favourite"] else 1
        self._conn.execute(
            "UPDATE notes SET is_favourite = ? WHERE id = ?", (new_val, note_id)
        )
        self._conn.commit()
        return bool(new_val)

    def delete_tag(self, tag_id: int) -> None:
        """Delete a tag. CASCADE will automatically remove note_tags entries."""
        self._conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
        self._conn.commit()

    def rename_tag(self, tag_id: int, new_name: str) -> None:
        """Rename a tag."""
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("Tag name cannot be empty")

        # Check if name already exists (case-insensitive)
        cur = self._conn.execute(
            "SELECT id FROM tags WHERE LOWER(name) = LOWER(?) AND id != ?",
            (new_name, tag_id),
        )
        if cur.fetchone():
            raise ValueError(f"Tag '{new_name}' already exists")

        self._conn.execute("UPDATE tags SET name = ? WHERE id = ?", (new_name, tag_id))
        self._conn.commit()

    def get_tag_usage_count(self, tag_id: int) -> int:
        """Return the number of notes using this tag."""
        cur = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM note_tags WHERE tag_id = ?", (tag_id,)
        )
        row = cur.fetchone()
        return int(row["cnt"]) if row else 0

    def upsert_note_embedding(self, note_id: int, vector_json: str) -> None:
        self._conn.execute(
            """
            INSERT INTO note_embeddings(note_id, vector_json, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(note_id) DO UPDATE SET
                vector_json = excluded.vector_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (note_id, vector_json),
        )
        self._conn.commit()

    def clear_embeddings(self) -> None:
        self._conn.execute("DELETE FROM note_embeddings")
        self._conn.commit()
