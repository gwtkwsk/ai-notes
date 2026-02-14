from app.data.repository import Repository
import json


def test_create_update_and_tags(tmp_path):
    db_path = tmp_path / "notes.db"
    repo = Repository(str(db_path))

    note_id = repo.create_note("Title", "Body")
    note = repo.get_note(note_id)
    assert note is not None
    assert note["title"] == "Title"

    repo.update_note(note_id, "New", "Text")
    note = repo.get_note(note_id)
    assert note is not None
    assert note["title"] == "New"

    repo.set_note_tags(note_id, ["python", "sqlite"])
    tags = repo.get_note_tags(note_id)
    assert {t["name"] for t in tags} == {"python", "sqlite"}

    tag_ids = [t["id"] for t in repo.list_tags() if t["name"] in {"python", "sqlite"}]
    notes = repo.list_notes(tag_ids)
    assert len(notes) == 1
    assert notes[0]["id"] == note_id

    second_note_id = repo.create_note("No labels", "Body 2")
    third_note_id = repo.create_note("One label", "Body 3")
    repo.set_note_tags(third_note_id, ["python"])

    python_id = next(t["id"] for t in repo.list_tags() if t["name"] == "python")
    sqlite_id = next(t["id"] for t in repo.list_tags() if t["name"] == "sqlite")

    and_notes = repo.list_notes([python_id, sqlite_id])
    assert [n["id"] for n in and_notes] == [note_id]

    notes_without_labels = repo.list_notes(without_labels=True)
    assert [n["id"] for n in notes_without_labels] == [second_note_id]

    repo.close()


def test_delete_tag(tmp_path):
    db_path = tmp_path / "notes.db"
    repo = Repository(str(db_path))

    # Create notes with tags
    note1_id = repo.create_note("Note 1", "Content 1")
    repo.set_note_tags(note1_id, ["python", "testing"])

    note2_id = repo.create_note("Note 2", "Content 2")
    repo.set_note_tags(note2_id, ["python"])

    # Get tag IDs
    python_tag = next(t for t in repo.list_tags() if t["name"] == "python")
    testing_tag = next(t for t in repo.list_tags() if t["name"] == "testing")

    python_id = python_tag["id"]
    testing_id = testing_tag["id"]

    # Check usage counts
    assert repo.get_tag_usage_count(python_id) == 2
    assert repo.get_tag_usage_count(testing_id) == 1

    # Delete testing tag
    repo.delete_tag(testing_id)

    # Verify tag is deleted
    remaining_tags = repo.list_tags()
    assert all(t["id"] != testing_id for t in remaining_tags)

    # Verify note1 still has python tag but not testing
    note1_tags = repo.get_note_tags(note1_id)
    assert len(note1_tags) == 1
    assert note1_tags[0]["name"] == "python"

    # Verify python tag usage count updated
    assert repo.get_tag_usage_count(python_id) == 2

    repo.close()


def test_rename_tag(tmp_path):
    db_path = tmp_path / "notes.db"
    repo = Repository(str(db_path))

    # Create note with tag
    note_id = repo.create_note("Note 1", "Content 1")
    repo.set_note_tags(note_id, ["python", "testing"])

    # Get tag
    python_tag = next(t for t in repo.list_tags() if t["name"] == "python")
    python_id = python_tag["id"]

    # Rename tag
    repo.rename_tag(python_id, "Python3")

    # Verify tag was renamed
    tags = repo.list_tags()
    renamed_tag = next(t for t in tags if t["id"] == python_id)
    assert renamed_tag["name"] == "Python3"

    # Verify note still has the tag
    note_tags = repo.get_note_tags(note_id)
    tag_names = {t["name"] for t in note_tags}
    assert "Python3" in tag_names
    assert "python" not in tag_names

    # Test duplicate name rejection
    try:
        repo.rename_tag(python_id, "testing")
        assert False, "Should have raised ValueError for duplicate name"
    except ValueError as e:
        assert "already exists" in str(e)

    # Test empty name rejection
    try:
        repo.rename_tag(python_id, "")
        assert False, "Should have raised ValueError for empty name"
    except ValueError as e:
        assert "cannot be empty" in str(e)

    repo.close()


def test_search_notes_by_embedding(tmp_path):
    db_path = tmp_path / "notes.db"
    repo = Repository(str(db_path))

    note_a = repo.create_note("A", "Alpha")
    note_b = repo.create_note("B", "Beta")

    repo.upsert_note_embedding(note_a, json.dumps([1.0, 0.0, 0.0]))
    repo.upsert_note_embedding(note_b, json.dumps([0.0, 1.0, 0.0]))

    results = repo.search_notes_by_embedding(json.dumps([1.0, 0.0, 0.0]), top_k=1)
    assert len(results) == 1
    assert results[0]["id"] == note_a

    repo.close()
