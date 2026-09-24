import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture()
def isolated_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "solutions"
    root.mkdir()
    records = tmp_path / "records.json"
    records.write_text(json.dumps([
        {"time": 1700000000, "status": False, "pid": "P1001", "rid": "r1"},
        {"time": 1700000100, "status": True, "pid": "P1001", "rid": "r2"},
        {"time": 1700000200, "status": True, "pid": "Qoj1001", "rid": "r3"},
    ]), encoding="utf-8")
    monkeypatch.setattr(main, "SOLUTIONS_DIR", str(root))
    monkeypatch.setattr(main, "DATA_FILE", str(records))
    monkeypatch.setattr(main, "META_FILE", str(tmp_path / "meta.json"))
    monkeypatch.setattr(main, "records_cache", [])
    monkeypatch.setattr(main, "pass_count", 0)
    for name in ("day_count_cache", "day_sum_cache", "month_count_cache", "month_sum_cache"):
        monkeypatch.setattr(main, name, getattr(main, name).copy())
    # 账本路径也要隔离，避免测试读写开发者的真实 OI 账本。
    monkeypatch.setattr(main, "LEDGER_FACTS_FILE", str(tmp_path / "facts.json"))
    monkeypatch.setattr(main, "LEDGER_LINKS_FILE", str(tmp_path / "ledger-links.json"))
    return root


@pytest.fixture()
def client(isolated_data):
    # Lifespan and MCP transport are exercised; all disk writes use temporary data.
    with TestClient(main.app) as client:
        yield client


class MCPSession:
    def __init__(self, client: TestClient, path: str = "/mcp",
                 server_name: str = "MMPFP Solutions"):
        self.client = client
        self.path = path
        self.request_id = 0
        self.headers = {"Accept": "application/json, text/event-stream"}
        response = self.request("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "mmpfp-tests", "version": "1.0"},
        })
        assert response.json()["result"]["serverInfo"]["name"] == server_name
        self.headers["Mcp-Session-Id"] = response.headers["Mcp-Session-Id"]
        self.headers["MCP-Protocol-Version"] = response.json()["result"]["protocolVersion"]
        response = client.post(self.path, headers=self.headers, json={
            "jsonrpc": "2.0", "method": "notifications/initialized",
        })
        assert response.status_code == 202

    def request(self, method, params):
        self.request_id += 1
        response = self.client.post(self.path, headers=self.headers, json={
            "jsonrpc": "2.0", "id": self.request_id, "method": method, "params": params,
        })
        assert response.status_code == 200, response.text
        return response

    def call(self, name, arguments=None, *, error=False):
        result = self.request("tools/call", {
            "name": name, "arguments": arguments or {},
        }).json()["result"]
        assert result.get("isError", False) is error, result
        if error:
            return result
        return json.loads(result["content"][0]["text"])

    def tools(self):
        return self.request("tools/list", {}).json()["result"]["tools"]


@pytest.fixture()
def session(client):
    session = MCPSession(client)
    yield session
    assert client.delete("/mcp", headers=session.headers).status_code == 200


@pytest.fixture()
def reports(isolated_data, monkeypatch):
    """Use controlled creation times on both Windows and Unix."""
    created = {}
    original_getctime = os.path.getctime

    def create(relative, timestamp, content="# 解题报告\n\n思路与证明。\n"):
        target = isolated_data / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        os.utime(target, (timestamp, timestamp))
        created[str(target.resolve())] = timestamp
        return target

    def getctime(filename):
        key = str(Path(filename).resolve())
        return created[key] if key in created else original_getctime(filename)

    monkeypatch.setattr(os.path, "getctime", getctime)
    return create


