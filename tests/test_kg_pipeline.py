import json

import pytest

from scripts.build_knowledge_graph import parse_llm_json_response, run_kg_pipeline


def test_parse_llm_json_response_accepts_fenced_json():
    raw = '```json\n{"related": []}\n```'

    assert parse_llm_json_response(raw) == {"related": []}


def test_parse_llm_json_response_accepts_prefixed_json():
    raw = '以下是結果：\n{"related": [{"id": "control_8.13"}]}\n請參考。'

    assert parse_llm_json_response(raw) == {"related": [{"id": "control_8.13"}]}


def test_parse_llm_json_response_rejects_plain_prose():
    with pytest.raises(ValueError, match="JSON"):
        parse_llm_json_response("我認為這些條文很相關，但沒有 JSON。")


def test_run_kg_pipeline_sample_keeps_full_candidate_pool(tmp_path):
    structure_path, embeddings_path = _write_inputs(tmp_path)
    output_path = tmp_path / "knowledge_graph.json"
    seen_candidate_counts = []

    def fake_nominator(item, all_items, model, round_index):
        seen_candidate_counts.append(len(all_items))
        return {"related": []}

    run_kg_pipeline(
        structure_path=structure_path,
        embeddings_path=embeddings_path,
        output_path=output_path,
        models=["mock-model"],
        rounds=1,
        sample=1,
        nominator_func=fake_nominator,
    )

    assert seen_candidate_counts == [15]


def _write_inputs(tmp_path):
    structure = [
        {
            "id": "control_8.13",
            "title": "資訊備份",
            "content": "資訊、軟體及系統之備份複本應予維護。",
        },
        {
            "id": "control_8.14",
            "title": "資訊處理設施之備援",
            "content": "資訊處理設施應以足夠備援實作。",
        },
        {
            "id": "control_5.7",
            "title": "威脅情資",
            "content": "威脅情資應予蒐集及分析。",
        },
        {
            "id": "control_5.23",
            "title": "雲端服務",
            "content": "雲端服務使用應建立程序。",
        },
    ]
    for i in range(1, 18):
        structure.append(
            {
                "id": f"control_9.{i}",
                "title": f"候選測試 {i}",
                "content": f"候選測試內容 {i} 應予維護。",
            }
        )
    embeddings = {
        "embed_model": "fake",
        "dimension": 2,
        "items": [
            {"id": "control_8.13", "embedding": [1.0, 0.0]},
            {"id": "control_8.14", "embedding": [1.0, 0.0]},
            {"id": "control_5.7", "embedding": [0.0, 1.0]},
            {"id": "control_5.23", "embedding": [1.0, 0.0]},
            *[
                {
                    "id": f"control_9.{i}",
                    "embedding": [1.0, 0.0] if i <= 12 else [-1.0, 0.0],
                }
                for i in range(1, 18)
            ],
        ],
    }
    structure_path = tmp_path / "iso27001_structure.json"
    embeddings_path = tmp_path / "clause_embeddings.json"
    structure_path.write_text(json.dumps(structure, ensure_ascii=False), encoding="utf-8")
    embeddings_path.write_text(json.dumps(embeddings, ensure_ascii=False), encoding="utf-8")
    return structure_path, embeddings_path


def test_run_kg_pipeline_applies_all_gates_and_writes_report(tmp_path):
    structure_path, embeddings_path = _write_inputs(tmp_path)
    output_path = tmp_path / "knowledge_graph.json"
    seen_candidates = {}

    def fake_nominator(item, all_items, model, round_index):
        candidate_ids = [candidate["id"] for candidate in all_items]
        seen_candidates[item["id"]] = candidate_ids
        assert item["id"] not in candidate_ids
        assert len(candidate_ids) <= 15
        related_by_id = {
            "control_8.13": [
                {
                    "id": "control_8.14",
                    "evidence_self": "備份複本應予維護",
                    "evidence_other": "資訊處理設施",
                },
                {
                    "id": "control_9.17",
                    "evidence_self": "備份複本應予維護",
                    "evidence_other": "候選測試內容 17",
                },
                {
                    "id": "control_5.7",
                    "evidence_self": "不存在的引句內容",
                    "evidence_other": "威脅情資應予蒐集",
                },
            ],
            "control_8.14": [
                {
                    "id": "control_8.13",
                    "evidence_self": "資訊處理設施",
                    "evidence_other": "備份複本應予維護",
                },
                {
                    "id": "control_5.7",
                    "evidence_self": "資訊處理設施",
                    "evidence_other": "威脅情資應予蒐集",
                },
                {
                    "id": "control_5.23",
                    "evidence_self": "資訊處理設施",
                    "evidence_other": "雲端服務使用應建立",
                },
            ],
        }
        return {"related": related_by_id.get(item["id"], [])}

    graph = run_kg_pipeline(
        structure_path=structure_path,
        embeddings_path=embeddings_path,
        output_path=output_path,
        models=["mock-model"],
        rounds=1,
        nominator_func=fake_nominator,
    )

    assert output_path.exists()
    assert "control_9.17" not in seen_candidates["control_8.13"]
    assert graph["gate_report"] == {
        "nominated": 5,
        "g1_rejected": 0,
        "g2_rejected": 1,
        "g3_rejected": 1,
        "g4_rejected": 1,
        "survived": 1,
    }
    assert graph["format_failures"] == {"mock-model": 1}
    assert graph["edges"] == [
        {
            "from": "control_8.13",
            "to": "control_8.14",
            "evidence_from": "備份複本應予維護",
            "evidence_to": "資訊處理設施",
            "similarity": 1.0,
            "nominated_by": ["mock-model"],
            "bidirectional": True,
        }
    ]


