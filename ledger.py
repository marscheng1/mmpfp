"""能力证据库（Evidence Ledger）核心实现。

范围：**只维护 fact + link 数据库。**

* 持久化**原子事实**（Fact：一次可定位的观察）与 Link（“该事实以什么资格支撑
  哪项能力”的冻结判断，同一事实可挂多项能力）。
* 提供按能力反查（`search`）与按 id 取单条（`get_fact`）。
* 失效管理（R6）：旧 Fact 可被后续修正 Fact 标记 `superseded`，它退出判断但保持
  可读，因此不会重复计数。

**不做能力画像，也不做引用校验。**样本数、Ability Rating、Plausible Range、
Confidence、证据强度都不在账本里，也没有任何能力画像 / 强度派生 / 对账 /
政策核查逻辑——那些属于教练侧报告。引用是否正确同样不在这里判断：账本只如实返回
已写入的 fact 与 link，核对由使用方完成。

写入复用 `main.save_records_sync()` 的原子模式：同目录临时文件 → flush + fsync →
`os.replace`，并用 `threading.RLock` 串行化。写入前做完整校验：重复 id、未知
skill_id、`superseded` 事实、空 `why`、非法枚举值全部拒绝；模型
`extra="forbid"`，任何派生字段（rating、样本数……）都会因字段不存在被拒。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, Iterator, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# --------------------------------------------------------------------------- #
# 枚举（§3 / §4 / §5.1）
# --------------------------------------------------------------------------- #

Phase = Literal["独立", "题解后", "赛后", "学习"]
Independence = Literal["I0", "I1", "I2", "I3", "I4"]
Result = Literal["AC", "未成解", "TLE", "部分分", "未实现", "仅思路"]
Role = Literal["core", "auxiliary", "out"]
Effect = Literal["positive", "negative", "boundary"]

PHASES: tuple[str, ...] = ("独立", "题解后", "赛后", "学习")
INDEPENDENCE_LEVELS: tuple[str, ...] = ("I0", "I1", "I2", "I3", "I4")
RESULTS: tuple[str, ...] = ("AC", "未成解", "TLE", "部分分", "未实现", "仅思路")
ROLES: tuple[str, ...] = ("core", "auxiliary", "out")
EFFECTS: tuple[str, ...] = ("positive", "negative", "boundary")

#: difficulty 的合法区间；它存在 Fact 上，Link 通过所属 Fact 继承。
DIFFICULTY_MIN = 0
DIFFICULTY_MAX = 8000

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FACT_ID_PATTERN = re.compile(r"^EV-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$")
SOURCE_REF_PATTERN = re.compile(r"^[^:]+:\d+$")


class LedgerError(ValueError):
    """账本校验失败。调用方应把它转成 4xx / MCP 工具错误。"""


# --------------------------------------------------------------------------- #
# 能力标识（§3，必须先冻结）
# --------------------------------------------------------------------------- #

class Skill:
    __slots__ = ("skill_id", "protocol_name", "display_name", "aliases")

    def __init__(self, skill_id: str, protocol_name: str, display_name: str,
                 aliases: tuple[str, ...] = ()) -> None:
        self.skill_id = skill_id
        self.protocol_name = protocol_name
        self.display_name = display_name
        self.aliases = aliases


#: 19 项能力，编号即协议 `0.Protocol.md` 的 A/B/C 编号，显示名只作别名。
#: 账本只冻结「哪条事实支撑哪项能力」，不维护这些能力的 rating 或样本数。
SKILLS: tuple[Skill, ...] = (
    Skill("A1", "数据结构", "Data Structure"),
    Skill("A2", "动态规划", "DP", ("Dynamic Programming",)),
    Skill("A3", "图论", "Graph"),
    Skill("A4", "数学与组合", "Math", ("Mathematics",)),
    Skill("A5", "字符串", "String"),
    Skill("B1", "读题与信息提取", "Reading"),
    Skill("B2", "观察与性质发现", "Observation"),
    Skill("B3", "建模", "Modeling"),
    Skill("B4", "算法设计", "Algorithm Design"),
    Skill("B5", "复杂度分析", "Complexity"),
    Skill("B6", "正确性证明", "Proof", ("Correctness",)),
    Skill("B7", "反例构造", "Counterexample"),
    Skill("B8", "思维收敛", "Convergence", ("Convergence (B8)",)),
    Skill("C1", "暴力与部分分", "Brute Force"),
    Skill("C2", "实现", "Implementation"),
    Skill("C3", "调试", "Debugging"),
    Skill("C4", "边界意识", "Boundary", ("Boundary (C4)",)),
    Skill("C5", "独立性", "Independence", ("Independence (C5)",)),
    Skill("C6", "陌生题迁移", "Transfer"),
)

SKILL_BY_ID: dict[str, Skill] = {skill.skill_id: skill for skill in SKILLS}
SKILL_IDS: tuple[str, ...] = tuple(skill.skill_id for skill in SKILLS)


def resolve_skill_id(value: str) -> str:
    """接受 skill_id 或报告中的显示名/别名，返回冻结的 skill_id。"""
    if value in SKILL_BY_ID:
        return value
    for skill in SKILLS:
        if value == skill.display_name or value in skill.aliases:
            return skill.skill_id
    raise LedgerError(
        f"未知 skill_id：{value!r}；合法取值为 {'、'.join(SKILL_IDS)}（或报告显示名）"
    )


# --------------------------------------------------------------------------- #
# 数据模型（§4）
# --------------------------------------------------------------------------- #

def _validate_date(value: str) -> str:
    if not isinstance(value, str) or not DATE_PATTERN.match(value):
        raise LedgerError(f"日期必须是 YYYY-MM-DD：{value!r}")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise LedgerError(f"日期无效：{value!r}") from exc
    return value


class Fact(BaseModel):
    """一条可定位的原子观察。字段即全部事实，不含任何派生数字。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=3, max_length=64,
                    description="稳定 ID，全局唯一，分配后永不改")
    pid: str = Field(min_length=1, max_length=200,
                     description="与 records.json 的 pid 完全一致")
    date: str = Field(description="观察日期，YYYY-MM-DD")
    phase: Phase = Field(description="独立 | 题解后 | 赛后 | 学习")
    independence: Independence = Field(description="I0|I1|I2|I3|I4")
    difficulty: int | None = Field(
        default=None,
        description=("题目难度（int，通常为 CF 等效 rating，如 2500）。"
                     "尚未核定时为 null；同一题的不同阶段可以不同。"))
    result: Result = Field(description="AC | 未成解 | TLE | 部分分 | 未实现 | 仅思路")
    source_ref: str = Field(
        min_length=3, max_length=500,
        description="可定位原文，例如 article/solutions/CF1665E.md:17")
    supersedes: str | None = Field(
        default=None, description="若本条是对旧事实的修正，填旧 id")
    note: str = Field(default="", max_length=2000,
                      description="自由文本；不得写派生数字")
    #: 派生状态，不是事实：由是否存在 `supersedes == id` 的修正 Fact 推出。
    #: 被取代的 Fact 仍可读，但退出判断，因此不会重复计数（R6）。
    superseded: bool = Field(
        default=False, description="（派生）已被后续修正 Fact 取代，退出判断")

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        if not FACT_ID_PATTERN.match(value):
            raise LedgerError(
                f"id 必须形如 EV-R17-08（字母数字分段）：{value!r}")
        return value

    @field_validator("date")
    @classmethod
    def _check_date(cls, value: str) -> str:
        return _validate_date(value)

    @field_validator("source_ref")
    @classmethod
    def _check_source_ref(cls, value: str) -> str:
        if not SOURCE_REF_PATTERN.match(value):
            raise LedgerError(
                f"source_ref 必须带可定位行号，例如 article/x.md:17：{value!r}")
        return value

    @field_validator("difficulty", mode="before")
    @classmethod
    def _check_difficulty(cls, value: object) -> object:
        """difficulty 必须是真正的 int 或 null。

        这里用 `mode="before"` 并显式检查类型：pydantic 的宽松模式会把 `True`
        当成 1 放过去，而难度写成一个布尔值显然是调用错误。
        """
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise LedgerError(f"difficulty 必须是整数或 null：{value!r}")
        return _check_difficulty_range(value)

    @field_validator("note")
    @classmethod
    def _check_note(cls, value: str) -> str:
        if re.search(r"\b\d+\s*(个)?样本|rating|置信度", value, re.IGNORECASE):
            raise LedgerError("note 不得写入派生数字（样本数、rating、置信度）")
        return value


