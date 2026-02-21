import logging
import re
import sqlite3
from collections.abc import Iterable

import sqlite_vec

from app.data.schema import FTS_SQL, SCHEMA_SQL

logger = logging.getLogger(__name__)


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
        self._migrate_embeddings_to_blob()
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()
        self._init_fts()
        # Migration: add is_favourite column for databases created before it existed.
        try:
            self._conn.execute(
                "ALTER TABLE notes ADD COLUMN is_favourite INTEGER NOT NULL DEFAULT 0"
            )
            self._conn.commit()
        except Exception:
            pass  # column already exists

    def _init_fts(self) -> None:
        """Create FTS5 virtual table and sync triggers if they don't exist.

        On first call (table absent), also populates the index from existing notes.
        Safe to call on every startup because all DDL statements use IF NOT EXISTS.
        """
        try:
            self._conn.execute("SELECT * FROM notes_fts LIMIT 0")
            newly_created = False
            logger.debug("FTS5 index already exists")
        except sqlite3.OperationalError:
            newly_created = True
            logger.info("FTS5 table not found — will create and populate")

        self._conn.executescript(FTS_SQL)  # all statements use IF NOT EXISTS
        if newly_created:
            self._conn.execute("INSERT INTO notes_fts(notes_fts) VALUES('rebuild')")
            self._conn.commit()
            logger.info("FTS5 index created and populated")

    def _migrate_embeddings_to_blob(self) -> None:
        """Drop old TEXT-based note_embeddings table so new BLOB schema is created."""
        try:
            self._conn.execute("SELECT vector_json FROM note_embeddings LIMIT 0")
            # Old schema detected — drop it; embeddings will be regenerated.
            logger.info(
                "Migrating embeddings from TEXT to BLOB format (re-index required)"
            )
            self._conn.execute("DROP TABLE note_embeddings")
            self._conn.commit()
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet or already has new schema

    def _load_sqlite_vec(self) -> None:
        try:
            self._conn.enable_load_extension(True)
            sqlite_vec.load(self._conn)
            self._conn.enable_load_extension(False)
            self._conn.execute("SELECT vec_version()")
            logger.info("sqlite-vec loaded successfully")
        except Exception as exc:
            raise RuntimeError(
                "sqlite-vec is required for RAG vector search, but could not "
                "be loaded in SQLite"
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

    def get_note(self, note_id: int) -> dict | None:
        cur = self._conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def list_notes(
        self,
        filter_tag_ids: Iterable[int] | None = None,
        without_labels: bool = False,
    ) -> list[dict]:
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

    def list_notes_for_embedding(self) -> list[dict]:
        cur = self._conn.execute("SELECT id, title, content, is_markdown FROM notes")
        return [dict(row) for row in cur.fetchall()]

    def list_notes_with_embeddings(self) -> list[dict]:
        cur = self._conn.execute(
            """
            SELECT n.id, n.title, n.content, n.is_markdown,
                   COUNT(ne.id) AS embedding_count
            FROM notes n
            LEFT JOIN note_embeddings ne ON ne.note_id = n.id
            GROUP BY n.id
            """
        )
        return [dict(row) for row in cur.fetchall()]

    def search_notes_by_embedding(self, query_vector: bytes, top_k: int) -> list[dict]:
        count_cur = self._conn.execute("SELECT COUNT(*) as cnt FROM note_embeddings")
        count_row = count_cur.fetchone()
        embedding_count = count_row["cnt"] if count_row else 0
        logger.info(
            f"Searching against {embedding_count} stored embedding chunks "
            f"(top_k={top_k})"
        )

        if embedding_count == 0:
            logger.warning(
                "No embeddings found in database. Run 'Re-index Notes' first."
            )
            return []

        cur = self._conn.execute(
            """
            SELECT
                n.id,
                n.title,
                n.content,
                n.is_markdown,
                MIN(vec_distance_cosine(ne.vector, ?)) AS cosine_distance
            FROM notes n
            JOIN note_embeddings ne ON ne.note_id = n.id
            GROUP BY n.id
            ORDER BY cosine_distance ASC
            LIMIT ?
            """,
            (query_vector, top_k),
        )
        results = [dict(row) for row in cur.fetchall()]
        logger.info(f"Database returned {len(results)} results")
        return results

    def list_tags(self) -> list[dict]:
        cur = self._conn.execute("SELECT * FROM tags ORDER BY name COLLATE NOCASE")
        return [dict(row) for row in cur.fetchall()]

    def get_note_tags(self, note_id: int) -> list[dict]:
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

    def replace_note_embeddings(
        self, note_id: int, chunks: list[tuple[str, bytes]]
    ) -> None:
        """Replace all embedding chunks for a note.

        Args:
            note_id: The note ID.
            chunks: List of ``(chunk_text, vector_blob)`` tuples where
                    *vector_blob* is a little-endian float32 binary vector.
        """
        self._conn.execute("DELETE FROM note_embeddings WHERE note_id = ?", (note_id,))
        for idx, (chunk_text, vector_blob) in enumerate(chunks):
            self._conn.execute(
                """
                INSERT INTO note_embeddings(
                    note_id, chunk_index, chunk_text,
                    vector, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (note_id, idx, chunk_text, vector_blob),
            )
        self._conn.commit()
        logger.debug(f"Stored {len(chunks)} embedding chunk(s) for note {note_id}")

    def clear_embeddings(self) -> None:
        logger.info("Clearing all embeddings from database")
        self._conn.execute("DELETE FROM note_embeddings")
        self._conn.commit()

    def search_notes_by_bm25(self, query: str, top_k: int) -> list[dict]:
        """Full-text BM25 search using SQLite FTS5.

        Args:
            query: User query string. Special FTS5 characters are sanitized.
            top_k: Maximum number of results to return.

        Returns:
            List of note dicts with id, title, content, is_markdown fields,
            ordered by BM25 relevance (most relevant first).
        """
        if not query.strip():
            return []
        safe_query = self._sanitize_fts_query(query)
        if not safe_query:
            return []
        try:
            cur = self._conn.execute(
                """
                SELECT
                    n.id,
                    n.title,
                    n.content,
                    n.is_markdown
                FROM notes_fts
                JOIN notes n ON n.id = notes_fts.rowid
                WHERE notes_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (safe_query, top_k),
            )
            results = [dict(row) for row in cur.fetchall()]
            logger.info(
                f"BM25 search returned {len(results)} results for query: '{query[:50]}'"
            )
            return results
        except sqlite3.OperationalError as exc:
            logger.warning(f"BM25 search failed (FTS5 error): {exc}")
            return []

    @staticmethod
    def _sanitize_fts_query(query: str) -> str:
        """Sanitize a user query string for use as an FTS5 MATCH term.

        Wraps each word in double-quotes to prevent FTS5 operator injection.
        Empty or whitespace-only input returns an empty string.

        Args:
            query: Raw user query.

        Returns:
            FTS5-safe query string or empty string if no valid tokens.
        """
        cleaned = re.sub(r'["\^*()\[\]]', " ", query)
        words = [w for w in cleaned.split() if w]
        if not words:
            return ""
        return " ".join(f'"{w}"' for w in words)