def test_mcp_publishes_queries_and_ledger_with_per_tool_annotations(session, client):
    """决策 1 (a)：同一个 /mcp 同时提供只读查询与账本读写，靠 annotation 区分。"""
    tools = session.tools()
    by_name = {tool["name"]: tool["annotations"] for tool in tools}
    assert set(by_name) == SOLUTION_TOOLS | LEDGER_TOOLS

    for name in SOLUTION_TOOLS | LEDGER_READ_TOOLS:
        assert by_name[name]["readOnlyHint"] is True, name
        assert by_name[name]["destructiveHint"] is False, name

    for name in LEDGER_WRITE_TOOLS:
        assert by_name[name]["readOnlyHint"] is False, name
    assert by_name["ledger_unlink"]["destructiveHint"] is True
    assert by_name["ledger_add_fact"]["destructiveHint"] is False
    assert all(not a["openWorldHint"] for a in by_name.values())

    # 内部查询/账本路由没有被发布到主应用上。
    for path in ("/reports", "/report", "/submissions", "/submissions/by-time",
                 "/ledger/search", "/ledger/profile", "/ledger/facts", "/ledger/links"):
        assert client.get(path).status_code == 404
        assert client.post(path, json={}).status_code == 404
    assert "/mcp" not in client.get("/openapi.json").json()["paths"]
    assert "/mcp-ledger" not in client.get("/openapi.json").json()["paths"]


def test_default_lists_latest_ten_recursively_before_now(session, reports):
    now = time.time()
    for i in range(12):
        reports(f"contest/round/{i:02}.md", now - 100 + i)
    reports("future.md", now + 3600)
    reports("ignored.txt", now - 1)
    assert session.call("list_solution_reports") == [
        f"contest/round/{i:02}.md" for i in range(11, 1, -1)
    ]


def test_time_window_includes_boundaries_and_handles_timezones(session, reports):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()
    reports("before.md", start - 1)
    reports("start.md", start)
    reports("a.md", start + 3600)
    reports("b.md", start + 3600)
    reports("end.md", start + 7200)
    reports("after.md", start + 7201)
    args = {"start_time": "2026-01-01T08:00:00+08:00", "end_time": "2026-01-01T02:00:00Z"}
    assert session.call("list_solution_reports", args) == ["end.md", "a.md", "b.md", "start.md"]
    assert session.call("list_solution_reports", {**args, "order": "asc", "limit": 2}) == [
        "start.md", "a.md",
    ]


def test_modified_time_can_be_selected(session, reports):
    now = time.time()
    old = reports("old.md", now - 100)
    reports("new.md", now - 50)
    os.utime(old, (now - 1, now - 1))
    assert session.call("list_solution_reports") == ["new.md", "old.md"]
    assert session.call("list_solution_reports", {"time_field": "modified"}) == ["old.md", "new.md"]


def test_explicit_null_time_bounds_use_defaults(session, reports):
    reports("report.md", time.time() - 1)
    assert session.call("list_solution_reports", {"start_time": None, "end_time": None}) == ["report.md"]


@pytest.mark.parametrize("args", [
    {"limit": 0}, {"limit": 1001}, {"limit": "ten"}, {"order": "wrong"},
    {"time_field": "wrong"}, {"start_time": "not-a-date"},
    {"start_time": "2026-02-01T00:00:00Z", "end_time": "2026-01-01T00:00:00Z"},
])
def test_invalid_report_query_returns_mcp_error(session, args):
    session.call("list_solution_reports", args, error=True)


def test_empty_queries_and_missing_reports(session):
    assert session.call("list_solution_reports") == []
    assert session.call("get_problem_submissions", {"pid": "unknown"}) == []
    session.call("get_solution_report", {"relative_path": "missing.md"}, error=True)


def test_read_report_preserves_content_and_accepts_relative_paths(session, reports):
    content = "# 题解\n\n中文、公式 $x^2$\n\n```cpp\nint main() {}\n```\n"
    reports("数学/题目.md", time.time() - 1, content)
    for relative in ("数学/题目.md", "数学/题目", "数学\\题目.md"):
        assert session.call("get_solution_report", {"relative_path": relative}) == {"content": content}


@pytest.mark.parametrize("relative", [
    "../outside.md", "..\\outside.md", "/outside.md", "C:/outside.md", "C:outside.md",
    "//server/share/outside.md", "report.md:secret", "a/../../outside.md", "bad\x00.md", "",
])
def test_unsafe_paths_return_mcp_error(session, relative):
    session.call("get_solution_report", {"relative_path": relative}, error=True)


