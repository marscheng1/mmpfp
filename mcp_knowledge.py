"""
知识库模块 — 为 MCP 服务提供 data/solutions 下的 Markdown 文件读取、筛选、搜索功能。
"""
import os
from os import path
from datetime import datetime, timezone
from typing import NotRequired, Optional, TypedDict

from config import SOLUTIONS_DIR

MAX_FILE_SIZE = 2 * 1024 * 1024
MAX_QUERY_LENGTH = 200
MAX_RESULT_LIMIT = 100


class FileInfo(TypedDict):
    path: str
    name: str
    size: int
    created_at: str
    modified_at: str


class SearchResult(TypedDict):
    path: str
    name: str
    snippet: str
    matched_in: str


class ReadResult(TypedDict):
    path: NotRequired[str]
    name: NotRequired[str]
    content: NotRequired[str]
    error: NotRequired[str]


def _get_file_info(root: str, rel_path: str) -> FileInfo:
    """获取单个文件的元信息"""
    full = path.join(root, rel_path)
    try:
        mtime = os.path.getmtime(full)
        ctime = os.path.getctime(full)
        size = os.path.getsize(full)
    except OSError:
        mtime = ctime = 0.0
        size = 0
    return {
        "path": rel_path.replace("\\", "/"),
        "name": path.basename(rel_path),
        "size": size,
        "created_at": datetime.fromtimestamp(ctime, tz=timezone.utc).isoformat(),
        "modified_at": datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(),
    }


def _scan_all_files(root: str, base_prefix: str = "") -> list[FileInfo]:
    """递归扫描所有 .md 文件，返回扁平列表"""
    results: list[FileInfo] = []
    try:
        for entry in os.listdir(root):
            full = path.join(root, entry)
            rel = path.join(base_prefix, entry) if base_prefix else entry
            if path.islink(full):
                continue
            if path.isdir(full):
                results.extend(_scan_all_files(full, rel))
            elif entry.endswith(".md"):
                info = _get_file_info(SOLUTIONS_DIR, rel)
                results.append(info)
    except OSError:
        pass
    return results


def _safe_path(relative_path: str) -> str:
    """校验路径安全性，防止目录穿越"""
    relative_path = relative_path.replace("\\", "/").strip("/")
    if not relative_path or len(relative_path) > 500:
        raise ValueError("路径不能为空或过长")
    if ".." in relative_path.split("/"):
        raise ValueError("路径穿越不允许")
    root = path.realpath(SOLUTIONS_DIR)
    abs_path = path.realpath(path.join(root, relative_path))
    try:
        inside_root = path.commonpath((root, abs_path)) == root
    except ValueError:
        inside_root = False
    if not inside_root:
        raise ValueError("路径越界")
    current = root
    for component in relative_path.split("/"):
        current = path.join(current, component)
        if path.islink(current):
            raise ValueError("不允许访问符号链接")
    return abs_path


def list_knowledge(
    limit: Optional[int] = None,
    time_range: Optional[str] = None,
    sort_by: str = "created_at",
    order: str = "desc",
) -> list[FileInfo]:
    """
    列出知识库文章，支持筛选和排序。

    Args:
        limit: 限制返回数量（最近 K 篇）
        time_range: 时间范围，格式 "YYYY-MM-DD,YYYY-MM-DD"
                    例如 "2024-01-01,2024-12-31" 表示该区间内的文章
                    "2024-06-01," 表示 2024-06-01 之后的
        sort_by: 排序字段，可选 "created_at" / "modified_at" / "name"
        order: 排序方向 "asc" 或 "desc"，默认 desc（最新的在前）

    Returns:
        文章列表，每项包含 path, name, size, created_at, modified_at
    """
    if limit is not None and not 1 <= limit <= MAX_RESULT_LIMIT:
        raise ValueError(f"limit 必须在 1 到 {MAX_RESULT_LIMIT} 之间")
    if order.lower() not in {"asc", "desc"}:
        raise ValueError("order 必须是 asc 或 desc")
    if sort_by not in {"created_at", "modified_at", "name"}:
        raise ValueError("sort_by 参数无效")

    if not path.exists(SOLUTIONS_DIR):
        return []

    files = _scan_all_files(SOLUTIONS_DIR)

    # 时间筛选
    if time_range:
        parts = time_range.split(",")
        if len(parts) == 2:
            t_start_s, t_end_s = parts[0].strip(), parts[1].strip()
            try:
                t_start = datetime.fromisoformat(t_start_s).replace(
                    tzinfo=timezone.utc) if t_start_s else None
                t_end = datetime.fromisoformat(t_end_s).replace(
                    tzinfo=timezone.utc) if t_end_s else None
            except ValueError as exc:
                raise ValueError("time_range 格式无效") from exc
        else:
            raise ValueError("time_range 格式无效")

        if t_start and t_end and t_start > t_end:
            raise ValueError("time_range 起始时间不能晚于结束时间")

        if t_start or t_end:
            filtered: list[FileInfo] = []
            for f in files:
                ct = datetime.fromisoformat(f["created_at"])
                if t_start and ct < t_start:
                    continue
                if t_end and ct > t_end:
                    continue
                filtered.append(f)
            files = filtered

    # 排序
    reverse = order.lower() != "asc"
    if sort_by == "name":
        files.sort(key=lambda x: x["name"], reverse=reverse)
    elif sort_by == "modified_at":
        files.sort(key=lambda x: x["modified_at"], reverse=reverse)
    else:  # created_at
        files.sort(key=lambda x: x["created_at"], reverse=reverse)

    # 限制数量
    if limit is not None:
        files = files[:limit]

    return files


