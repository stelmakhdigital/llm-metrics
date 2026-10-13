"""GET/PUT /api/note — файл заметки (вкладка «Note»).

Путь по умолчанию — note.md рядом с БД (в тестах — каталог tmp-БД).
"""

from pathlib import Path


def test_note_default_empty(client):
    r = client.get("/api/note")
    assert r.status_code == 200
    body = r.json()
    assert body["content"] == ""
    assert body["exists"] is False
    assert body["mtime"] is None


def test_note_put_get_roundtrip(client):
    md = "# Памятка\n\n- пункт 1\n- пункт 2\n"
    r = client.put("/api/note", json={"content": md})
    assert r.status_code == 200
    body = r.json()
    assert body["saved"] is True
    assert body["mtime"] is not None

    r = client.get("/api/note")
    body = r.json()
    assert body["content"] == md
    assert body["exists"] is True
    assert body["mtime"] is not None


def test_note_put_overwrites(client):
    # перезапись, а не append: второе сохранение заменяет файл целиком
    client.put("/api/note", json={"content": "первый вариант"})
    client.put("/api/note", json={"content": "второй"})
    body = client.get("/api/note").json()
    assert body["content"] == "второй"


def test_note_default_path_beside_db(client, db_path):
    # путь по умолчанию — note.md рядом с БД (tmp-каталог теста)
    body = client.get("/api/note").json()
    assert Path(body["path"]) == Path(str(db_path)).parent / "note.md"


def test_note_too_long_rejected(client):
    r = client.put("/api/note", json={"content": "x" * (2_000_001)})
    assert r.status_code == 422
