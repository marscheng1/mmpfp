"""能力证据库（Evidence Ledger）的契约测试。

范围：**只维护 fact + link 数据库**。因此这里断言的是 R1–R3、R6 与 §8.2 负例，
以及「账本里不出现任何画像派生量」——不断言任何样本数 / rating / 强度 / 引用校验。

* R1 持久化原子事实；R2 记录“以什么资格支撑哪项能力”；R3 按能力反查；
* R6 失效管理不重复计数；
* §8.2 负例：重复 id、未知 skill、superseded fact、空 why、派生字段。

`FACTS` / `LINKS` 是本测试自带的 round17 数据集（10 条事实、39 条 Link），
用作端到端夹具；它不依赖任何外部脚本。
"""

from __future__ import annotations

import json
import pathlib
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ledger import (  # noqa: E402
    DIFFICULTY_MAX, DIFFICULTY_MIN, FACT_ID_PATTERN, Fact, LedgerError,
    LedgerStore, Link, SKILL_IDS, link_counts,
)

# --------------------------------------------------------------------------- #
# round17 数据集：10 条原子事实 + 39 条 Link
#
# 内容照抄 `D:/code/OI/article/report/round17/2.能力证据.md` 与同目录
# `3.能力分析.md`（资格与正负侧来自 §2.1 的增量审计）。
# --------------------------------------------------------------------------- #

FACTS: list[dict] = [
    {
        'id': 'EV-R17-01',
        'pid': 'abc231_g',
        'date': '2026-09-16',
        'phase': '独立',
        'independence': 'I3',
        'difficulty': None,
        'result': '未成解',
        'source_ref': 'article/solutions/ABC231G.md:5',
        'supersedes': None,
        'note': 'A 在 13 分写出对所有非负、和为 K 的频数向量求和，权重为 K!/∏c_i!，贡献含 ∏(a_i+c_i)。',
    },
    {
        'id': 'EV-R17-02',
        'pid': 'abc231_g',
        'date': '2026-09-16',
        'phase': '独立',
        'independence': 'I3',
        'difficulty': None,
        'result': '未成解',
        'source_ref': 'article/solutions/ABC231G.md:9',
        'supersedes': None,
        'note': 'A 的 18/21/36/45 分递推逐步改变计数对象（少枚举频数乘子、把 n 个盒子的试验空间随乘积项数一并减少）；46 分转题解，独立阶段未撤回。',
    },
    {
        'id': 'EV-R17-03',
        'pid': 'abc231_g',
        'date': '2026-09-16',
        'phase': '题解后',
        'independence': 'I0',
        'difficulty': None,
        'result': 'AC',
        'source_ref': 'AT_abc231_G.cpp:108',
        'supersedes': None,
        'note': 'A 明确转题解后以系数 DP 与下降乘积计算答案并 AC；属于学习后实现，不回填 46 分前的独立阶段。',
    },
    {
        'id': 'EV-R17-04',
        'pid': 'abc228_h',
        'date': '2026-09-17',
        'phase': '独立',
        'independence': 'I3',
        'difficulty': None,
        'result': '未成解',
        'source_ref': 'article/solutions/ABC228H.md:5',
        'supersedes': None,
        'note': 'B 在 20/25 分形成分组正规形：桶聚合、连续段升至段尾、前缀和展开，并联想凸包、限定只在出现值处转移。20 分公式不完整（写 max、截距符号反）。',
    },
    {
        'id': 'EV-R17-05',
        'pid': 'abc228_h',
        'date': '2026-09-17',
        'phase': '独立',
        'independence': 'I3',
        'difficulty': None,
        'result': '未成解',
        'source_ref': 'article/solutions/ABC228H.md:13',
        'supersedes': None,
        'note': 'B 在 46 分发现应求最小值、52 分把单调栈改为单调队列，55 分记录 AC；极值方向晚纠正但由用户自己闭合。',
    },
    {
        'id': 'EV-R17-06',
        'pid': 'abc228_h',
        'date': '2026-09-17',
        'phase': '独立',
        'independence': 'I3',
        'difficulty': None,
        'result': 'AC',
        'source_ref': 'AT_abc228_H.cpp:104',
        'supersedes': None,
        'note': 'B 自述一次 AC 且与采集的一条 AC 一致；正确初始化、同值聚合、单调队列、叉积用 __int128，实际复杂度 O(M+n log n)。',
    },
    {
        'id': 'EV-R17-07',
        'pid': 'Cf1665E',
        'date': '2026-09-17',
        'phase': '独立',
        'independence': 'I3',
        'difficulty': None,
        'result': '未成解',
        'source_ref': 'article/solutions/CF1665E.md:5',
        'supersedes': None,
        'note': 'C 在 5–25 分做子掩码可行性改写、指出二分分支不能保证缩小、用 2^30 否定直接全域子集和；能识别框架缺关键适用条件，但未形成算法。',
    },
    {
        'id': 'EV-R17-08',
        'pid': 'Cf1665E',
        'date': '2026-09-17',
        'phase': '独立',
        'independence': 'I3',
        'difficulty': None,
        'result': '未成解',
        'source_ref': 'article/solutions/CF1665E.md:17',
        'supersedes': None,
        'note': 'C 在 36–47 分仍无思路，40 分才转向全局单询问；关键有限候选性质来自题解，用户确认之后看题解。',
    },
    {
        'id': 'EV-R17-09',
        'pid': 'Cf1665E',
        'date': '2026-09-17',
        'phase': '题解后',
        'independence': 'I0',
        'difficulty': None,
        'result': 'AC',
        'source_ref': 'CF1665E.cpp:96',
        'supersedes': None,
        'note': 'C 题解后实现每结点保留 31 小元素的短表线段树并 AC；静态核查未发现越界/哨兵/重复数问题。',
    },
    {
        'id': 'EV-R17-10',
        'pid': 'Cf1542E2',
        'date': '2026-09-17',
        'phase': '学习',
        'independence': 'I3',
        'difficulty': None,
        'result': 'AC',
        'source_ref': 'CF1542E2.cpp:98',
        'supersedes': None,
        'note': '旧 CF1542E2 沿用原差值计数与线性权重滑窗，用户补充“把取模优化了一些”，后续提交 AC；原独立限时 TLE 保留。',
    },
]