class Link(BaseModel):
    """某条 Fact 以什么资格支撑哪项能力的**冻结判断**。"""

    model_config = ConfigDict(extra="forbid")

    fact_id: str = Field(min_length=3, max_length=64)
    skill_id: str = Field(description="协议 A/B/C 编号，见 §3 清单")
    role: Role = Field(description="core（核心样本）| auxiliary（辅助观察）| out（不参与评分）")
    effect: Effect = Field(description="positive | negative | boundary")
    why: str = Field(min_length=1, max_length=2000,
                     description="必填理由；资格漂移的唯一锚点")
    created: str = Field(description="写入日期，YYYY-MM-DD")

    @field_validator("skill_id")
    @classmethod
    def _check_skill(cls, value: str) -> str:
        return resolve_skill_id(value)

    @field_validator("why")
    @classmethod
    def _check_why(cls, value: str) -> str:
        if not value or not value.strip():
            raise LedgerError("why 不能为空；它是防止资格漂移的唯一锚点")
        return value.strip()

    @field_validator("created")
    @classmethod
    def _check_created(cls, value: str) -> str:
        return _validate_date(value)


# --------------------------------------------------------------------------- #
# JSON 读写（§7.2 原子写入）
# --------------------------------------------------------------------------- #

FILE_LOCK = threading.RLock()


