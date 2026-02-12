from app.data.repository import Repository


def test_create_update_and_tags(tmp_path):
    db_path = tmp_path / "notes.db"
    repo = Repository(str(db_path))

    note_id = repo.create_note("Title", "Body")
    note = repo.get_note(note_id)
    assert note["title"] == "Title"

    repo.update_note(note_id, "New", "Text")
    note = repo.get_note(note_id)
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