LINKS: list[dict] = [
    {
        'fact_id': 'EV-R17-01',
        'skill_id': 'B3',
        'role': 'core',
        'effect': 'positive',
        'why': '13 分就写出对所有非负、和为 K 的频数向量的完整联合计数表达，建模入口正确，是该题的关键区分点之一。',
    },
    {
        'fact_id': 'EV-R17-01',
        'skill_id': 'A4',
        'role': 'core',
        'effect': 'positive',
        'why': '权重 K!/∏c_i! 与贡献 ∏(a_i+c_i) 的联合计数式正确，属于本题数学阶段的核心正证。',
    },
    {
        'fact_id': 'EV-R17-01',
        'skill_id': 'B2',
        'role': 'auxiliary',
        'effect': 'positive',
        'why': '“先转计数再算期望”的视角切换是辅助观察；本题关键负荷在后续压缩，此条不构成该题核心性质发现。',
    },
    {
        'fact_id': 'EV-R17-01',
        'skill_id': 'B1',
        'role': 'auxiliary',
        'effect': 'positive',
        'why': '正确复述随机选择、乘积期望与数据范围，属读题辅助正证；未出现读题主导错误，但本题并未以读题为瓶颈。',
    },
    {
        'fact_id': 'EV-R17-02',
        'skill_id': 'A4',
        'role': 'core',
        'effect': 'negative',
        'why': '在原文给出的 f 含义下是实质计数错误：递推缺少被枚举频数 m 的乘数，把参与乘积的盒子数与可选盒子总数混同，数学语义核验是该题关键区分点。',
    },
    {
        'fact_id': 'EV-R17-02',
        'skill_id': 'B3',
        'role': 'core',
        'effect': 'negative',
        'why': '状态转移改变了样本空间（把 n 个盒子的试验空间随乘积项数一并减少），对象身份在转换中没有保持，是本题建模的核心负侧。',
    },
    {
        'fact_id': 'EV-R17-02',
        'skill_id': 'A2',
        'role': 'core',
        'effect': 'negative',
        'why': '18/21/36 分的递推在固定样本空间下都不成立，45 分求导式只是与错误递推自洽；本题递推等价性是该题的核心考察点。',
    },
    {
        'fact_id': 'EV-R17-02',
        'skill_id': 'B6',
        'role': 'core',
        'effect': 'negative',
        'why': '等价性核验的核心过程负证：连续三个式子在书面过程里都没有被撤回或说明新语义，证明/核验环节未拦住错误。',
    },
    {
        'fact_id': 'EV-R17-02',
        'skill_id': 'B4',
        'role': 'auxiliary',
        'effect': 'negative',
        'why': '算法设计阶段的未完成主要由上游语义错误决定，不单独给该能力记“2600 失败”，因此只作辅助负侧。',
    },
    {
        'fact_id': 'EV-R17-02',
        'skill_id': 'B8',
        'role': 'auxiliary',
        'effect': 'negative',
        'why': '错误路线影响探索收敛，但归因受上游语义错误主导，只作辅助过程观察，不据总题分判收敛阈值。',
    },
    {
        'fact_id': 'EV-R17-03',
        'skill_id': 'C2',
        'role': 'auxiliary',
        'effect': 'positive',
        'why': 'I0 学习后以系数 DP 和下降乘积实现并 AC，只能作学习后辅助观察；没有记录证明逐字独立写出，独立实现样本不增加。',
    },
    {
        'fact_id': 'EV-R17-04',
        'skill_id': 'B2',
        'role': 'core',
        'effect': 'positive',
        'why': '独自从桶聚合看出连续段可升至段尾、并走到前缀和展开，结构观察是该题关键区分点。',
    },
    {
        'fact_id': 'EV-R17-04',
        'skill_id': 'B3',
        'role': 'core',
        'effect': 'positive',
        'why': '分组正规形正确：排序后组内连续、终值不超过组内原最大值，构成可算模型，是本题核心建模步骤。',
    },
    {
        'fact_id': 'EV-R17-04',
        'skill_id': 'A2',
        'role': 'core',
        'effect': 'positive',
        'why': '把问题化为 f_i 的最小代价 DP 并在出现值处转移，状态设计与转移方向是本题核心。',
    },
    {
        'fact_id': 'EV-R17-04',
        'skill_id': 'A1',
        'role': 'auxiliary',
        'effect': 'positive',
        'why': '用的是 09-10 已自述掌握的单调 CHT，属熟悉工具的辅助正证；不能把整题 2500 复制成数据结构专项成功。',
    },
    {
        'fact_id': 'EV-R17-04',
        'skill_id': 'C6',
        'role': 'auxiliary',
        'effect': 'positive',
        'why': '把已知 CHT 接到新代价函数上属近距离迁移的辅助正证；不证明所有抽象都能远迁移。',
    },
    {
        'fact_id': 'EV-R17-04',
        'skill_id': 'B6',
        'role': 'auxiliary',
        'effect': 'positive',
        'why': '正文没有完整独立证明书写，教练证明不回填；单调性方向曾写反后纠正，只作辅助过程观察。',
    },
    {
        'fact_id': 'EV-R17-04',
        'skill_id': 'B5',
        'role': 'auxiliary',
        'effect': 'positive',
        'why': '20 分时的复杂度判断只是接口层观察，未形成完整总界；专项有效难度 Unknown，不复制整题 2500。',
    },
    {
        'fact_id': 'EV-R17-05',
        'skill_id': 'B4',
        'role': 'core',
        'effect': 'positive',
        'why': '从发现目标方向错误到改成单调队列并交付，是本题完整算法的核心成功组成。',
    },
    {
        'fact_id': 'EV-R17-05',
        'skill_id': 'B6',
        'role': 'auxiliary',
        'effect': 'boundary',
        'why': '46 分才发现应求最小值，语义一致性检查偏晚；这只界定核验时机，不是专项难度失败。',
    },
    {
        'fact_id': 'EV-R17-05',
        'skill_id': 'C3',
        'role': 'auxiliary',
        'effect': 'positive',
        'why': '用户自己把单调栈改成单调队列并一次 AC，是调试正证；但专项有效难度 Unknown，不按 2500 拟合阈值。',
    },
    {
        'fact_id': 'EV-R17-05',
        'skill_id': 'B8',
        'role': 'auxiliary',
        'effect': 'boundary',
        'why': '46→55 分最多 9 分钟的纠正后交付窗口是辅助过程观察，不能量化 21 分钟是否浪费，也不作为收敛阈值。',
    },
    {
        'fact_id': 'EV-R17-06',
        'skill_id': 'B4',
        'role': 'core',
        'effect': 'positive',
        'why': '55 分独立交付正确代码，本题最终目标与实现一致，是完整算法的核心成功。',
    },
    {
        'fact_id': 'EV-R17-06',
        'skill_id': 'C2',
        'role': 'auxiliary',
        'effect': 'positive',
        'why': '本题编码以熟悉的单调队列与叉积为主，属辅助实现正证；不能把整题难度当编码难度。',
    },
    {
        'fact_id': 'EV-R17-06',
        'skill_id': 'C4',
        'role': 'auxiliary',
        'effect': 'positive',
        'why': '25 分主动只在出现值处转移是直接边界行为，但正确代码不能推定所有边界都在开写前检查。',
    },
    {
        'fact_id': 'EV-R17-06',
        'skill_id': 'B1',
        'role': 'auxiliary',
        'effect': 'positive',
        'why': '正确复述目标与约束，属读题辅助正证；未构成本题瓶颈。',
    },
    {
        'fact_id': 'EV-R17-07',
        'skill_id': 'B5',
        'role': 'auxiliary',
        'effect': 'positive',
        'why': '用 2^30 否定直接全域子集和、指出二分分支不能保证缩小，属基本成本与接口判断，有效难度 Unknown。',
    },
    {
        'fact_id': 'EV-R17-07',
        'skill_id': 'B3',
        'role': 'auxiliary',
        'effect': 'positive',
        'why': '子掩码可行性改写有价值但未形成可执行算法，属辅助正证，不作 2500 核心成功。',
    },
    {
        'fact_id': 'EV-R17-07',
        'skill_id': 'B2',
        'role': 'auxiliary',
        'effect': 'positive',
        'why': '发现框架缺少适用条件是辅助观察；关键有限候选性质此后仍未被发现。',
    },
    {
        'fact_id': 'EV-R17-07',
        'skill_id': 'B1',
        'role': 'auxiliary',
        'effect': 'positive',
        'why': '目标与操作定义提取正确，属读题辅助正证。',
    },
    {
        'fact_id': 'EV-R17-08',
        'skill_id': 'B2',
        'role': 'core',
        'effect': 'negative',
        'why': '47 分仍未发现“保留最小 31 个候选”这一关键性质，性质发现是该题的关键区分点，构成核心负侧。',
    },
    {
        'fact_id': 'EV-R17-08',
        'skill_id': 'B3',
        'role': 'auxiliary',
        'effect': 'negative',
        'why': '性质缺失之后的建模未完成，受上游限制，只作辅助负侧。',
    },
    {
        'fact_id': 'EV-R17-08',
        'skill_id': 'B4',
        'role': 'auxiliary',
        'effect': 'negative',
        'why': '先套多询问框架、再研究单询问结构，是性质缺失导致的设计阶段未完成，不单独记核心失败。',
    },
    {
        'fact_id': 'EV-R17-08',
        'skill_id': 'B8',
        'role': 'auxiliary',
        'effect': 'negative',
        'why': '探索顺序是可复查的过程特征，但只有一个直接样本，只作辅助观察，不泛化为探索习惯。',
    },
    {
        'fact_id': 'EV-R17-09',
        'skill_id': 'A1',
        'role': 'auxiliary',
        'effect': 'positive',
        'why': 'I0 题解后实现短表线段树并 AC，属学习后结构落地；不能证明 2500 独立数据结构能力。',
    },
    {
        'fact_id': 'EV-R17-09',
        'skill_id': 'C2',
        'role': 'auxiliary',
        'effect': 'positive',
        'why': '题解后实现正确且有 AC，只增加学习后实现经验；独立评分排除。',
    },
    {
        'fact_id': 'EV-R17-10',
        'skill_id': 'B5',
        'role': 'auxiliary',
        'effect': 'positive',
        'why': '原数学算法的实际工作量判断曾被取模开销主导，后来靠减少/延后取模交付；性能修复专项强度 Unknown，不复制 2700。',
    },
    {
        'fact_id': 'EV-R17-10',
        'skill_id': 'C2',
        'role': 'auxiliary',
        'effect': 'positive',
        'why': '旧题熟悉基础上的交付追加，属辅助更新；不新增陌生成功。',
    },
    {
        'fact_id': 'EV-R17-10',
        'skill_id': 'C3',
        'role': 'auxiliary',
        'effect': 'positive',
        'why': '定位到取模重操作并优化到 AC，是旧题性能闭合的辅助正证；不抹除原独立限时 TLE。',
    },
]