def _read_json_array(file_path: str, label: str) -> list[dict[str, Any]]:
    if not os.path.exists(file_path):
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise LedgerError(f"无法读取 {label}（{file_path}）：{exc}") from exc
    if not isinstance(raw, list):
        raise LedgerError(f"{label} 必须是 JSON 数组：{file_path}")
    return raw


def write_json_atomic(file_path: str, payload: Any) -> None:
    """与 records.json 相同的原子写入：临时文件 → fsync → os.replace。"""
    directory = os.path.dirname(os.path.abspath(file_path)) or "."
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary_file = tempfile.mkstemp(
        dir=directory, prefix=os.path.basename(file_path) + ".", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_file, file_path)
    finally:
        if os.path.exists(temporary_file):
            os.remove(temporary_file)


# --------------------------------------------------------------------------- #
# 账本存储
# --------------------------------------------------------------------------- #

def _dump_fact(fact: Fact) -> dict[str, Any]:
    """序列化 Fact，剔除派生状态，保证落盘文件只含原子事实。"""
    payload = fact.model_dump()
    payload.pop("superseded", None)
    return payload


class LedgerStore:
    """两个平面文件：facts.json（原子事实）与 ledger-links.json（资格判断）。"""

    def __init__(self, facts_file: str, links_file: str) -> None:
        self.facts_file = facts_file
        self.links_file = links_file

    # ---- 读取 ---------------------------------------------------------- #

    def read_facts(self) -> list[Fact]:
        with FILE_LOCK:
            raw = _read_json_array(self.facts_file, "facts.json")
        facts: list[Fact] = []
        for index, item in enumerate(raw):
            try:
                facts.append(Fact.model_validate(item))
            except Exception as exc:  # pydantic ValidationError / LedgerError
                raise LedgerError(
                    f"facts.json 第 {index + 1} 条不合法：{exc}") from exc
        # `superseded` 由文件内容现算，不落盘（§6.4）。
        superseded = {fact.supersedes for fact in facts if fact.supersedes}
        for fact in facts:
            fact.superseded = fact.id in superseded
        return facts

    def read_links(self) -> list[Link]:
        with FILE_LOCK:
            raw = _read_json_array(self.links_file, "ledger-links.json")
        links: list[Link] = []
        for index, item in enumerate(raw):
            try:
                links.append(Link.model_validate(item))
            except Exception as exc:
                raise LedgerError(
                    f"ledger-links.json 第 {index + 1} 条不合法：{exc}") from exc
        return links

    def find_fact(self, fact_id: str) -> Fact | None:
        for fact in self.read_facts():
            if fact.id == fact_id:
                return fact
        return None

    # ---- 写入 ---------------------------------------------------------- #

    def add_fact(self, fact: Fact) -> str:
        """写入一条 Fact。重复 id 一律拒绝，绝不覆盖。"""
        with FILE_LOCK:
            existing = self.read_facts()
            if any(item.id == fact.id for item in existing):
                raise LedgerError(f"Fact id 已存在，不允许覆盖：{fact.id}")
            if fact.supersedes:
                if fact.supersedes == fact.id:
                    raise LedgerError("supersedes 不能指向自身")
                target = next((item for item in existing
                               if item.id == fact.supersedes), None)
                if target is None:
                    raise LedgerError(f"supersedes 指向不存在的 Fact：{fact.supersedes}")
                if any(item.supersedes == fact.id for item in existing):
                    raise LedgerError(f"{fact.id} 已被别的 Fact 取代，不能再写入")
            payload = [_dump_fact(item) for item in existing]
            payload.append(_dump_fact(fact))
            write_json_atomic(self.facts_file, payload)
        return fact.id

    def supersede(self, fact_id: str, *, reason: str, created: str) -> tuple[str, str]:
        """把旧 Fact 标记为 `superseded`：写一条修正 Fact，由它 `supersedes` 旧 id。

        旧 Fact 保持可读但退出判断，因此不会重复计数。
        """
        if not reason or not reason.strip():
            raise LedgerError("修正必须给出 reason")
        created = _validate_date(created)
        with FILE_LOCK:
            facts = self.read_facts()
            old = next((item for item in facts if item.id == fact_id), None)
            if old is None:
                raise LedgerError(f"Fact 不存在：{fact_id}")
            if old.superseded:
                raise LedgerError(f"Fact 已被取代，无需重复取代：{fact_id}")
            replacement_id = self._next_correction_id(old.id, facts)
            replacement = Fact(
                id=replacement_id, pid=old.pid, date=created, phase=old.phase,
                independence=old.independence, difficulty=old.difficulty,
                result=old.result, source_ref=old.source_ref,
                supersedes=fact_id, note=reason.strip())
            self.add_fact(replacement)
        return fact_id, replacement_id

    @staticmethod
    def _next_correction_id(old_id: str, facts: list[Fact]) -> str:
        prefix = f"{old_id}-C"
        used = {item.id for item in facts}
        index = 1
        while f"{prefix}{index}" in used:
            index += 1
        return f"{prefix}{index}"

    def add_link(self, link: Link) -> None:
        """新增 Link。重复、未知 skill、superseded 事实、空 why 全部拒绝。"""
        with FILE_LOCK:
            facts = self.read_facts()
            fact = next((item for item in facts if item.id == link.fact_id), None)
            if fact is None:
                raise LedgerError(f"fact_id 不存在：{link.fact_id}")
            if fact.superseded:
                raise LedgerError(
                    f"Fact 已被取代（superseded），不得新增 Link：{link.fact_id}")
            links = self.read_links()
            if any(item.fact_id == link.fact_id and item.skill_id == link.skill_id
                   for item in links):
                raise LedgerError(
                    f"Link 已存在：{link.fact_id} × {link.skill_id}")
            payload = [item.model_dump() for item in links]
            payload.append(link.model_dump())
            write_json_atomic(self.links_file, payload)

    def remove_link(self, fact_id: str, skill_id: str) -> bool:
        with FILE_LOCK:
            skill_id = resolve_skill_id(skill_id)
            links = self.read_links()
            kept = [item for item in links
                    if not (item.fact_id == fact_id and item.skill_id == skill_id)]
            if len(kept) == len(links):
                return False
            write_json_atomic(self.links_file,
                              [item.model_dump() for item in kept])
            return True

    def next_fact_id(self, prefix: str | None = None) -> str:
        """服务生成稳定 ID：EV-YYYYMMDD-NN。调用方指定 id 时不会用到。"""
        stamp = prefix or datetime.now().strftime("%Y%m%d")
        with FILE_LOCK:
            used = {item.id for item in self.read_facts()}
        index = 1
        while f"EV-{stamp}-{index:02d}" in used:
            index += 1
        return f"EV-{stamp}-{index:02d}"

    # ---- 检索（R3） ----------------------------------------------------- #

    def search(self, *, skill_id: str, role: Role | None = None,
               effect: Effect | None = None,
               independence: list[str] | None = None,
               difficulty: list[int] | None = None,
               difficulty_min: int | None = None,
               difficulty_max: int | None = None,
               start_date: str | None = None, end_date: str | None = None,
               limit: int | None = None) -> list[dict[str, Any]]:
        """按能力反查 Link，并连带返回其所属 Fact。

        Link 没有自己的 difficulty——**筛选用的都是它所属 Fact 的 difficulty**。

        * `difficulty`：精确匹配，传多个值时表示“任一命中”（OR）。
        * `difficulty_min` / `difficulty_max`：闭区间，两端可单独给出；与 `difficulty`
          同时给出时是**与**关系（既要落在区间内，又要在给定取值里）。

        Fact 的 difficulty 为 `null`（尚未核定）时，**任何难度筛选都不会命中它**——
        null 与具体难度不可比，不能因为“不满足 >2500”就把它当低难度返回。
        """
        skill_id = resolve_skill_id(skill_id)
        if role is not None and role not in ROLES:
            raise LedgerError(f"role 非法：{role!r}；合法取值 {'、'.join(ROLES)}")
        if effect is not None and effect not in EFFECTS:
            raise LedgerError(f"effect 非法：{effect!r}；合法取值 {'、'.join(EFFECTS)}")
        if independence:
            for level in independence:
                if level not in INDEPENDENCE_LEVELS:
                    raise LedgerError(
                        f"independence 非法：{level!r}；合法取值 "
                        f"{'、'.join(INDEPENDENCE_LEVELS)}")
        wanted_difficulty = _normalise_difficulty_filter(difficulty)
        low, high = _normalise_difficulty_bounds(difficulty_min, difficulty_max)
        has_range = low is not None or high is not None
        if start_date is not None:
            _validate_date(start_date)
        if end_date is not None:
            _validate_date(end_date)
        if start_date and end_date and start_date > end_date:
            raise LedgerError("start_date 不能晚于 end_date")

        facts = {fact.id: fact for fact in self.read_facts()}
        rows: list[dict[str, Any]] = []
        for link in self.read_links():
            if link.skill_id != skill_id:
                continue
            fact = facts.get(link.fact_id)
            if fact is None:
                continue
            if role is not None and link.role != role:
                continue
            if effect is not None and link.effect != effect:
                continue
            if independence and fact.independence not in independence:
                continue
            if wanted_difficulty is not None and fact.difficulty not in wanted_difficulty:
                continue
            if has_range:
                # null 与任何区间都不可比，直接排除。
                if fact.difficulty is None:
                    continue
                if low is not None and fact.difficulty < low:
                    continue
                if high is not None and fact.difficulty > high:
                    continue
            if start_date and fact.date < start_date:
                continue
            if end_date and fact.date > end_date:
                continue
            rows.append({
                "fact_id": fact.id,
                "pid": fact.pid,
                "date": fact.date,
                "phase": fact.phase,
                "independence": fact.independence,
                "difficulty": fact.difficulty,
                "result": fact.result,
                "source_ref": fact.source_ref,
                "superseded": fact.superseded,
                "note": fact.note,
                "skill_id": link.skill_id,
                "skill_display": SKILL_BY_ID[link.skill_id].display_name,
                "role": link.role,
                "effect": link.effect,
                "why": link.why,
                "created": link.created,
                "counts_for_judgement": (link.role != "out"
                                         and not fact.superseded),
            })
        rows.sort(key=lambda row: (row["fact_id"], row["skill_id"]))
        if limit is not None:
            if limit < 1:
                raise LedgerError("limit 必须 ≥ 1")
            rows = rows[:limit]
        return rows

    def get_fact(self, fact_id: str) -> dict[str, Any] | None:
        facts = self.read_facts()
        fact = next((item for item in facts if item.id == fact_id), None)
        if fact is None:
            return None
        links = [link for link in self.read_links() if link.fact_id == fact_id]
        # 取代关系一次算出，避免重复读盘。
        replaced_by = next((item.id for item in facts if item.supersedes == fact_id), None)
        return {
            "fact": {**fact.model_dump(), "replaced_by": replaced_by},
            "links": [link.model_dump() for link in links],
            "replaced_by": replaced_by,
        }