def test_run_kg_pipeline_from_pdca(tmp_path):
    # 建立 mock structure
    structure = [
        {"id": "control_8.13", "title": "資訊備份", "content": "備份內容"},
        {"id": "control_8.14", "title": "備援", "content": "備援內容"},
        {"id": "control_5.7", "title": "威脅情資", "content": "情資內容"},
        {"id": "control_5.23", "title": "雲端服務", "content": "雲端內容"},
    ]
    # 為 degree cap 測試加入額外節點 (讓 control_8.13 與 7 個節點關聯)
    for i in range(1, 8):
        structure.append(
            {"id": f"control_9.{i}", "title": f"測試 {i}", "content": f"內容 {i}"}
        )

    # 建立 mock embeddings
    embeddings = {
        "embed_model": "fake",
        "dimension": 2,
        "items": [
            {"id": "control_8.13", "embedding": [1.0, 0.0]},
            {"id": "control_8.14", "embedding": [1.0, 0.0]},
            {"id": "control_5.7", "embedding": [0.0, 1.0]},
            {"id": "control_5.23", "embedding": [1.0, 0.0]},
            *[
                {"id": f"control_9.{i}", "embedding": [1.0, 0.0] if i <= 5 else [0.0, 1.0]}
                for i in range(1, 8)
            ]
        ]
    }

    # 建立 mock pdca_graph
    pdca_graph = {
        "_meta": {"version": "test"},
        # 1. 正常雙向關聯 (A->B 且 B->A)，展開去重後應為 1 條邊
        "control_8.13": {
            "cluster": "test",
            "related": ["control_8.14", "control_5.7"],
            "next": ["control_5.23"]  # next 應被忽略
        },
        "control_8.14": {
            "cluster": "test",
            "related": ["control_8.13"]
        },
        # 2. 自環 (應被 G1 刷掉)
        "control_5.7": {
            "cluster": "test",
            "related": ["control_5.7", "invalid_id_xyz"] # invalid_id_xyz 不存在於 structure (應被 G1 刷掉)
        },
        # 3. 測試 degree cap. control_8.13 與 control_9.1 到 control_9.7 關聯
        # 這樣 control_8.13 的 degree 有 2 (上面 8.14, 5.7) + 7 = 9 條邊
        # 經過 degree cap=6 後，應該只剩下 6 條邊，保留 similarity 較高者
        "control_9.1": {"cluster": "test", "related": ["control_8.13"]},
        "control_9.2": {"cluster": "test", "related": ["control_8.13"]},
        "control_9.3": {"cluster": "test", "related": ["control_8.13"]},
        "control_9.4": {"cluster": "test", "related": ["control_8.13"]},
        "control_9.5": {"cluster": "test", "related": ["control_8.13"]},
        "control_9.6": {"cluster": "test", "related": ["control_8.13"]},
        "control_9.7": {"cluster": "test", "related": ["control_8.13"]},
    }

    structure_path = tmp_path / "iso27001_structure.json"
    embeddings_path = tmp_path / "clause_embeddings.json"
    pdca_path = tmp_path / "pdca_graph.json"
    output_path = tmp_path / "knowledge_graph.json"

    structure_path.write_text(json.dumps(structure, ensure_ascii=False), encoding="utf-8")
    embeddings_path.write_text(json.dumps(embeddings, ensure_ascii=False), encoding="utf-8")
    pdca_path.write_text(json.dumps(pdca_graph, ensure_ascii=False), encoding="utf-8")

    from scripts.build_knowledge_graph import run_kg_pipeline

    graph = run_kg_pipeline(
        structure_path=structure_path,
        embeddings_path=embeddings_path,
        output_path=output_path,
        from_pdca=True,
        pdca_path=pdca_path,
    )

    assert output_path.exists()
    
    # 驗證 edges 中的屬性
    for edge in graph["edges"]:
        assert edge["source"] == "pdca_graph"
        assert edge["evidence_from"] == ""
        assert edge["evidence_to"] == ""
        assert edge["nominated_by"] == ["pdca_graph"]
        assert edge["bidirectional"] is True
        assert "similarity" in edge

    # 驗證 degree cap 作用後，control_8.13 的度數不超過 6
    degrees = {}
    for edge in graph["edges"]:
        f, t = edge["from"], edge["to"]
        degrees[f] = degrees.get(f, 0) + 1
        degrees[t] = degrees.get(t, 0) + 1

    assert degrees.get("control_8.13", 0) <= 6
    assert graph["gate_report"]["g2_rejected"] == 0
    assert graph["gate_report"]["g3_rejected"] == 0
    assert graph["gate_report"]["g4_rejected"] == 0
    assert graph["gate_report"]["survived"] == len(graph["edges"])
    assert "similarity_distribution" in graph