PRIMARY_FACTS = {fact["id"] for fact in FACTS}
LINK_COUNT = len(LINKS)


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture()
def store(tmp_path: Path) -> LedgerStore:
    return LedgerStore(
        facts_file=str(tmp_path / "facts.json"),
        links_file=str(tmp_path / "ledger-links.json"),
    )


@pytest.fixture()
def backfilled(store: LedgerStore) -> LedgerStore:
    """把 round17 的 10 条证据写进临时账本（等价于走内部 store 接口迁移）。"""
    for payload in FACTS:
        store.add_fact(Fact.model_validate(payload))
    for payload in LINKS:
        store.add_link(Link.model_validate({**payload, "created": "2026-09-17"}))
    return store


def _sample_fact(**overrides) -> dict:
    payload = {
        "id": "EV-TEST-01",
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


def _sample_link(**overrides) -> dict:
    payload = {
        "fact_id": "EV-TEST-01",
        "skill_id": "B2",
        "role": "core",
        "effect": "positive",
        "why": "测试用理由：该条测的是关键性质是否被发现。",
        "created": "2026-09-17",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# R1/R2：事实与资格判断的持久化
# --------------------------------------------------------------------------- #

def test_facts_and_links_round_trip_as_flat_arrays(store: LedgerStore):
    store.add_fact(Fact.model_validate(_sample_fact()))
    store.add_link(Link.model_validate(_sample_link()))

    facts = json.loads(Path(store.facts_file).read_text(encoding="utf-8"))
    links = json.loads(Path(store.links_file).read_text(encoding="utf-8"))
    assert isinstance(facts, list) and isinstance(links, list)
    assert facts[0]["id"] == "EV-TEST-01"
    assert links[0] == {
        "fact_id": "EV-TEST-01", "skill_id": "B2", "role": "core",
        "effect": "positive",
        "why": "测试用理由：该条测的是关键性质是否被发现。",
        "created": "2026-09-17",
    }


def test_skill_id_is_frozen_and_display_name_is_only_an_alias(store: LedgerStore):
    store.add_fact(Fact.model_validate(_sample_fact()))
    store.add_link(Link.model_validate(_sample_link(skill_id="Observation")))
    assert store.read_links()[0].skill_id == "B2"
    # 同一事实可以挂多项能力。
    store.add_link(Link.model_validate(_sample_link(skill_id="A4", role="auxiliary")))
    assert {link.skill_id for link in store.read_links()} == {"B2", "A4"}


def test_ledger_files_never_contain_profile_derived_fields(backfilled: LedgerStore):
    """账本里不出现任何画像派生量：rating、样本数、强度、区间、置信度。

    `superseded` 是文件内容现算的派生状态，不属于落盘字段。
    """
    forbidden = {"rating", "strength", "confidence", "range", "sample_count",
                 "samples", "core_count", "aux_count", "independent_samples",
                 "baseline_samples", "profile", "ability_rating"}
    for path in (backfilled.facts_file, backfilled.links_file):
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        for row in payload:
            assert not (forbidden & set(row)), (path, row)


def test_no_profile_or_citation_api_survives_in_the_package():
    """账本模块不再导出任何画像投影 / 强度派生 / 政策核查 / 引用校验入口。"""
    import ledger

    for gone in ("project_profile", "render_increment", "scan_aux_violations",
                 "SkillProjection", "ProfileProjection", "PROXY_SKILL_IDS",
                 "AUX_POLICY"):
        assert not hasattr(ledger, gone), gone
    assert not hasattr(LedgerStore, "read_baseline")
    assert not hasattr(LedgerStore, "read_registry")
    assert not hasattr(LedgerStore, "verify_citation")


# --------------------------------------------------------------------------- #
# §8.2 负例
# --------------------------------------------------------------------------- #

def test_duplicate_fact_id_is_rejected(store: LedgerStore):
    store.add_fact(Fact.model_validate(_sample_fact()))
    with pytest.raises(LedgerError, match="已存在"):
        store.add_fact(Fact.model_validate(_sample_fact(note="覆盖尝试")))


@pytest.mark.parametrize("skill_id", ["Z9", "Observationn", "", "B0"])
def test_unknown_skill_id_is_rejected(store: LedgerStore, skill_id: str):
    store.add_fact(Fact.model_validate(_sample_fact()))
    with pytest.raises(Exception):
        Link.model_validate(_sample_link(skill_id=skill_id))


def test_link_on_missing_fact_is_rejected(store: LedgerStore):
    with pytest.raises(LedgerError, match="fact_id 不存在"):
        store.add_link(Link.model_validate(_sample_link(fact_id="EV-NOPE-01")))


def test_superseded_fact_cannot_receive_new_links(store: LedgerStore):
    store.add_fact(Fact.model_validate(_sample_fact()))
    _, replacement = store.supersede("EV-TEST-01", reason="后续澄清修正", created="2026-09-18")
    assert replacement == "EV-TEST-01-C1"

    with pytest.raises(LedgerError, match="superseded"):
        store.add_link(Link.model_validate(_sample_link(skill_id="A4")))

    # 修正后的事实仍可挂 Link。
    store.add_link(Link.model_validate(
        _sample_link(fact_id=replacement, skill_id="A4", created="2026-09-18")))


@pytest.mark.parametrize("why", ["", "   ", "\n"])
def test_empty_why_is_rejected(store: LedgerStore, why: str):
    store.add_fact(Fact.model_validate(_sample_fact()))
    with pytest.raises(Exception):
        Link.model_validate(_sample_link(why=why))


@pytest.mark.parametrize("field,value", [
    ("rating", 2600),
    ("samples", 12),
    ("core_count", 3),
    ("confidence", 0.5),
    ("strength", "Strong"),
    ("range", "2000-3000"),
    ("independent_samples", 8),
    ("baseline_samples", 25),
])
def test_derived_fields_are_rejected_by_schema(field: str, value: object):
    """§8.2：在任意字段写入 rating / 样本数 → 字段不存在即拒。"""
    with pytest.raises(Exception):
        Fact.model_validate(_sample_fact(**{field: value}))
    with pytest.raises(Exception):
        Link.model_validate(_sample_link(**{field: value}))


@pytest.mark.parametrize("field,value", [
    ("phase", "赛后复盘"),
    ("independence", "I5"),
    ("difficulty", "easy"),
    ("result", "AC-ish"),
    ("date", "2026/09/17"),
    ("source_ref", "article/solutions/P1001.md"),
    ("id", "R17-01"),
])
def test_fact_enums_and_formats_are_enforced(field: str, value: object):
    with pytest.raises(Exception):
        Fact.model_validate(_sample_fact(**{field: value}))


@pytest.mark.parametrize("value", [True, False, 1.5, -1, 8001, "x"])
def test_difficulty_rejects_non_integers_and_out_of_range(value: object):
    with pytest.raises(Exception):
        Fact.model_validate(_sample_fact(difficulty=value))


@pytest.mark.parametrize("value", [0, 8000, 2500])
def test_difficulty_accepts_a_plain_int(value: int):
    assert Fact.model_validate(_sample_fact(difficulty=value)).difficulty == value


@pytest.mark.parametrize("field,value", [
    ("role", "primary"),
    ("effect", "neutral"),
    ("created", "2026-9-17"),
])
def test_link_enums_and_formats_are_enforced(field: str, value: object):
    with pytest.raises(Exception):
        Link.model_validate(_sample_link(**{field: value}))


def test_duplicate_link_is_rejected(store: LedgerStore):
    store.add_fact(Fact.model_validate(_sample_fact()))
    store.add_link(Link.model_validate(_sample_link()))
    with pytest.raises(LedgerError, match="已存在"):
        store.add_link(Link.model_validate(_sample_link(role="auxiliary")))


def test_note_cannot_smuggle_derived_numbers():
    with pytest.raises(Exception):
        Fact.model_validate(_sample_fact(note="本轮共 12 个样本"))
    with pytest.raises(Exception):
        Fact.model_validate(_sample_fact(note="rating 2600"))


# --------------------------------------------------------------------------- #
# R6：失效管理
# --------------------------------------------------------------------------- #

def test_superseded_fact_stays_readable_and_is_marked(store: LedgerStore):
    store.add_fact(Fact.model_validate(_sample_fact()))
    store.add_link(Link.model_validate(_sample_link()))

    store.supersede("EV-TEST-01", reason="修正计数对象", created="2026-09-18")

    # 旧 Fact 仍可读，标 superseded，并给出 replaced_by（可追溯，不是删除）。
    entry = store.get_fact("EV-TEST-01")
    assert entry["fact"]["superseded"] is True
    assert entry["replaced_by"] == "EV-TEST-01-C1"
    assert entry["links"][0]["role"] == "core"

    # 取代它的新 Fact 记录 supersedes，可追溯回旧 id。
    replacement = store.get_fact("EV-TEST-01-C1")["fact"]
    assert replacement["supersedes"] == "EV-TEST-01"
    assert replacement["superseded"] is False


def test_role_and_effect_are_frozen_at_write_time(backfilled: LedgerStore):
    """role / effect 是写入时的判断，读回来必须一模一样，且 core/aux 分列保留。"""
    roles = {link.role for link in backfilled.read_links()}
    effects = {link.effect for link in backfilled.read_links()}
    assert roles == {"core", "auxiliary"}
    assert effects <= {"positive", "negative", "boundary"}
    assert sum(1 for link in backfilled.read_links() if link.role == "core") == 12
    assert sum(1 for link in backfilled.read_links() if link.role == "auxiliary") == 27
    # `out` 的 Link 有资格标记、但不参与判断。
    assert link_counts(Link.model_validate(_sample_link(role="out"))) is False
    assert link_counts(Link.model_validate(_sample_link(role="core"))) is True


def test_difficulty_defaults_to_null_until_calibrated(backfilled: LedgerStore):
    """difficulty 是 Fact 的字段；未核定时为 null，仍是合法值。"""
    facts = backfilled.read_facts()
    assert {fact.difficulty for fact in facts} == {None}
    # 它不是派生量：写进 JSON 的就是 null。
    payload = json.loads(pathlib.Path(backfilled.facts_file).read_text(encoding="utf-8"))
    assert all("difficulty" in row and row["difficulty"] is None for row in payload)
    assert all("independence_source" not in row for row in payload)


def test_search_can_filter_links_by_the_difficulty_of_their_fact(store: LedgerStore):
    """Link 没有自己的 difficulty：筛选用的是它所属 Fact 的 difficulty。"""
    for fact_id, difficulty in (("EV-D-01", 2500), ("EV-D-02", 1900),
                                ("EV-D-03", None), ("EV-D-04", 2500)):
        store.add_fact(Fact.model_validate(_sample_fact(
            id=fact_id, pid=f"P-{fact_id[-2:]}", difficulty=difficulty)))
        store.add_link(Link.model_validate(_sample_link(fact_id=fact_id)))

    def ids(**kwargs) -> set[str]:
        return {row["fact_id"] for row in store.search(skill_id="B2", **kwargs)}

    assert ids() == {"EV-D-01", "EV-D-02", "EV-D-03", "EV-D-04"}
    # 单值
    assert ids(difficulty=[2500]) == {"EV-D-01", "EV-D-04"}
    # 多值 OR
    assert ids(difficulty=[2500, 1900]) == {"EV-D-01", "EV-D-02", "EV-D-04"}
    # difficulty 为 null 的 Fact 不会被任何难度筛选命中
    assert "EV-D-03" not in ids(difficulty=[2500, 1900])
    # 没有命中的难度返回空
    assert ids(difficulty=[3000]) == set()
    # 查询结果行里带回所属 Fact 的 difficulty
    rows = store.search(skill_id="B2", difficulty=[1900])
    assert [row["difficulty"] for row in rows] == [1900]
    assert rows[0]["fact_id"] == "EV-D-02"
    # 与其它条件叠加
    assert ids(difficulty=[2500], role="core") == {"EV-D-01", "EV-D-04"}
    assert ids(difficulty=[2500], role="auxiliary") == set()
    assert ids(difficulty=[2500], effect="negative") == set()


@pytest.mark.parametrize("bad", ["easy", True, 1.5, -1, 8001, [2500, "x"]])
def test_search_rejects_bad_difficulty_filters(store: LedgerStore, bad: object):
    store.add_fact(Fact.model_validate(_sample_fact()))
    with pytest.raises(LedgerError):
        store.search(skill_id="B2", difficulty=bad)


def _difficulty_spread_store(store: LedgerStore) -> dict[str, int | None]:
    """造一批难度分散的样本：1600 / 1900 / 2500 / 2500 / 未核定。"""
    spread: dict[str, int | None] = {
        "EV-R-01": 1600, "EV-R-02": 1900, "EV-R-03": 2500,
        "EV-R-04": 2500, "EV-R-05": None,
    }
    for fact_id, difficulty in spread.items():
        store.add_fact(Fact.model_validate(_sample_fact(
            id=fact_id, pid=f"P-{fact_id[-2:]}", difficulty=difficulty)))
        store.add_link(Link.model_validate(_sample_link(fact_id=fact_id)))
    return spread


def test_search_difficulty_range_is_inclusive_and_open_ended(store: LedgerStore):
    """区间搜索：闭区间，两端可单独给出。"""
    _difficulty_spread_store(store)

    def ids(**kwargs) -> set[str]:
        return {row["fact_id"] for row in store.search(skill_id="B2", **kwargs)}

    # 闭区间：两端都含在结果里。
    assert ids(difficulty_min=1900, difficulty_max=2500) == {
        "EV-R-02", "EV-R-03", "EV-R-04"}
    # 只给下界 = “≥ 下界”
    assert ids(difficulty_min=2500) == {"EV-R-03", "EV-R-04"}
    # 只给上界 = “≤ 上界”
    assert ids(difficulty_max=1900) == {"EV-R-01", "EV-R-02"}
    # 单点区间等价于精确匹配该值
    assert ids(difficulty_min=1900, difficulty_max=1900) == {"EV-R-02"}
    # 区间内没有样本时返回空，而不是回退成不筛
    assert ids(difficulty_min=2000, difficulty_max=2400) == set()
    # 覆盖全量上限时，未核定难度的样本仍然不出现
    assert ids(difficulty_min=DIFFICULTY_MIN, difficulty_max=DIFFICULTY_MAX) == {
        "EV-R-01", "EV-R-02", "EV-R-03", "EV-R-04"}


def test_search_difficulty_range_never_matches_uncalibrated_facts(store: LedgerStore):
    """null 与任何区间都不可比：不能因为“不满足 >2500”就被归到低难度。"""
    _difficulty_spread_store(store)
    for kwargs in ({"difficulty_min": 0}, {"difficulty_max": 8000},
                   {"difficulty_min": 0, "difficulty_max": 8000},
                   {"difficulty_min": 2600}, {"difficulty_max": 1500}):
        rows = store.search(skill_id="B2", **kwargs)
        assert "EV-R-05" not in {row["fact_id"] for row in rows}, kwargs


def test_search_difficulty_range_ands_with_exact_values(store: LedgerStore):
    """精确值列表与区间同时给出时取交集。"""
    _difficulty_spread_store(store)

    def ids(**kwargs) -> set[str]:
        return {row["fact_id"] for row in store.search(skill_id="B2", **kwargs)}

    assert ids(difficulty=[1600, 2500], difficulty_min=2000) == {
        "EV-R-03", "EV-R-04"}
    # 交集为空时返回空，而不是退化成并集。
    assert ids(difficulty=[1600], difficulty_min=2000) == set()
    assert ids(difficulty=[1600, 1900], difficulty_max=1900) == {
        "EV-R-01", "EV-R-02"}


def test_search_difficulty_range_stacks_with_other_filters(store: LedgerStore):
    """区间与 role / effect / independence / 日期叠加时，只留下同时满足全部条件的 Link。"""
    _difficulty_spread_store(store)
    # 同一 Fact × skill 只能有一条 Link（add_link 会拒重复），所以用另外两条 Fact
    # 造出 out 资格与 negative 侧。
    for fact_id, role, effect in (("EV-R-06", "out", "positive"),
                                  ("EV-R-07", "core", "negative")):
        store.add_fact(Fact.model_validate(_sample_fact(
            id=fact_id, pid=f"P-{fact_id[-2:]}", difficulty=2500)))
        store.add_link(Link.model_validate(_sample_link(
            fact_id=fact_id, role=role, effect=effect)))

    def ids(**kwargs) -> set[str]:
        return {row["fact_id"] for row in store.search(skill_id="B2", **kwargs)}

    assert ids(difficulty_min=2500) == {"EV-R-03", "EV-R-04", "EV-R-06", "EV-R-07"}
    assert ids(difficulty_min=2500, role="core") == {"EV-R-03", "EV-R-04", "EV-R-07"}
    assert ids(difficulty_min=2500, role="out") == {"EV-R-06"}
    assert ids(difficulty_min=2500, role="auxiliary") == set()
    assert ids(difficulty_min=2500, effect="negative") == {"EV-R-07"}
    assert ids(difficulty_min=2500, effect="boundary") == set()
    # independence 与日期读的是所属 Fact，因此整条 Fact 的资格一起生效。
    assert ids(difficulty_min=2500, independence=["I3"]) == {
        "EV-R-03", "EV-R-04", "EV-R-06", "EV-R-07"}
    assert ids(difficulty_min=2500, independence=["I0"]) == set()
    assert ids(difficulty_min=2500, start_date="2026-09-17") == {
        "EV-R-03", "EV-R-04", "EV-R-06", "EV-R-07"}
    assert ids(difficulty_min=2500, start_date="2026-09-18") == set()
    # 区间先排除样本时，其它条件不会把它带回来。
    assert ids(difficulty_min=2600, role="core") == set()
    assert ids(difficulty_max=1500, effect="negative") == set()


def test_search_difficulty_range_stacks_with_date_bounds(store: LedgerStore):
    """区间与日期上下界叠加时，只有同时满足两者的样本留下。"""
    for fact_id, day in (("EV-R-11", "2026-09-10"), ("EV-R-12", "2026-09-20")):
        store.add_fact(Fact.model_validate(_sample_fact(
            id=fact_id, pid=f"P-{fact_id[-2:]}", date=day, difficulty=2500)))
        store.add_link(Link.model_validate(_sample_link(fact_id=fact_id)))

    def ids(**kwargs) -> set[str]:
        return {row["fact_id"] for row in store.search(skill_id="B2", **kwargs)}

    assert ids(difficulty_min=2000) == {"EV-R-11", "EV-R-12"}
    assert ids(difficulty_min=2000, start_date="2026-09-15") == {"EV-R-12"}
    assert ids(difficulty_min=2000, end_date="2026-09-15") == {"EV-R-11"}
    assert ids(difficulty_min=2000, start_date="2026-09-15",
               end_date="2026-09-19") == set()
    # 区间本身筛掉样本时，日期条件不会把它救回来。
    assert ids(difficulty_max=1000, start_date="2026-09-01") == set()


def test_search_accepts_numeric_strings_for_difficulty_bounds(store: LedgerStore):
    """HTTP query 只给字符串，因此两界也要接受数字串（与精确筛选一致）。"""
    _difficulty_spread_store(store)

    def ids(**kwargs) -> set[str]:
        return {row["fact_id"] for row in store.search(skill_id="B2", **kwargs)}

    assert ids(difficulty_min="1900", difficulty_max="2500") == {
        "EV-R-02", "EV-R-03", "EV-R-04"}
    assert ids(difficulty_min=" 2500 ") == {"EV-R-03", "EV-R-04"}


@pytest.mark.parametrize("kwargs", [
    {"difficulty_min": "easy"},
    {"difficulty_max": "easy"},
    {"difficulty_min": True},
    {"difficulty_max": 1.5},
    {"difficulty_min": -1},
    {"difficulty_max": 8001},
    {"difficulty_min": 2500, "difficulty_max": 1900},
])
def test_search_rejects_bad_difficulty_bounds(store: LedgerStore, kwargs: dict):
    """非法界与上下界颠倒都按调用错误处理，不静默返回空集。"""
    _difficulty_spread_store(store)
    with pytest.raises(LedgerError):
        store.search(skill_id="B2", **kwargs)


# --------------------------------------------------------------------------- #
# R3：按能力反查
# --------------------------------------------------------------------------- #

def test_search_filters_by_role_effect_and_independence(backfilled: LedgerStore):
    rows = backfilled.search(skill_id="B2")
    assert {row["fact_id"] for row in rows} == {"EV-R17-01", "EV-R17-04", "EV-R17-07",
                                                "EV-R17-08"}
    assert all(row["why"] and row["source_ref"] for row in rows)

    core = backfilled.search(skill_id="B2", role="core")
    assert {row["fact_id"] for row in core} == {"EV-R17-04", "EV-R17-08"}
    negative = backfilled.search(skill_id="B2", effect="negative")
    assert {row["fact_id"] for row in negative} == {"EV-R17-08"}
    explicit = backfilled.search(skill_id="B2", independence=["I0"])
    assert explicit == []
    assert backfilled.search(skill_id="B2", start_date="2026-09-17") != []
    assert backfilled.search(skill_id="B2", limit=1) != []
    assert all(row["counts_for_judgement"] for row in rows)


def test_search_rejects_bad_filters(backfilled: LedgerStore):
    for kwargs in ({"role": "primary"}, {"effect": "neutral"},
                   {"independence": ["I9"]}, {"start_date": "2026-9-1"},
                   {"limit": 0}):
        with pytest.raises(LedgerError):
            backfilled.search(skill_id="B2", **kwargs)
    with pytest.raises(LedgerError):
        backfilled.search(skill_id="Z9")


def test_search_covers_every_frozen_skill_id(backfilled: LedgerStore):
    assert set(SKILL_IDS) == {skill.skill_id for skill in __import__("ledger").SKILLS}
    assert len(SKILL_IDS) == 19
    # 账本里只有这些能力有 Link；其余返回空列表而不是报错。
    assert backfilled.search(skill_id="A5") == []


def test_get_fact_returns_all_links(backfilled: LedgerStore):
    entry = backfilled.get_fact("EV-R17-04")
    assert entry["fact"]["pid"] == "abc228_h"
    assert len(entry["links"]) == 7
    assert {link["skill_id"] for link in entry["links"]} == {
        "B2", "B3", "A2", "A1", "C6", "B6", "B5"}
    assert backfilled.get_fact("EV-NOPE-01") is None


# --------------------------------------------------------------------------- #
# §7 存储：原子写入 + 并发安全
# --------------------------------------------------------------------------- #

def test_writes_are_atomic_and_leave_no_temporary_files(store: LedgerStore):
    store.add_fact(Fact.model_validate(_sample_fact()))
    directory = Path(store.facts_file).parent
    assert [path.name for path in directory.glob("*.tmp")] == []
    assert json.loads(Path(store.facts_file).read_text(encoding="utf-8"))


def test_concurrent_writes_do_not_lose_facts(store: LedgerStore):
    import threading

    def write(index: int):
        store.add_fact(Fact.model_validate(_sample_fact(
            id=f"EV-TEST-{index:02d}",
            pid=f"P{1000 + index}",
            source_ref=f"article/solutions/P{1000 + index}.md:1",
        )))

    threads = [threading.Thread(target=write, args=(index,)) for index in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(store.read_facts()) == 12
    assert len(json.loads(Path(store.facts_file).read_text(encoding="utf-8"))) == 12


def test_fact_ids_are_stable_and_well_formed(backfilled: LedgerStore):
    for fact in backfilled.read_facts():
        assert FACT_ID_PATTERN.match(fact.id)
    assert {fact.id for fact in backfilled.read_facts()} == PRIMARY_FACTS
    assert len(backfilled.read_links()) == LINK_COUNT == 39