def link_counts(link: Link) -> bool:
    """该 Link 是否是有资格参与判断的样本：`core` 或 `auxiliary`（`out` 不算）。"""
    return link.role in ("core", "auxiliary")


def _parse_difficulty_int(value: object, *, label: str) -> int:
    """把单个难度值解析成 int；数字字符串一并接受（HTTP query 只给字符串）。

    显式挡掉 `bool`：pydantic 的宽松模式会把 `True` 当 1，而难度写成布尔值显然是调用错误。
    """
    if isinstance(value, bool):
        raise LedgerError(f"{label} 必须是整数：{value!r}")
    if isinstance(value, str):
        text = value.strip()
        if not re.fullmatch(r"-?\d+", text):
            raise LedgerError(f"{label} 必须是整数：{value!r}")
        return _check_difficulty_range(int(text))
    if not isinstance(value, int):
        raise LedgerError(f"{label} 必须是整数：{value!r}")
    return _check_difficulty_range(value)


def _normalise_difficulty_filter(
        difficulty: list[int] | int | None) -> set[int] | None:
    """把 difficulty 精确筛选参数规整成集合；`None` 表示不筛选。

    接受 int、数字字符串、逗号分隔串与列表。注意单值 `None`（以及解析后为空）
    一律视为“不筛选”，因此**无法用它检索 difficulty 为 null 的事实**。
    """
    if difficulty is None:
        return None
    raw = difficulty if isinstance(difficulty, (list, tuple, set)) else [difficulty]
    wanted: set[int] = set()
    for item in raw:
        if item is None:
            continue
        if isinstance(item, str):
            # 逗号分隔串要全部取值，不能只看第一段。
            for piece in item.split(","):
                if piece.strip():
                    wanted.add(_parse_difficulty_int(piece, label="difficulty"))
            continue
        wanted.add(_parse_difficulty_int(item, label="difficulty"))
    return wanted or None


