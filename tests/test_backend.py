from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
import mcp_knowledge


@pytest.fixture()
def knowledge_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "solutions"
    root.mkdir()
    monkeypatch.setattr(main, "SOLUTIONS_DIR", str(root))
    monkeypatch.setattr(mcp_knowledge, "SOLUTIONS_DIR", str(root))
    return root


def test_knowledge_scan_uses_nested_relative_paths(knowledge_dir: Path):
    nested = knowledge_dir / "math"
    nested.mkdir()
    (nested / "answer.md").write_text("binary search", encoding="utf-8")

    result = mcp_knowledge.list_knowledge()

    assert result[0]["path"] == "math/answer.md"


def test_knowledge_rejects_invalid_search_limit(knowledge_dir: Path):
    with pytest.raises(ValueError):
        mcp_knowledge.search_knowledge("answer", limit=0)


def test_knowledge_rejects_symlink(knowledge_dir: Path, tmp_path: Path):
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    link = knowledge_dir / "link.md"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境不支持创建符号链接")

    assert mcp_knowledge.list_knowledge() == []
    assert mcp_knowledge.read_knowledge("link.md") == {"error": "文件不存在"}


def test_solution_delete_rejects_empty_path():
    client = TestClient(main.app)
    response = client.post("/api/solutions/delete", json={})

    assert response.status_code == 422


def test_knowledge_api_requires_token():
    client = TestClient(main.app)
    response = client.get("/api/knowledge/list")

    assert response.status_code == 401


def test_mcp_exposes_only_knowledge_tools():
    tool_names = {tool.name for tool in main.mcp_server.tools}

    assert tool_names == {
        "list_articles",
        "read_article",
        "search_articles",
    }


def test_mcp_operation_ids_are_stable():
    operations = {
        operation["operationId"]
        for item in main.app.openapi()["paths"].values()
        for operation in item.values()
        if "operationId" in operation
    }

    assert {"list_articles", "read_article", "search_articles"} <= operations
