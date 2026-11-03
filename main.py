import json
import logging
import os
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from os import path
from datetime import datetime
from typing import Any, Callable, cast

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse

from pydantic import BaseModel, Field

from solution_mcp import create_solution_mcp
from ledger import LedgerError, LedgerStore

from config import (
    ATCODER_ID, CF_ID, CSES_ID, DATA_FILE, DMY_ID, HDU_ID, LEDGER_FACTS_FILE,
    LEDGER_LINKS_FILE, LOJ_ID, LUOGU_ID, META_FILE, PAGE_DIR, PROMPT_FILE, QOJ_ID,
    SOLUTIONS_DIR, UOJ_ID, day_id, day_len, month_id, month_len,
)

logger = logging.getLogger(__name__)
MAX_CONTENT_SIZE = 2 * 1024 * 1024
MAX_PATH_LENGTH = 500


class Record(BaseModel):
    time: int = Field(ge=0)
    status: bool
    pid: str = Field(min_length=1, max_length=200)
    rid: str = Field(min_length=1, max_length=200)


class PathRequest(BaseModel):
    path: str = Field(min_length=1, max_length=MAX_PATH_LENGTH)


class FileRequest(PathRequest):
    content: str = Field(default="", max_length=MAX_CONTENT_SIZE)


class MetaRequest(BaseModel):
    path: str = Field(min_length=1, max_length=MAX_PATH_LENGTH)
    elapsed: int = Field(default=0, ge=0, le=2_000_000_000)
    completed: bool = False


class MetaBatchRequest(BaseModel):
    items: dict[str, dict[str, object]]


records_cache = []
day_count_cache = [0] * day_len
day_sum_cache = [0] * day_len
month_count_cache = [0] * month_len
month_sum_cache = [0] * month_len
pass_count = 0
records_lock = threading.RLock()
meta_lock = threading.RLock()
ledger_lock = threading.RLock()

#: 账本路径。默认取自 config.json，测试可以 monkeypatch 这两个名字。
LEDGER_FACTS_FILE = LEDGER_FACTS_FILE
LEDGER_LINKS_FILE = LEDGER_LINKS_FILE


def make_ledger_store() -> LedgerStore:
    """按当前（可被测试覆盖的）路径构造账本；构造本身不读盘。"""
    return LedgerStore(
        facts_file=LEDGER_FACTS_FILE,
        links_file=LEDGER_LINKS_FILE,
    )


