"""MCP server, isolated from the web application's routes.

`/mcp` publishes two groups in one connection:

* the four read-only report/submission queries (all `readOnlyHint=True`);
* the Evidence Ledger fact+link tools (see `ledger_mcp.py`), where the three read
  tools stay `readOnlyHint=True` and the three write tools are marked non-read-only,
  with `ledger_unlink` additionally marked destructive.

The read-only boundary is therefore per-tool (`ToolAnnotations`), not per-server:
the ledger writes never touch the existing web/API routes, and this internal app is
still only reachable through the adapter's in-process ASGI client.
"""

import logging
import ntpath
import os
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Any, Literal

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi_mcp import FastApiMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, BeforeValidator, Field

from ledger import LedgerStore
from ledger_mcp import TOOL_NAMES as LEDGER_TOOL_NAMES
from ledger_mcp import enrich_ledger_tools, register_ledger_routes

logger = logging.getLogger(__name__)
TOOL_NAMES = [
    "list_solution_reports", "get_solution_report", "get_problem_submissions",
    "get_submissions_by_time",
    *LEDGER_TOOL_NAMES,
]
#: 原有的四个只读查询；账本工具的 annotation 由 `enrich_ledger_tools` 处理。
READ_ONLY_QUERY_NAMES = {
    "list_solution_reports", "get_solution_report", "get_problem_submissions",
    "get_submissions_by_time",
}
# The adapter encodes explicit JSON null query parameters as empty strings.
# Treat those as omitted, consistent with the nullable MCP input schema.
OptionalQueryTime = Annotated[
    datetime | None, BeforeValidator(lambda value: None if value == "" else value),
]


class ReportContent(BaseModel):
    content: str = Field(description="解题报告的完整 UTF-8 Markdown 内容")


class Submission(BaseModel):
    time: int = Field(description="提交时间，Unix 时间戳（秒）")
    status: bool = Field(description="是否通过，true 表示通过，false 表示未通过")
    pid: str = Field(description="带平台标识的题号，与采集记录中的 pid 完全一致")
    rid: str = Field(description="提交记录 ID")


def resolve_time_window(start_time: datetime | None, end_time: datetime | None) -> tuple[float, float]:
    try:
        start = start_time.timestamp() if start_time is not None else float("-inf")
        end = end_time.timestamp() if end_time is not None else time.time()
    except (OSError, OverflowError, ValueError) as exc:
        raise HTTPException(422, "时间超出系统支持的范围") from exc
    if start > end:
        raise HTTPException(422, "start_time 不能晚于 end_time")
    return start, end


class SolutionMCP(FastApiMCP):
    @asynccontextmanager
    async def lifespan(self):
        # fastapi-mcp 0.4 starts its HTTP transport lazily but does not register
        # shutdown hooks. Keep its cleanup here, separate from record persistence.
        if self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.fastapi, raise_app_exceptions=False),
                base_url="http://apiserver",
                timeout=10.0,
            )
        try:
            yield
        finally:
            try:
                if self._http_transport is not None:
                    await self._http_transport.shutdown()
            finally:
                await self._http_client.aclose()


