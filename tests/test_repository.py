from app.data.repository import Repository


def test_create_update_and_tags(tmp_path):
    db_path = tmp_path / "notes.db"
    repo = Repository(str(db_path))

    note_id = repo.create_note("Title", "Body", False)
    note = repo.get_note(note_id)
    assert note["title"] == "Title"

    repo.update_note(note_id, "New", "Text", True)
    note = repo.get_note(note_id)
    assert note["title"] == "New"
    assert note["is_markdown"] == 1

    repo.set_note_tags(note_id, ["python", "sqlite"])
    tags = repo.get_note_tags(note_id)
    assert {t["name"] for t in tags} == {"python", "sqlite"}

    tag_ids = [t["id"] for t in repo.list_tags() if t["name"] in {"python", "sqlite"}]
    notes = repo.list_notes(tag_ids)
    assert len(notes) == 1

    repo.close()