def load_count_cache():
    global day_count_cache, day_sum_cache, month_count_cache, month_sum_cache, pass_count

    passed: set[str] = set()
    for i in range(day_len):
        day_count_cache[i] = 0
    for i in range(month_len):
        month_count_cache[i] = 0
    for rec in records_cache:
        time = datetime.fromtimestamp(rec["time"])
        status = rec["status"]
        pid = rec["pid"]

        if status:
            if pid not in passed:
                passed.add(pid)
                current_day = day_id(time)
                current_month = month_id(time)
                if not 0 <= current_day < day_len or not 0 <= current_month < month_len:
                    continue
                day_count_cache[current_day] += 1
                month_count_cache[current_month] += 1
    day_sum_cache[0] = day_count_cache[0]
    for i in range(1, day_len):
        day_sum_cache[i] = day_sum_cache[i - 1] + day_count_cache[i]
    month_sum_cache[0] = month_count_cache[0]
    for i in range(1, month_len):
        month_sum_cache[i] = month_sum_cache[i - 1] + month_count_cache[i]
    pass_count = len(passed)
    print("loaded", pass_count, len(records_cache))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global records_cache
    os.makedirs(SOLUTIONS_DIR, exist_ok=True)
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, list):
            raise ValueError("records.json 必须是数组")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError("无法加载 records.json，请检查文件格式") from exc
    records = cast(list[dict[str, Any]], raw)
    validated_records = [Record.model_validate(record) for record in records]
    unique = {record.rid: record.model_dump()
              for record in validated_records}.values()
    try:
        records_cache = sorted(
            unique,
            key=lambda r: r["time"],
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeError("records.json 包含无效记录") from exc
    with records_lock:
        load_count_cache()
    try:
        async with solution_mcp.lifespan():
            yield
    finally:
        save_records_sync()

app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def request_logging(request: Request, call_next: Callable[[Request], Any]) -> Response:
    started_at = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started_at) * 1000
    logger.info(
        "request method=%s path=%s status=%s elapsed_ms=%.1f",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


def save_records_sync():
    with records_lock:
        directory = path.dirname(DATA_FILE)
        fd, temporary_file = tempfile.mkstemp(
            dir=directory, prefix="records.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(records_cache, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary_file, DATA_FILE)
        finally:
            if path.exists(temporary_file):
                os.remove(temporary_file)


@app.get("/", response_class=HTMLResponse)
def index():
    with open(path.join(PAGE_DIR, "index.html"), encoding="utf-8") as f:
        return f.read()


@app.get("/api/id/luogu")
def get_luogu_id():
    return LUOGU_ID


@app.get("/api/id/qoj")
def get_qoj_id():
    return QOJ_ID


@app.get("/api/id/cf")
def get_cf_id():
    return CF_ID


@app.get("/api/id/hdu")
def get_hdu_id():
    return HDU_ID


@app.get("/api/id/atcoder")
def get_atcoder_id():
    return ATCODER_ID


@app.get("/api/id/dmy")
def get_dmy_id():
    return DMY_ID


@app.get("/api/id/uoj")
def get_uoj_id():
    return UOJ_ID


@app.get("/api/id/loj")
def get_loj_id():
    return LOJ_ID


@app.get("/api/id/cses")
def get_cses_id():
    return CSES_ID


@app.get("/api/basic")
def api_basic():
    return {
        "pass_count": pass_count
    }


@app.post("/api/push_record")
def push_record(record: list[Record]):
    global records_cache

    with records_lock:
        changed = False
        temp_dict = {r["rid"]: r for r in records_cache}
        for rec in record:
            current = temp_dict.get(rec.rid)
            if current != rec.model_dump():
                temp_dict[rec.rid] = rec.model_dump()
                changed = True
        if changed:
            records_cache = sorted(temp_dict.values(), key=lambda r: r["time"])
            load_count_cache()
            save_records_sync()


def validate_date_range(
    start_date: str,
    end_date: str,
    unit_len: int,
    converter: Callable[[str], int],
) -> tuple[int, int]:
    try:
        start = converter(start_date)
        end = converter(end_date)
    except (TypeError, ValueError):
        raise HTTPException(422, "日期格式无效")
    if start < 0 or end >= unit_len or start > end:
        raise HTTPException(422, "日期范围无效")
    return start, end


@app.get("/api/day_count")
def day_count(start_date: str, end_date: str):
    start, end = validate_date_range(start_date, end_date, day_len, day_id)
    return day_count_cache[start: end + 1]


@app.get("/api/day_sum")
def day_sum(start_date: str, end_date: str):
    start, end = validate_date_range(start_date, end_date, day_len, day_id)
    return day_sum_cache[start: end + 1]


@app.get("/api/month_count")
def month_count(start_date: str, end_date: str):
    start, end = validate_date_range(start_date, end_date, month_len, month_id)
    return month_count_cache[start: end + 1]


@app.get("/api/month_sum")
def month_sum(start_date: str, end_date: str):
    start, end = validate_date_range(start_date, end_date, month_len, month_id)
    return month_sum_cache[start: end + 1]


# ===== 解题日志 =====
def load_meta() -> dict[str, dict[str, object]]:
    """读取计时器/完成状态元数据"""
    if not path.exists(META_FILE):
        return {}
    try:
        with open(META_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _write_meta(meta: dict[str, dict[str, object]]):
    """保存计时器/完成状态元数据"""
    directory = path.dirname(META_FILE)
    os.makedirs(directory, exist_ok=True)
    fd, temporary_file = tempfile.mkstemp(
        dir=directory, prefix="solutions-meta.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary_file, META_FILE)
    finally:
        if path.exists(temporary_file):
            os.remove(temporary_file)


def save_meta(meta: dict[str, dict[str, object]]):
    with meta_lock:
        _write_meta(meta)


def merge_meta(items: dict[str, dict[str, object]]):
    """原子合并元数据；旧客户端或延迟请求不得让计时倒退。"""
    with meta_lock:
        meta = load_meta()
        for file_path, item in items.items():
            old = meta.get(file_path, {})
            old_elapsed = old.get("elapsed", 0)
            new_elapsed = item.get("elapsed", 0)
            if not isinstance(old_elapsed, int) or isinstance(old_elapsed, bool):
                old_elapsed = 0
            if not isinstance(new_elapsed, int) or isinstance(new_elapsed, bool):
                continue
            meta[file_path] = {
                "elapsed": max(old_elapsed, new_elapsed),
                "completed": bool(item.get("completed", False)),
            }
        _write_meta(meta)


def safe_solutions_path(relative_path: str) -> str:
    """校验路径安全性，防止目录穿越"""
    # 替换反斜杠为正斜杠，去除首尾斜杠
    relative_path = relative_path.replace("\\", "/").strip("/")
    if not relative_path or len(relative_path) > MAX_PATH_LENGTH:
        raise HTTPException(400, "路径不能为空或过长")
    # 不允许 ".." 路径穿越
    if ".." in relative_path.split("/"):
        raise HTTPException(400, "路径穿越不允许")
    root = path.realpath(SOLUTIONS_DIR)
    abs_path = path.realpath(path.join(root, relative_path))
    try:
        inside_root = path.commonpath((root, abs_path)) == root
    except ValueError:
        inside_root = False
    if not inside_root:
        raise HTTPException(400, "路径越界")
    current = root
    for component in relative_path.split("/"):
        current = path.join(current, component)
        if path.islink(current):
            raise HTTPException(400, "不允许访问符号链接")
    return abs_path


@app.get("/solution-journal", response_class=HTMLResponse)
def solution_journal():
    with open(path.join(PAGE_DIR, "solution-journal.html"), encoding="utf-8") as f:
        return f.read()


@app.get("/api/solutions/list")
def solutions_list() -> list[dict[str, Any]]:
    """递归列出解题日志目录的树形结构"""
    def scan_dir(dir_path: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        try:
            items: list[dict[str, Any]] = []
            for entry in os.listdir(dir_path):
                full = path.join(dir_path, entry)
                if path.islink(full):
                    continue
                if path.isdir(full):
                    children = scan_dir(full)  # 递归扫描子目录
                    try:
                        ctime = os.path.getctime(full)
                    except OSError:
                        ctime = 0
                    items.append({"name": entry, "type": "dir",
                                 "children": children, "_ctime": ctime})
                elif entry.endswith(".md"):
                    try:
                        ctime = os.path.getctime(full)
                    except OSError:
                        ctime = 0
                    items.append(
                        {"name": entry, "type": "file", "_ctime": ctime})
            # 排序：文件夹在前，文件在后；同类按创建时间降序（近的在前）
            items.sort(key=lambda x: (
                0 if x["type"] == "dir" else 1, -x["_ctime"]))
            for item in items:
                del item["_ctime"]
            result = items
        except OSError:
            pass
        return result

    root = SOLUTIONS_DIR
    if not path.exists(root):
        return list[dict[str, Any]]()
    return scan_dir(root)


@app.post("/api/solutions/mkdir")
def solutions_mkdir(data: PathRequest):
    dir_name = data.path
    abs_path = safe_solutions_path(dir_name)
    try:
        os.makedirs(abs_path, exist_ok=True)
        return {"ok": True}
    except OSError:
        logger.exception("创建解题日志目录失败")
        raise HTTPException(500, "创建目录失败")


@app.post("/api/solutions/new")
def solutions_new(data: FileRequest):
    file_path = data.path
    if not file_path.endswith(".md"):
        file_path += ".md"
    content = data.content
    abs_path = safe_solutions_path(file_path)
    try:
        parent = path.dirname(abs_path)
        os.makedirs(parent, exist_ok=True)
        if path.exists(abs_path):
            raise HTTPException(400, "文件已存在")
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"ok": True}
    except OSError:
        logger.exception("创建解题日志文件失败")
        raise HTTPException(500, "创建文件失败")


@app.get("/api/solutions/read")
def solutions_read(file_path: str):
    if not file_path.endswith(".md"):
        file_path += ".md"
    abs_path = safe_solutions_path(file_path)
    if not path.exists(abs_path):
        raise HTTPException(404, "文件不存在")
    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"content": content}
    except OSError:
        logger.exception("读取解题日志失败")
        raise HTTPException(500, "读取文件失败")


@app.post("/api/solutions/save")
def solutions_save(data: FileRequest):
    file_path = data.path
    if not file_path.endswith(".md"):
        file_path += ".md"
    content = data.content
    abs_path = safe_solutions_path(file_path)
    try:
        parent = path.dirname(abs_path)
        os.makedirs(parent, exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"ok": True}
    except OSError:
        logger.exception("保存解题日志失败")
        raise HTTPException(500, "保存文件失败")


@app.post("/api/solutions/append")
def solutions_append(data: FileRequest):
    """追加内容到文件末尾（追加模式）"""
    file_path = data.path
    if not file_path.endswith(".md"):
        file_path += ".md"
    content = data.content
    abs_path = safe_solutions_path(file_path)
    if not path.exists(abs_path):
        raise HTTPException(404, "文件不存在")
    try:
        with open(abs_path, "a", encoding="utf-8") as f:
            f.write(content)
        return {"ok": True}
    except OSError:
        logger.exception("追加解题日志失败")
        raise HTTPException(500, "追加内容失败")


@app.post("/api/solutions/delete")
def solutions_delete(data: PathRequest):
    """删除文件或文件夹"""
    item_path = data.path
    abs_path = safe_solutions_path(item_path)
    if path.realpath(SOLUTIONS_DIR) == abs_path:
        raise HTTPException(400, "不允许删除知识库根目录")
    if not path.exists(abs_path):
        raise HTTPException(404, "路径不存在")
    try:
        if path.isdir(abs_path):
            import shutil
            shutil.rmtree(abs_path)
        else:
            os.remove(abs_path)
        return {"ok": True}
    except OSError:
        logger.exception("删除解题日志失败")
        raise HTTPException(500, "删除失败")


@app.get("/api/solutions/meta")
def solutions_meta_get():
    """获取所有文件的计时器/完成状态元数据"""
    return load_meta()


@app.get("/api/solutions/read-prompt")
def solutions_read_prompt():
    """读取 prompt 模板文件"""
    prompt_path = PROMPT_FILE
    if not path.exists(prompt_path):
        raise HTTPException(404, "prompt 模板文件不存在")
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read(), media_type="text/plain")
    except OSError as e:
        raise HTTPException(500, f"读取 prompt 模板失败: {e}")


@app.post("/api/solutions/meta")
def solutions_meta_set(data: MetaRequest):
    """保存单个文件的计时器/完成状态"""
    merge_meta({data.path: {"elapsed": data.elapsed, "completed": data.completed}})
    return {"ok": True}


@app.post("/api/solutions/meta/batch")
def solutions_meta_batch(data: MetaBatchRequest):
    """批量保存所有文件的计时器/完成状态"""
    merge_meta(data.items)
    return {"ok": True}


@app.post("/api/solutions/meta/delete")
def solutions_meta_delete(data: PathRequest):
    """删除文件或目录对应的计时元数据。"""
    key = data.path.removesuffix(".md").replace("\\", "/").strip("/")
    with meta_lock:
        meta = load_meta()
        meta = {name: value for name, value in meta.items()
                if name != key and not name.startswith(key + "/")}
        _write_meta(meta)
    return {"ok": True}


def get_submissions_snapshot(pid: str | None = None) -> list[dict[str, Any]]:
    """按题号或读取全部缓存快照；与前端采集共用锁，避免读到并发更新的中间状态。"""
    with records_lock:
        return [record.copy() for record in records_cache if pid is None or record["pid"] == pid]


# ===== 能力证据库（只读展示） =====
def _split_csv(values: list[str] | None) -> list[str] | None:
    """把「重复同名参数 + 逗号分隔」两种写法展平成值列表。

    例：`?difficulty=1500,2500&difficulty=3000` → `["1500", "2500", "3000"]`。
    空串与纯空白被丢弃；空结果按未筛选处理（返回 None）。
    """
    if not values:
        return None
    flattened: list[str] = []
    for value in values:
        flattened.extend(piece.strip() for piece in value.split(","))
    kept = [piece for piece in flattened if piece]
    return kept or None


@app.get("/ledger", response_class=HTMLResponse)
def ledger_page():
    with open(path.join(PAGE_DIR, "ledger.html"), encoding="utf-8") as f:
        return f.read()


@app.get("/api/ledger/facts")
def ledger_facts(limit: int = 2000):
    """全部 Facts（含各自的 Links），供人工核查。被取代的 Fact 仍可读。

    默认返回整个账本（上限 2000 条），**按最新优先**排序（date 降序，同日内 id 降序），
    因此刚写入的事实一定出现在最前面。响应里的 `returned` / `has_more` 让调用方
    能判断是否被截断——账本超过上限时应缩小查询而不是静默丢数据。
    """
    if not 1 <= limit <= 5000:
        raise HTTPException(422, "limit 必须在 1–5000 之间")
    store = make_ledger_store()
    try:
        facts = store.read_facts()
        links = store.read_links()
    except LedgerError as exc:
        raise HTTPException(422, str(exc)) from exc
    by_fact: dict[str, list[dict[str, Any]]] = {}
    for link in links:
        by_fact.setdefault(link.fact_id, []).append(link.model_dump())
    # 一次算出取代关系，避免逐条回查（否则是 O(n²) 次读盘）。
    replaced_by = {fact.supersedes: fact.id for fact in facts if fact.supersedes}
    ordered = sorted(facts, key=lambda item: (item.date, item.id), reverse=True)
    selected = ordered[:limit]
    items = [
        {
            **fact.model_dump(),
            "replaced_by": replaced_by.get(fact.id),
            "links": by_fact.get(fact.id, []),
        }
        for fact in selected
    ]
    return {
        "facts_file": store.facts_file,
        "links_file": store.links_file,
        "fact_count": len(facts),
        "link_count": len(links),
        "returned": len(items),
        "has_more": len(ordered) > len(items),
        "order": "date desc, id desc（最新优先）",
        "items": items,
    }


@app.get("/api/ledger/search")
def ledger_search(
    skill_id: str,
    role: str | None = None,
    effect: str | None = None,
    independence: list[str] | None = Query(
        default=None,
        description="独立性筛选，可多值：逗号分隔或重复同名参数"),
    difficulty: list[str] | None = Query(
        default=None,
        description=("难度精确筛选，可多值：逗号分隔（`difficulty=1500,2500`）"
                     "或重复同名参数。取所属 Fact 的 difficulty，命中任一即返回；"
                     "difficulty 为 null 的 Fact 不会被命中。")),
    difficulty_min: str | None = Query(
        default=None,
        description=("难度区间下界（含）。只给下界表示“≥ 下界”；"
                     "与 difficulty_max 同时给出时必须 ≤ 它。")),
    difficulty_max: str | None = Query(
        default=None,
        description=("难度区间上界（含）。只给上界表示“≤ 上界”；"
                     "与 difficulty 同时给出时是“与”关系。")),
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int | None = None,
):
    """按能力反查 Link（连带所属 Fact），可按难度精确值/区间等条件筛选。

    这里收 `list[str]` 而不是 `list[int]`：FastAPI 对 `list[int]` 会先做类型校验，
    `difficulty=1500,2500` 这种逗号写法直接 422，而页面输入框本来就允许逗号多值。
    收字符串后交给 `_normalise_difficulty_filter` / 枚举校验解析，于是**重复同名参数
    与逗号分隔两种写法都能用**——这是改动前 `list[int]`（只支持重复参数）的超集。
    区间两界也收字符串，同样交给 `_normalise_difficulty_bounds` 解析并校验。
    """
    store = make_ledger_store()
    try:
        return store.search(
            skill_id=skill_id, role=role, effect=effect,
            independence=_split_csv(independence),
            difficulty=_split_csv(difficulty),
            difficulty_min=difficulty_min, difficulty_max=difficulty_max,
            start_date=start_date, end_date=end_date, limit=limit)
    except LedgerError as exc:
        raise HTTPException(422, str(exc)) from exc


solution_mcp = create_solution_mcp(
    app,
    get_solutions_dir=lambda: SOLUTIONS_DIR,
    resolve_path=safe_solutions_path,
    read_report=solutions_read,
    get_submissions=get_submissions_snapshot,
    get_ledger_store=make_ledger_store,
)


