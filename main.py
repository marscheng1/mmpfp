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

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse

from pydantic import BaseModel, Field

from config import (
    ATCODER_ID, CF_ID, DATA_FILE, HDU_ID, LUOGU_ID, META_FILE, PAGE_DIR,
    PROMPT_FILE, QOJ_ID, SOLUTIONS_DIR, day_id, day_len, month_id, month_len,
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
    yield
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