def create_solution_mcp(
    app: FastAPI,
    *,
    get_solutions_dir: Callable[[], str],
    resolve_path: Callable[[str], str],
    read_report: Callable[[str], dict[str, str]],
    get_submissions: Callable[[str | None], list[dict[str, Any]]],
    get_ledger_store: Callable[[], LedgerStore],
) -> SolutionMCP:
    # This app is used only by the adapter's in-process ASGI client. Its query
    # routes are not mounted publicly and cannot expose existing write APIs.
    queries = FastAPI(title="MMPFP MCP 查询与证据库", docs_url=None, redoc_url=None)

    @queries.get("/reports", operation_id="list_solution_reports")
    def list_solution_reports(
        start_time: Annotated[OptionalQueryTime, Query(
            description="时间窗口下界（含），ISO 8601；省略表示不限。无时区时按服务器本地时间。",
        )] = None,
        end_time: Annotated[OptionalQueryTime, Query(
            description="时间窗口上界（含），ISO 8601；省略表示当前时间。无时区时按服务器本地时间。",
        )] = None,
        order: Annotated[Literal["desc", "asc"], Query(
            description="desc 从新到旧，asc 从旧到新；相同时间按相对路径升序。",
        )] = "desc",
        limit: Annotated[int, Query(ge=1, le=1000, description="最多返回的报告数量")] = 10,
        time_field: Annotated[Literal["created", "modified"], Query(
            description="created 按文件创建时间（与前端一致）；modified 按最后修改时间。",
        )] = "created",
    ) -> list[str]:
        """按时间窗口递归查询解题报告，只返回相对于 SOLUTIONS_DIR 的路径列表。

        不传参数即“从现在向前查找，从新到旧，前 10 篇报告”。
        只包含 .md 文件，包含未标记完成的报告，忽略符号链接。
        路径使用 / 分隔，可直接传给 get_solution_report。
        created 使用 os.path.getctime；Windows 为创建时间，Unix 为元数据变更时间。
        """
        start, end = resolve_time_window(start_time, end_time)

        root = get_solutions_dir()
        reports: list[tuple[float, str]] = []

        def scan_error(exc: OSError):
            # A missing/just-deleted directory is an empty result, not a failure.
            if not isinstance(exc, FileNotFoundError):
                raise exc

        try:
            for directory, dirs, files in os.walk(root, followlinks=False, onerror=scan_error):
                allowed_dirs = []
                for name in dirs:
                    candidate = os.path.join(directory, name)
                    if os.path.islink(candidate) or getattr(os.path, "isjunction", lambda _: False)(candidate):
                        continue
                    try:
                        resolve_path(os.path.relpath(candidate, root))
                    except HTTPException:
                        continue
                    allowed_dirs.append(name)
                dirs[:] = allowed_dirs
                for name in files:
                    if not name.endswith(".md"):
                        continue
                    relative = os.path.relpath(os.path.join(directory, name), root).replace("\\", "/")
                    try:
                        full_path = resolve_path(relative)
                        if not os.path.isfile(full_path):
                            continue
                        timestamp = (os.path.getctime(full_path) if time_field == "created"
                                     else os.path.getmtime(full_path))
                    except (FileNotFoundError, HTTPException):
                        # Files may disappear while the web editor updates the tree.
                        continue
                    if start <= timestamp <= end:
                        reports.append((timestamp, relative))
        except OSError as exc:
            logger.exception("MCP 查询解题报告失败")
            raise HTTPException(500, "无法读取解题报告目录") from exc

        reports.sort(key=lambda item: (-item[0] if order == "desc" else item[0], item[1]))
        return [relative for _, relative in reports[:limit]]

    @queries.get("/report", operation_id="get_solution_report", response_model=ReportContent)
    def get_solution_report(
        relative_path: Annotated[str, Query(
            min_length=1, max_length=500,
            description="相对于 SOLUTIONS_DIR 的报告路径，例如 math/P1001.md；可省略 .md。",
        )],
    ) -> dict[str, str]:
        """读取一篇解题报告的完整内容，返回 {content: Markdown 文本}。

        路径可来自 list_solution_reports。只读取报告目录内的 Markdown 文件，
        不允许绝对路径、..、符号链接或 Windows 备用数据流路径。
        """
        relative_path = relative_path.replace("\\", "/")
        if (relative_path.startswith("/") or ntpath.splitdrive(relative_path)[0]
                or ":" in relative_path or "\x00" in relative_path
                or ".." in relative_path.split("/")):
            raise HTTPException(400, "必须提供报告目录内的相对路径")
        if not relative_path.endswith(".md"):
            relative_path += ".md"
        full_path = resolve_path(relative_path)
        if not os.path.isfile(full_path):
            raise HTTPException(404, "报告文件不存在")
        try:
            return read_report(relative_path)
        except UnicodeError as exc:
            raise HTTPException(422, "报告文件不是有效的 UTF-8 文本") from exc

    @queries.get("/submissions", operation_id="get_problem_submissions", response_model=list[Submission])
    def get_problem_submissions(
        pid: Annotated[str, Query(
            min_length=1, max_length=200,
            description="精确匹配采集记录中的题号（含平台标识），如 P1001、Qoj123、Cf123A、Atcoderabc001_1。",
        )],
    ) -> list[dict[str, Any]]:
        """获取某道题的所有本地提交记录（包括通过和未通过），按提交时间从新到旧排序。

        每条记录包含 time（Unix 秒）、status（是否通过）、pid（题号）、rid（提交 ID）。
        只查询当前服务已采集的记录，不请求在线评测网站；无匹配时返回空列表。
        """
        return sorted(get_submissions(pid), key=lambda record: (-record["time"], record["rid"]))

    @queries.get("/submissions/by-time", operation_id="get_submissions_by_time", response_model=list[Submission])
    def get_submissions_by_time(
        start_time: Annotated[OptionalQueryTime, Query(
            description="提交时间窗口下界（含），ISO 8601；省略表示不限。无时区时按服务器本地时间。",
        )] = None,
        end_time: Annotated[OptionalQueryTime, Query(
            description="提交时间窗口上界（含），ISO 8601；省略表示当前时间。无时区时按服务器本地时间。",
        )] = None,
        order: Annotated[Literal["desc", "asc"], Query(
            description="desc 从新到旧，asc 从旧到新；相同时间按提交 ID 升序。",
        )] = "desc",
        limit: Annotated[int, Query(ge=1, le=1000, description="最多返回的提交记录数量")] = 10,
        offset: Annotated[int, Query(ge=0, description="筛选并排序后跳过的记录数量，用于分页")] = 0,
    ) -> list[dict[str, Any]]:
        """根据时间窗口获取所有题目的本地提交记录，按记录的 time 字段筛选。

        不传参数即返回截至现在、从新到旧的最近 10 条提交，包含通过和未通过的记录。
        每条包含 time（Unix 秒）、status（是否通过）、pid（题号）、rid（提交 ID）。
        时间窗口两端均包含，无匹配时返回空列表。记录超过 limit 时可递增 offset 分页；
        翻页时建议固定 end_time，避免新提交导致分页位置变化。不请求在线评测网站。
        """
        start, end = resolve_time_window(start_time, end_time)
        records = [record for record in get_submissions(None) if start <= record["time"] <= end]
        records.sort(key=lambda record: (
            -record["time"] if order == "desc" else record["time"], record["rid"],
        ))
        return records[offset:offset + limit]

    # 账本路由与上面的查询路由注册在同一个内部 app 上，因此合成一个 /mcp server。
    register_ledger_routes(queries, get_store=get_ledger_store)

    server = SolutionMCP(
        queries,
        name="MMPFP Solutions",
        description="解题报告与本地提交记录查询，以及能力证据库的读写工具",
        include_operations=TOOL_NAMES,
        describe_full_response_schema=True,
    )
    for tool in server.tools:
        if tool.name not in READ_ONLY_QUERY_NAMES:
            continue
        if tool.name in {"list_solution_reports", "get_submissions_by_time"}:
            # fastapi-mcp 0.4 flattens nullable query schemas to strings. Restore
            # null so clients can explicitly request the default time bounds.
            for field in ("start_time", "end_time"):
                tool.inputSchema["properties"][field]["type"] = ["string", "null"]
        tool.annotations = ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False,
        )
    # 账本工具：读的标只读，写的标非只读（ledger_unlink 另标 destructive）。
    enrich_ledger_tools(server)
    server.mount_http(app, mount_path="/mcp")
    return server
