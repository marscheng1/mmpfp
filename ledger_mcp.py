"""能力证据库的 MCP 接口：只维护 fact + link 数据库。

**只读边界（需求 §10 开放决策 1，(a) 方案）**：账本工具与原有的四个只读查询挂在
**同一个** `/mcp` server 上，客户端一次连接即可。区分靠 tool annotations——
`ledger_search` / `ledger_get_fact` 标 `readOnlyHint=True`，三个写工具标
`readOnlyHint=False`，其中 `ledger_unlink` 额外标 `destructiveHint=True`，避免把
删除伪装成幂等写。这取代了 README 早先「`/mcp` 只提供四个只读工具」的表述；
现在承诺的粒度是**每个工具的 annotation**。

**不做能力画像，也不做引用校验。**这里没有、也不会有能力画像 / 样本数 / rating /
强度派生 / 辅助计数政策核查 / 引用校验之类的工具——账本只如实返回已写入的 fact
与 link，怎么用它由使用方决定。

**`id` 完全由服务端分配（需求 §10 开放决策 3）**：`ledger_add_fact` 不接受
调用方传入 `id`（传了报 422），服务端按 `EV-YYYYMMDD-NN` 生成并返回。
需要沿用历史报告编号（如 `EV-R17-01`）的迁移/回填走 `LedgerStore.add_fact()`
这一内部接口，不经过 MCP 写面。

**不设二次确认（需求 §10 开放决策 2）**：写工具无 `confirm` 参数，调用即落盘。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Literal

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi_mcp import FastApiMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field

from ledger import (
    DIFFICULTY_MAX, DIFFICULTY_MIN, EFFECTS, INDEPENDENCE_LEVELS, ROLES, Fact,
    LedgerError, LedgerStore, Link, parse_date_argument, resolve_skill_id,
)

logger = logging.getLogger(__name__)

#: 账本工具名；与原 `/mcp` 的四个只读查询合并成同一个 server 的工具集。
TOOL_NAMES = [
    "ledger_add_fact", "ledger_link", "ledger_unlink", "ledger_search",
    "ledger_get_fact",
]

#: 读工具：真正只读，可以安全重试。
READ_ONLY_TOOLS = {"ledger_search", "ledger_get_fact"}
#: 只读且幂等（同参数重复调用结果相同）。
IDEMPOTENT_TOOLS = {"ledger_search", "ledger_get_fact"}
#: 会移除已冻结判断的工具，标 destructive。
DESTRUCTIVE_TOOLS = {"ledger_unlink"}

_MAX_LIMIT = 1000


def _translate(exc: LedgerError) -> HTTPException:
    return HTTPException(422, str(exc))


# --------------------------------------------------------------------------- #
# 请求模型
# --------------------------------------------------------------------------- #

class FactInput(BaseModel):
    """`ledger_add_fact` 的 fact 入参。

    字段与 `ledger.Fact` 一致，但**没有 `id`**——id 由服务端分配。这里显式声明而非
    用裸 dict，让 MCP 客户端能看到各字段的枚举与说明。
    """

    model_config = ConfigDict(extra="forbid")

    pid: str = Field(min_length=1, max_length=200,
                     description="与 records.json 的 pid 完全一致")
    date: str = Field(description="观察日期 YYYY-MM-DD")
    phase: Literal["独立", "题解后", "赛后", "学习"] = Field(description="阶段")
    independence: Literal["I0", "I1", "I2",
                          "I3", "I4"] = Field(description="独立程度")
    difficulty: int | None = Field(
        default=None,
        description=("题目难度（整数，通常为 CF 等效 rating，如 2500）。"
                     "尚未核定时传 null；同一题的不同阶段可以不同。"))
    result: Literal["AC", "未成解", "TLE", "部分分", "未实现", "仅思路"] = Field(
        description="结果")
    source_ref: str = Field(
        min_length=3, max_length=500,
        description="可定位原文，例如 article/solutions/CF1665E.md:17")
    supersedes: str | None = Field(
        default=None, description="若本条是对旧事实的修正，填旧 id")
    note: str = Field(default="", max_length=2000,
                      description="自由文本；不得写派生数字")


class FactRequest(BaseModel):
    """`ledger_add_fact` 的参数。`fact` 里不要带 id，由服务端分配。"""

    fact: FactInput = Field(description="Fact 对象（§4）；id 由服务端分配，不要传")


class LinkRequest(BaseModel):
    fact_id: str
    skill_id: str
    role: str
    effect: str
    why: str
    created: str | None = Field(
        default=None, description="写入日期 YYYY-MM-DD；省略取今天")


class UnlinkRequest(BaseModel):
    fact_id: str
    skill_id: str


class AddFactResponse(BaseModel):
    id: str = Field(description="服务端分配的 Fact id")
    created_new: bool = True


class OkResponse(BaseModel):
    ok: bool = True
    detail: str = ""


# --------------------------------------------------------------------------- #
# 路由注册（挂到与原只读查询同一个内部 app 上）
# --------------------------------------------------------------------------- #

def register_ledger_routes(
    queries: FastAPI,
    *,
    get_store: Callable[[], LedgerStore],
) -> None:
    """把账本的 5 个路由注册到给定的内部查询 app 上。

    调用方随后用一个 `FastApiMCP(queries, include_operations=...)` 同时发布
    原只读查询与账本工具，即需求 §10 决策 1 的 (a) 方案。
    """

    # ---- 读工具 ---------------------------------------------------------- #

    @queries.get("/ledger/search", operation_id="ledger_search")
    def ledger_search(
        skill_id: str = Query(
            min_length=1, max_length=64,
            description="协议 A/B/C 编号（§3），或报告中的显示名，如 B2 / Observation"),
        role: str | None = Query(
            default=None, description="core | auxiliary | out；省略表示不限"),
        effect: str | None = Query(
            default=None, description="positive | negative | boundary；省略表示不限"),
        independence: list[str] | None = Query(
            default=None, description="独立性筛选，可多值：I0|I1|I2|I3|I4"),
        difficulty: list[int] | None = Query(
            default=None,
            description=("难度精确筛选，可多值（逗号分隔或重复参数），命中任一即返回。"
                         "取的是该 Link 所属 Fact 的 difficulty；"
                         "difficulty 为 null 的 Fact 不会被命中。")),
        difficulty_min: int | None = Query(
            default=None, ge=DIFFICULTY_MIN, le=DIFFICULTY_MAX,
            description=("难度区间下界（含）。只给下界表示“≥ 下界”；"
                         "与 difficulty_max 同时给出时必须 ≤ 它。"
                         "Fact 的 difficulty 为 null 时不会命中区间筛选。")),
        difficulty_max: int | None = Query(
            default=None, ge=DIFFICULTY_MIN, le=DIFFICULTY_MAX,
            description=("难度区间上界（含）。只给上界表示“≤ 上界”；"
                         "与 difficulty 同时给出时是“与”关系。")),
        start_date: str | None = Query(
            default=None, description="观察日期下界（含），YYYY-MM-DD"),
        end_date: str | None = Query(
            default=None, description="观察日期上界（含），YYYY-MM-DD"),
        limit: int | None = Query(
            default=None, ge=1, le=_MAX_LIMIT, description="最多返回条数"),
    ) -> list[dict[str, object]]:
        """按能力反查支持证据（R3），返回 Fact 与 Link 的合并行。

        每行含 `why`（该 Link 的资格理由）、`source_ref`（可定位原文）与 `difficulty`
        （取自所属 Fact）。同一 Fact 可挂多项能力，按 skill 过滤后逐条列出。
        被取代（`superseded`）的 Fact 仍可读出，但退出判断，不应计入样本。

        **难度筛选（本工具的完整口径）**

        * `difficulty`：精确匹配，多值之间是“或”，如 `difficulty=1500,2500`。
        * `difficulty_min` / `difficulty_max`：闭区间，两端**都可单独省略**——
          只给下界即“≥ 下界”，只给上界即“≤ 上界”。
        * Link 本身没有难度字段：以上三者筛的都是该 Link **所属 Fact** 的难度。
        * `difficulty` 与区间**同时给出时取交集**（既落在区间内，又属于给定取值）。
        * `difficulty` 为 `null`（尚未核定）的事实**不参与任何难度筛选**：null 与具体
          难度不可比，不能因为“不满足 >2500”就把它当作低难度返回。
        * 上下界颠倒（`min > max`）、非整数或超出 0–8000 都作为调用错误返回，
          而不是静默给出空结果。
        """
        try:
            return get_store().search(
                skill_id=skill_id, role=role, effect=effect,
                independence=list(independence) if independence else None,
                difficulty=list(difficulty) if difficulty else None,
                difficulty_min=difficulty_min, difficulty_max=difficulty_max,
                start_date=start_date, end_date=end_date, limit=limit)
        except LedgerError as exc:
            raise _translate(exc) from exc

    @queries.get("/ledger/fact", operation_id="ledger_get_fact")
    def ledger_get_fact(
        fact_id: str = Query(min_length=3, max_length=64,
                             description="Fact id"),
    ) -> dict[str, object]:
        """按 id 取单条 Fact（含全部 Links）。被取代的 Fact 仍可读，并给出 replaced_by。"""
        entry = get_store().get_fact(fact_id)
        if entry is None:
            raise HTTPException(404, f"Fact 不存在：{fact_id}")
        return entry

    # ---- 写工具 ---------------------------------------------------------- #

    @queries.post("/ledger/facts", operation_id="ledger_add_fact",
                  response_model=AddFactResponse)
    def ledger_add_fact(request: FactRequest = Body()) -> dict[str, object]:
        """写入一条原子事实（R1），返回服务端分配的 id。

        **字段口径**（`fact` 入参）

        * `difficulty`：整数，题目难度（通常为 CF 等效 rating，如 2500）；尚未核定写
          `null`。`null` 不是 0，且**不参与任何难度筛选**（精确值与区间都取不到）；
          同一题的不同阶段可以给不同值。
        * `independence`：`I0`–`I4`，独立性等级。
        * `role` / `effect` 不在这里——它们属于 Link，见 `ledger_link`。

        `id` 完全由服务端分配（`EV-YYYYMMDD-NN`），入参里没有这个字段；已存在的 id
        一律拒绝，绝不覆盖。Fact 模型 `extra=forbid`，rating / 样本数等派生字段
        不存在即被拒（§8.2）。
        """
        store = get_store()
        payload = request.fact.model_dump()
        payload["id"] = store.next_fact_id()
        try:
            fact = Fact.model_validate(payload)
            return {"id": store.add_fact(fact), "created_new": True}
        except LedgerError as exc:
            raise _translate(exc) from exc
        except Exception as exc:  # pydantic ValidationError
            raise HTTPException(422, f"Fact 不合法：{exc}") from exc

    @queries.post("/ledger/links", operation_id="ledger_link",
                  response_model=OkResponse)
    def ledger_link(request: LinkRequest = Body()) -> dict[str, object]:
        """记录“某 Fact 以什么资格支撑哪项能力”（R2）。

        `role`（`core` / `auxiliary` / `out`）与 `effect`（`positive` / `negative` /
        `boundary`）必须在写入那一刻冻结；`why` 必填且非空，且必须是该条观察专有的
        理由（不是记录位置、不是恒真套话）。同一 Fact × skill 只能有一条 Link。
        拒绝不存在的 fact_id、清单外的 skill_id、已 superseded 的 Fact，以及重复 Link。
        """
        store = get_store()
        created = parse_date_argument(request.created) or _today()
        try:
            link = Link.model_validate({
                "fact_id": request.fact_id,
                "skill_id": request.skill_id,
                "role": request.role,
                "effect": request.effect,
                "why": request.why,
                "created": created,
            })
            store.add_link(link)
        except LedgerError as exc:
            raise _translate(exc) from exc
        except Exception as exc:
            raise HTTPException(422, f"Link 不合法：{exc}") from exc
        return {"ok": True, "detail": f"{link.fact_id} × {link.skill_id} ({link.role})"}

    @queries.post("/ledger/unlink", operation_id="ledger_unlink",
                  response_model=OkResponse)
    def ledger_unlink(request: UnlinkRequest = Body()) -> dict[str, object]:
        """撤销一条 Link。事实本身保留；被撤销的 Link 不再参与判断。"""
        store = get_store()
        try:
            removed = store.remove_link(request.fact_id, request.skill_id)
        except LedgerError as exc:
            raise _translate(exc) from exc
        if not removed:
            raise HTTPException(
                404, f"Link 不存在：{request.fact_id} × {request.skill_id}")
        return {"ok": True, "detail": f"removed {request.fact_id} × {request.skill_id}"}


# --------------------------------------------------------------------------- #
# 工具标注与 schema 修正
# --------------------------------------------------------------------------- #

def enrich_ledger_tools(server: FastApiMCP) -> None:
    """给合并后的 server 上的账本工具补 annotation 与数组 schema。

    只读工具标只读；写工具标非只读，`ledger_unlink` 标 destructive。
    """
    for tool in server.tools:
        if tool.name not in TOOL_NAMES:
            continue
        tool.annotations = ToolAnnotations(
            readOnlyHint=tool.name in READ_ONLY_TOOLS,
            destructiveHint=tool.name in DESTRUCTIVE_TOOLS,
            idempotentHint=tool.name in IDEMPOTENT_TOOLS,
            openWorldHint=False,
        )
        if tool.name == "ledger_search":
            _widen_list(tool, "independence", "string")
            _widen_list(tool, "difficulty", "integer")


def _widen_list(tool: Any, field: str, item_type: str) -> None:
    """fastapi-mcp 0.4 会把可空列表查询展平成字符串；补回数组形态。"""
    properties = tool.inputSchema.get("properties", {})
    if field in properties:
        properties[field] = {
            "anyOf": [
                {"type": "array", "items": {"type": item_type}},
                {"type": "null"},
            ],
            "description": properties[field].get("description", ""),
        }


def _today() -> str:
    from datetime import date

    return date.today().isoformat()


# 供 FastAPI 直接复用的常量，避免调用方各自硬编码枚举。
__all__ = [
    "EFFECTS", "INDEPENDENCE_LEVELS", "ROLES", "TOOL_NAMES",
    "enrich_ledger_tools", "register_ledger_routes", "resolve_skill_id",
]