def test_symlinks_are_not_listed_or_read(session, isolated_data, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("private", encoding="utf-8")
    link = isolated_data / "linked.md"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Creating symlinks is not permitted on this system")
    assert session.call("list_solution_reports") == []
    session.call("get_solution_report", {"relative_path": "linked.md"}, error=True)


def test_all_problem_submissions_and_live_updates(session, client):
    assert [record["rid"] for record in session.call("get_problem_submissions", {"pid": "P1001"})] == [
        "r2", "r1",
    ]
    latest = {"time": 1700000300, "status": False, "pid": "P1001", "rid": "r4"}
    assert client.post("/api/push_record", json=[latest]).status_code == 200
    records = session.call("get_problem_submissions", {"pid": "P1001"})
    assert [record["rid"] for record in records] == ["r4", "r2", "r1"]
    assert records[0] == latest
    assert session.call("get_problem_submissions", {"pid": "1001"}) == []


def test_default_submission_window_returns_latest_ten_and_live_updates(session, client):
    now = int(time.time())
    records = [
        {"time": now - 100 + i, "status": bool(i % 2), "pid": f"P{i}", "rid": f"new-{i:02}"}
        for i in range(12)
    ]
    future = {"time": now + 3600, "status": True, "pid": "Qoj1", "rid": "future"}
    assert client.post("/api/push_record", json=[*records, future]).status_code == 200
    before_query = [record.copy() for record in main.records_cache]
    assert session.call("get_submissions_by_time") == list(reversed(records[2:]))
    assert main.records_cache == before_query


def test_submission_window_boundaries_timezones_order_and_pagination(session, client):
    tied = {"time": 1700000100, "status": False, "pid": "Cf123A", "rid": "r2b"}
    after = {"time": 1700000201, "status": True, "pid": "P1001", "rid": "after"}
    assert client.post("/api/push_record", json=[tied, after]).status_code == 200
    args = {
        "start_time": datetime.fromtimestamp(1700000100, timezone(timedelta(hours=8))).isoformat(),
        "end_time": datetime.fromtimestamp(1700000200, timezone.utc).isoformat(),
    }
    result = session.call("get_submissions_by_time", args)
    assert [record["rid"] for record in result] == ["r3", "r2", "r2b"]
    assert result[-1] == tied
    assert [record["rid"] for record in session.call("get_submissions_by_time", {**args, "order": "asc"})] == [
        "r2", "r2b", "r3",
    ]
    assert session.call("get_submissions_by_time", {**args, "order": "asc", "limit": 1, "offset": 1}) == [tied]
    assert session.call("get_submissions_by_time", {**args, "offset": 3}) == []
    assert session.call("get_submissions_by_time", {
        "start_time": "2020-01-01T00:00:00Z", "end_time": "2020-01-02T00:00:00Z",
    }) == []


def test_submission_window_optional_bounds_and_local_time(session):
    assert [record["rid"] for record in session.call("get_submissions_by_time", {
        "start_time": None, "end_time": None,
    })] == ["r3", "r2", "r1"]
    local_boundary = datetime.fromtimestamp(1700000100).isoformat()
    assert [record["rid"] for record in session.call("get_submissions_by_time", {
        "start_time": local_boundary,
    })] == ["r3", "r2"]
    assert [record["rid"] for record in session.call("get_submissions_by_time", {
        "end_time": local_boundary,
    })] == ["r2", "r1"]
    assert [record["rid"] for record in session.call("get_submissions_by_time", {
        "start_time": local_boundary, "end_time": local_boundary,
    })] == ["r2"]


@pytest.mark.parametrize("args", [
    {"limit": 0}, {"limit": 1001}, {"limit": "ten"}, {"order": "wrong"},
    {"offset": -1}, {"offset": 1.5}, {"start_time": "not-a-date"},
    {"start_time": "2026-02-01T00:00:00Z", "end_time": "2026-01-01T00:00:00Z"},
])
def test_invalid_submission_window_returns_mcp_error(session, args):
    session.call("get_submissions_by_time", args, error=True)


def test_original_web_crud_and_statistics_still_work_with_mcp(session, client, isolated_data):
    assert client.get("/").status_code == 200
    assert client.get("/solution-journal").status_code == 200
    assert client.get("/api/basic").json() == {"pass_count": 2}
    assert client.post("/api/solutions/new", json={"path": "folder/demo", "content": "first"}).status_code == 200
    assert client.post("/api/solutions/save", json={"path": "folder/demo", "content": "updated"}).status_code == 200
    assert client.post("/api/solutions/append", json={"path": "folder/demo", "content": "\nlast"}).status_code == 200
    assert client.get("/api/solutions/read", params={"file_path": "folder/demo"}).json() == {"content": "updated\nlast"}
    assert session.call("get_solution_report", {"relative_path": "folder/demo.md"}) == {"content": "updated\nlast"}
    assert session.call("list_solution_reports") == ["folder/demo.md"]
    assert client.get("/api/solutions/list").json()[0]["children"][0]["name"] == "demo.md"
    delete_tool = main.app.openapi()["paths"]["/api/solutions/delete"]["post"]["operationId"]
    session.call(delete_tool, {"path": "folder/demo.md"}, error=True)
    assert (isolated_data / "folder/demo.md").read_text(encoding="utf-8") == "updated\nlast"
    assert client.post("/api/solutions/delete", json={"path": "folder/demo.md"}).status_code == 200
    assert session.call("list_solution_reports") == []


# --------------------------------------------------------------------------- #
# 能力证据库：同一个 /mcp 上的读写工具
# --------------------------------------------------------------------------- #

SOLUTION_TOOLS = {
    "list_solution_reports", "get_solution_report", "get_problem_submissions",
    "get_submissions_by_time",
}
LEDGER_READ_TOOLS = {"ledger_search", "ledger_get_fact"}
LEDGER_WRITE_TOOLS = {"ledger_add_fact", "ledger_link", "ledger_unlink"}
LEDGER_TOOLS = LEDGER_READ_TOOLS | LEDGER_WRITE_TOOLS


def _fact_payload(**overrides):
    """`ledger_add_fact` 的 fact 参数。id 由服务端分配，因此这里不带 id。"""
    payload = {
        "pid": "P1001",
        "date": "2026-09-17",
        "phase": "独立",
        "independence": "I3",
        "difficulty": None,
        "result": "未成解",
        "source_ref": "article/solutions/P1001.md:3",
        "supersedes": None,
        "note": "",
    }
    payload.update(overrides)
    return payload


def _link_payload(fact_id, **overrides):
    payload = {
        "fact_id": fact_id,
        "skill_id": "B2",
        "role": "core",
        "effect": "positive",
        "why": "这条测的是关键性质是否被发现。",
    }
    payload.update(overrides)
    return payload


def _add_fact(session, **overrides) -> str:
    return session.call("ledger_add_fact", {"fact": _fact_payload(**overrides)})["id"]


def test_ledger_tools_share_the_solution_mcp_surface(session):
    """决策 1 (a)：一次连接即可，读写的区分只靠 annotation。"""
    assert {tool["name"] for tool in session.tools()} == SOLUTION_TOOLS | LEDGER_TOOLS


def test_ledger_add_fact_schema_advertises_fact_fields_without_id(session):
    """决策 3：fact 入参的 schema 里根本没有 id，且枚举可见。"""
    tool = next(tool for tool in session.tools() if tool["name"] == "ledger_add_fact")
    fact = tool["inputSchema"]["properties"]["fact"]
    fields = fact["properties"]
    assert "id" not in fields
    assert fact.get("additionalProperties") is False
    assert fields["phase"]["enum"] == ["独立", "题解后", "赛后", "学习"]
    assert fields["independence"]["enum"] == ["I0", "I1", "I2", "I3", "I4"]
    assert fields["difficulty"]["anyOf"] == [{"type": "integer"}, {"type": "null"}]
    assert fields["result"]["enum"] == ["AC", "未成解", "TLE", "部分分", "未实现", "仅思路"]
    # difficulty 可省略（默认 null）；independence_source 已移除。
    assert "independence_source" not in fields
    assert set(fact.get("required", [])) == {
        "pid", "date", "phase", "independence",
        "result", "source_ref",
    }


def test_ledger_search_filters_expose_arrays(session):
    """fastapi-mcp 0.4 会把可空列表查询展平成字符串，需要补回数组形态。"""
    search = next(tool for tool in session.tools() if tool["name"] == "ledger_search")
    properties = search["inputSchema"]["properties"]
    assert {"type": "array", "items": {"type": "string"}} in \
        properties["independence"]["anyOf"]
    assert {"type": "array", "items": {"type": "integer"}} in \
        properties["difficulty"]["anyOf"]


def test_ledger_search_exposes_difficulty_range_bounds(session):
    """区间搜索在 MCP schema 里必须可见，且带着难度量纲的上下限。"""
    search = next(tool for tool in session.tools() if tool["name"] == "ledger_search")
    properties = search["inputSchema"]["properties"]
    for field in ("difficulty_min", "difficulty_max"):
        assert field in properties, field
        schema = properties[field]
        # `ge`/`le` 落在 anyOf 里的整数分支上，不是顶层 minimum/maximum。
        integer = [branch for branch in schema["anyOf"]
                   if branch.get("type") == "integer"]
        assert integer, schema
        assert integer[0]["minimum"] == 0 and integer[0]["maximum"] == 8000, schema
        assert {"type": "null"} in schema["anyOf"], schema


def test_ledger_search_tool_still_lists_every_documented_filter(session):
    """工具参数表与 README 对齐：难度既有精确值也有区间。"""
    search = next(tool for tool in session.tools() if tool["name"] == "ledger_search")
    properties = set(search["inputSchema"]["properties"])
    assert {"skill_id", "role", "effect", "independence", "difficulty",
            "difficulty_min", "difficulty_max", "start_date", "end_date",
            "limit"} <= properties


def test_ledger_search_tool_description_carries_the_difficulty_rules(session):
    """功能说明落在 MCP 工具说明里——流程提示词只引用它，不重复登记。

    这是 `data/prompt/*.md` 里「见 MCP 工具说明（ledger_search）」这句话的兑现点：
    客户端读到的 `description` 必须真的含完整难度口径，否则指针指向空气。
    """
    search = next(tool for tool in session.tools() if tool["name"] == "ledger_search")
    description = search["description"]
    for required in ("difficulty_min", "difficulty_max", "闭区间",
                     "所属 Fact", "取交集", "不参与任何难度筛选"):
        assert required in description, (required, description)


def test_ledger_write_tool_descriptions_carry_their_field_rules(session):
    """写工具说明也要能独立交代字段口径——提示词里的「以 MCP 工具说明为准」靠它兑现。"""
    tools = {tool["name"]: tool for tool in session.tools()}
    add_fact = tools["ledger_add_fact"]["description"]
    for required in ("difficulty", "I0", "null", "不参与任何难度筛选",
                     "EV-YYYYMMDD-NN"):
        assert required in add_fact, (required, add_fact)

    link = tools["ledger_link"]["description"]
    for required in ("core", "auxiliary", "out", "positive", "negative",
                     "boundary", "why", "一条 Link"):
        assert required in link, (required, link)


def test_ledger_add_fact_is_immediate_and_server_assigns_the_id(session):
    """决策 2（无二次确认）+ 决策 3（id 完全由服务端分配）。"""
    result = session.call("ledger_add_fact", {"fact": _fact_payload()})
    fact_id = result["id"]
    assert fact_id.startswith("EV-") and result["created_new"] is True
    assert session.call("ledger_get_fact", {"fact_id": fact_id})["fact"]["pid"] == "P1001"

    # 第二个 id 不会与第一个冲突。
    assert _add_fact(session) != fact_id


def test_ledger_add_fact_rejects_a_client_supplied_id(session):
    """决策 3：调用方传 id 会被拒，不能借此绕过服务端分配。"""
    session.call("ledger_add_fact", {"fact": _fact_payload(id="EV-R17-99")}, error=True)
    assert session.call("ledger_get_fact", {"fact_id": "EV-R17-99"}, error=True)
    # 通过 supersedes 仍可声明修正关系，但新事实自己的 id 依旧由服务端生成。
    old = _add_fact(session)
    correction = session.call("ledger_add_fact", {
        "fact": _fact_payload(supersedes=old, note="修正计数对象")})
    assert correction["id"] != old
    assert session.call("ledger_get_fact", {"fact_id": old})["fact"]["superseded"] is True


def test_ledger_link_round_trip_needs_no_confirmation(session):
    fact_id = _add_fact(session)

    assert session.call("ledger_link", _link_payload(fact_id))["ok"] is True
    # 重复 Link 仍被拒。
    session.call("ledger_link", _link_payload(fact_id), error=True)

    rows = session.call("ledger_search", {"skill_id": "B2"})
    assert [row["fact_id"] for row in rows] == [fact_id]
    assert rows[0]["why"] and rows[0]["role"] == "core"
    # 显示名也可以作为 skill 过滤条件。
    assert session.call("ledger_search", {"skill_id": "Observation"}) == rows
    assert session.call("ledger_search", {"skill_id": "B2", "role": "auxiliary"}) == []

    # 账本的读面只有 fact + link；没有任何画像投影 / 样本数 / rating / 引用校验工具。
    names = {tool["name"] for tool in session.tools()}
    assert "ledger_render_profile" not in names
    assert "ledger_verify_citation" not in names
    entry = session.call("ledger_get_fact", {"fact_id": fact_id})
    assert entry["links"][0]["skill_id"] == "B2"
    assert "rating" not in json.dumps(entry)

    assert session.call("ledger_unlink",
                        {"fact_id": fact_id, "skill_id": "B2"})["ok"]
    assert session.call("ledger_search", {"skill_id": "B2"}) == []


def test_ledger_mcp_rejects_unknown_facts_skills_and_empty_why(session):
    fact_id = _add_fact(session)
    session.call("ledger_link", _link_payload("EV-NOPE-01"), error=True)
    session.call("ledger_link", _link_payload(fact_id, skill_id="Z9"), error=True)
    session.call("ledger_link", _link_payload(fact_id, why="   "), error=True)
    session.call("ledger_add_fact", {"fact": _fact_payload(rating=2600)}, error=True)
    session.call("ledger_add_fact", {"fact": _fact_payload(phase="赛后复盘")}, error=True)


def test_ledger_web_view_shows_only_facts_and_links(client, session):
    assert client.get("/ledger").status_code == 200
    page = client.get("/ledger").text
    assert "能力证据库" in page
    # 页面不再有画像表 / 加法对账 / 引用校验区。
    assert "独立样本" not in page and "Independent Samples" not in page
    assert "加法对账" not in page
    assert "引用校验" not in page

    # 已删除的接口不再存在。
    assert client.get("/api/ledger/profile").status_code == 404
    assert client.get("/api/ledger/increment").status_code == 404
    assert client.get("/api/ledger/verify-citation",
                      params={"fact_id": "EV-R16-02",
                              "claimed_skill_id": "A4"}).status_code == 404
    assert client.post("/api/ledger/check-aux", json={"text": "x"}).status_code == 404

    facts = client.get("/api/ledger/facts").json()
    assert facts["fact_count"] == 0 and facts["items"] == []
    assert facts["returned"] == 0 and facts["has_more"] is False
    assert client.get("/api/ledger/facts", params={"limit": 0}).status_code == 422
    assert client.get("/api/ledger/facts", params={"limit": 5001}).status_code == 422

    fact_id = _add_fact(session)
    session.call("ledger_link", _link_payload(fact_id, skill_id="B1", role="auxiliary"))
    payload = client.get("/api/ledger/facts").json()
    assert payload["fact_count"] == 1 and payload["link_count"] == 1
    item = payload["items"][0]
    assert item["id"] == fact_id
    assert item["links"][0]["skill_id"] == "B1"
    assert item["links"][0]["role"] == "auxiliary"

    # 展示接口不写账本。
    assert client.get("/api/ledger/facts").json()["fact_count"] == 1


def test_ledger_facts_endpoint_defaults_to_the_whole_ledger_newest_first(client, session):
    """页面数据必须与账本同步：默认返回整库、按最新优先，并如实报告是否截断。

    `client` 已经把账本指向临时目录（见 `isolated_data`）。
    """
    # 造 5 条事实，日期错开，且写入顺序与日期顺序不一致。
    for index, day in enumerate(["2026-09-01", "2026-09-03", "2026-09-02",
                                 "2026-09-05", "2026-09-04"]):
        fact_id = _add_fact(session, date=day, pid=f"P{1000 + index}")
        session.call("ledger_link", _link_payload(fact_id))

    body = client.get("/api/ledger/facts").json()
    assert body["fact_count"] == 5
    assert body["returned"] == 5
    assert body["has_more"] is False
    assert "最新优先" in body["order"]
    dates = [item["date"] for item in body["items"]]
    assert dates == sorted(dates, reverse=True), dates
    assert body["items"][0]["date"] == "2026-09-05"
    assert body["items"][-1]["date"] == "2026-09-01"
    # 每条 fact 都带 replaced_by 字段（页面据此显示取代关系）。
    assert all("replaced_by" in item for item in body["items"])

    # limit 生效并如实报告截断。
    limited = client.get("/api/ledger/facts", params={"limit": 2}).json()
    assert limited["returned"] == 2 and limited["has_more"] is True
    assert limited["fact_count"] == 5


def test_ledger_search_endpoint_accepts_comma_separated_difficulty(client, session):
    """页面用的 HTTP 检索必须同时接受逗号分隔与重复同名两种难度写法。

    早先是 `list[int]`：重复参数可用，但 `difficulty=1500,2500` 会被 FastAPI 的
    类型校验直接 422，而页面输入框本来就允许逗号多值。现在收字符串再自行展平，
    两种写法都支持（是改动前的超集）。
    """
    cheap = _add_fact(session, difficulty=1500, pid="P1500")
    dear = _add_fact(session, difficulty=2500, pid="P2500")
    unknown = _add_fact(session, difficulty=None, pid="P0000")
    for fact_id in (cheap, dear, unknown):
        session.call("ledger_link", _link_payload(fact_id))

    def ids(pairs):
        body = client.get("/api/ledger/search", params=[("skill_id", "B2"), *pairs])
        assert body.status_code == 200, body.text
        return {row["fact_id"] for row in body.json()}

    assert ids([]) == {cheap, dear, unknown}
    # null 难度的 Fact 不会被任何难度筛选命中。
    assert ids([("difficulty", "1500,2500")]) == {cheap, dear}
    assert ids([("difficulty", "1500"), ("difficulty", "2500")]) == {cheap, dear}
    # 两种写法可以混用。
    assert ids([("difficulty", "1500"), ("difficulty", "2500,3000")]) == {cheap, dear}
    assert ids([("difficulty", "1500")]) == {cheap}
    assert ids([("difficulty", "3000")]) == set()
    # 空白与空串按未筛选处理，不报错也不静默返回空。
    assert ids([("difficulty", "  ")]) == {cheap, dear, unknown}
    # 非法难度按账本口径报 422，而不是 500。
    assert client.get("/api/ledger/search",
                      params={"skill_id": "B2", "difficulty": "easy"}).status_code == 422
    assert client.get("/api/ledger/search",
                      params={"skill_id": "B2",
                              "difficulty": "1500,oops"}).status_code == 422


def test_ledger_search_endpoint_supports_difficulty_range(client, session):
    """页面「难度区间」用的两个参数：闭区间、单边开放、与精确值取交集。"""
    spread: list[tuple[int | None, str]] = []
    for pid, difficulty in (("P1400", 1400), ("P1900", 1900),
                            ("P2500", 2500), ("P0000", None)):
        fact_id = _add_fact(session, difficulty=difficulty, pid=pid)
        session.call("ledger_link", _link_payload(fact_id))
        spread.append((difficulty, fact_id))

    def fact_with(difficulty: int | None) -> str:
        return next(fid for value, fid in spread if value == difficulty)

    def ids(**extra):
        body = client.get("/api/ledger/search",
                          params={"skill_id": "B2", **extra})
        assert body.status_code == 200, body.text
        return {row["fact_id"] for row in body.json()}

    assert ids(difficulty_min="1900", difficulty_max="2500") == {
        fact_with(1900), fact_with(2500)}
    assert ids(difficulty_min="2500") == {fact_with(2500)}
    assert ids(difficulty_max="1400") == {fact_with(1400)}
    # 未核定难度的样本不出现在任何区间结果里。
    assert fact_with(None) not in ids(difficulty_min="0", difficulty_max="8000")
    # 与精确值取交集
    assert ids(difficulty="1400,2500", difficulty_min="2000") == {fact_with(2500)}
    assert ids(difficulty="1400", difficulty_min="2000") == set()

    # 上下界颠倒、非整数、越界都按调用错误报 422。
    for extra in ({"difficulty_min": "2500", "difficulty_max": "1900"},
                  {"difficulty_min": "easy"},
                  {"difficulty_max": "1.5"},
                  {"difficulty_min": "-1"},
                  {"difficulty_max": "8001"}):
        response = client.get("/api/ledger/search",
                              params={"skill_id": "B2", **extra})
        assert response.status_code == 422, (extra, response.status_code)
