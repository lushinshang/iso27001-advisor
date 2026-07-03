import json

import pytest

from scripts.build_embeddings import build_clause_embeddings, load_embedding_index


def _write_structure(path):
    items = [
        {
            "id": "clause_5",
            "type": "clause",
            "subsection": "5 領導",
            "title": "領導",
            "content": "父章節不應建立向量。",
        },
        {
            "id": "clause_5.1",
            "type": "clause",
            "subsection": "5.1 領導及承諾",
            "title": "領導及承諾",
            "content": "最高管理階層應展現領導及承諾。",
        },
        {
            "id": "control_8.13",
            "type": "control",
            "subsection": "8.13 資訊備份",
            "title": "資訊備份",
            "content": "資訊、軟體及系統之備份複本應予維護。",
        },
    ]
    path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")


def test_build_clause_embeddings_writes_expected_schema(tmp_path):
    structure_path = tmp_path / "iso27001_structure.json"
    output_path = tmp_path / "clause_embeddings.json"
    _write_structure(structure_path)

    def fake_embed(text, model, host):
        assert "Instruct:" not in text
        return [float(len(text)), 1.0, 0.5]

    index = build_clause_embeddings(
        structure_path=structure_path,
        output_path=output_path,
        embedding_func=fake_embed,
    )

    assert output_path.exists()
    assert index["embed_model"] == "jeffh/intfloat-multilingual-e5-large-instruct:f16"
    assert index["source_file"] == str(structure_path)
    assert index["dimension"] == 3
    assert [item["id"] for item in index["items"]] == ["clause_5.1", "control_8.13"]


def test_build_clause_embeddings_rejects_inconsistent_dimensions(tmp_path):
    structure_path = tmp_path / "iso27001_structure.json"
    output_path = tmp_path / "clause_embeddings.json"
    _write_structure(structure_path)
    calls = {"count": 0}

    def inconsistent_embed(text, model, host):
        calls["count"] += 1
        return [1.0, 2.0] if calls["count"] == 1 else [1.0]

    with pytest.raises(ValueError, match="向量維度不一致"):
        build_clause_embeddings(
            structure_path=structure_path,
            output_path=output_path,
            embedding_func=inconsistent_embed,
        )


def test_load_embedding_index_reports_missing_file(tmp_path):
    missing_path = tmp_path / "missing_embeddings.json"

    with pytest.raises(FileNotFoundError, match="找不到向量索引"):
        load_embedding_index(missing_path)