def _normalise_difficulty_bounds(
        difficulty_min: int | str | None,
        difficulty_max: int | str | None) -> tuple[int | None, int | None]:
    """规整难度区间下/上界，含两端。

    任一界可单独给出：只给下界即“≥ 下界”，只给上界即“≤ 上界”，两者都不给表示不筛。
    两端都给出时必须 `min <= max`，否则视为调用错误而不是返回空结果。
    """
    low = (None if difficulty_min is None
           else _parse_difficulty_int(difficulty_min, label="difficulty_min"))
    high = (None if difficulty_max is None
            else _parse_difficulty_int(difficulty_max, label="difficulty_max"))
    if low is not None and high is not None and low > high:
        raise LedgerError(
            f"difficulty_min 不能大于 difficulty_max：{low!r} > {high!r}")
    return low, high


def _check_difficulty_range(value: int) -> int:
    if not DIFFICULTY_MIN <= value <= DIFFICULTY_MAX:
        raise LedgerError(
            f"difficulty 必须在 {DIFFICULTY_MIN}–{DIFFICULTY_MAX} 之间：{value!r}")
    return value


# --------------------------------------------------------------------------- #
# 配置读取辅助
# --------------------------------------------------------------------------- #

def configured_store() -> LedgerStore:
    """从 config 构造默认账本；供 main / MCP / 脚本共用。"""
    import config

    return LedgerStore(
        facts_file=config.LEDGER_FACTS_FILE,
        links_file=config.LEDGER_LINKS_FILE,
    )


def parse_date_argument(value: str | date | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return _validate_date(value)


@contextmanager
def ledger_lock() -> Iterator[None]:
    """对外暴露串行化上下文，便于脚本把一次回填做成一个临界区。"""
    with FILE_LOCK:
        yield


__all__ = [
    "DIFFICULTY_MAX", "DIFFICULTY_MIN", "EFFECTS", "Fact", "INDEPENDENCE_LEVELS",
    "LedgerError", "LedgerStore", "Link", "PHASES", "RESULTS", "ROLES", "SKILLS",
    "SKILL_BY_ID", "SKILL_IDS", "configured_store", "ledger_lock", "link_counts",
    "parse_date_argument", "resolve_skill_id", "write_json_atomic",
]