def read_knowledge(file_path: str) -> ReadResult:
    """
    读取指定知识库文章的 Markdown 内容。

    Args:
        file_path: 文件的相对路径（相对于 data/solutions），例如 "math/2024-01-01-abc.md"

    Returns:
        包含 path, name, content 的字典；出错时返回 {"error": "..."}
    """
    if not file_path.endswith(".md"):
        file_path += ".md"
    try:
        abs_path = _safe_path(file_path)
    except ValueError as e:
        return {"error": str(e)}

    if not path.exists(abs_path):
        return {"error": "文件不存在"}

    try:
        if not path.isfile(abs_path):
            return {"error": "目标不是文件"}
        if path.getsize(abs_path) > MAX_FILE_SIZE:
            return {"error": "文件过大"}
        with open(abs_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {
            "path": file_path.replace("\\", "/"),
            "name": path.basename(file_path),
            "content": content,
        }
    except OSError as e:
        return {"error": f"读取失败: {e}"}


def search_knowledge(query: str, limit: int = 10) -> list[SearchResult]:
    """
    全文搜索知识库文章。

    Args:
        query: 搜索关键词（大小写不敏感）
        limit: 最大返回数量

    Returns:
        匹配的文章列表，每项包含 path, name, snippet（匹配片段）
    """
    query = query.strip()
    if not query or len(query) > MAX_QUERY_LENGTH:
        raise ValueError("query 不能为空且长度不能超过 200")
    if not 1 <= limit <= MAX_RESULT_LIMIT:
        raise ValueError(f"limit 必须在 1 到 {MAX_RESULT_LIMIT} 之间")

    if not path.exists(SOLUTIONS_DIR):
        return []

    files = _scan_all_files(SOLUTIONS_DIR)
    results: list[SearchResult] = []
    query_lower = query.lower()

    for f in files:
        abs_path = path.abspath(path.join(SOLUTIONS_DIR, f["path"]))
        try:
            if f["size"] > MAX_FILE_SIZE:
                continue
            with open(abs_path, "r", encoding="utf-8") as fp:
                content = fp.read()
        except OSError:
            continue

        content_lower = content.lower()
        path_lower = f["path"].lower()
        content_match = query_lower in content_lower
        path_match = query_lower in path_lower
        if not content_match and not path_match:
            continue

        # 提取匹配片段（取前后各 50 字符）
        idx = content_lower.find(query_lower)
        matched_in = "content"
        if idx < 0:
            matched_in = "path"
            idx = path_lower.find(query_lower)
            snippet_source = f["path"]
        else:
            snippet_source = content
        start = max(0, idx - 50)
        end = min(len(snippet_source), idx + len(query) + 50)
        snippet = snippet_source[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(content):
            snippet = snippet + "..."

        results.append({
            "path": f["path"],
            "name": f["name"],
            "snippet": snippet,
            "matched_in": matched_in,
        })

        if len(results) >= limit:
            break

    return results
