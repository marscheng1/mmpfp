# MMPFP — 刷题记录追踪与解题日志

## 项目说明

刷题记录追踪应用，支持多 OJ 平台（Luogu、QOJ、UOJ、LOJ、Codeforces、CSES、HDU、AtCoder、MXOJ、HFOJ、代码源）的刷题记录统计，并提供本地解题日志编辑器。

浏览器采集脚本为 `webview-script.js`。HFOJ 支持 `hfoj.net/record` 和任意多层路径下的 `/record` 列表页（可带查询参数），点击页面上的“读取记录”按钮才会采集当前页；与 HDU 一样不自动采集或翻页，请先在网站上筛选自己的提交。HFOJ 题号保留题库路径，例如 `Hfoj_d_ou_training_centre_S44M7T3`，根题库使用 `Hfoj题号`；提交号使用 `Hfoj` 前缀。脚本中的 `debug = true` 只打印结果，设置为 `false` 才会上传到本地服务。

代码源新 OJ（`newoj.daimayuan.top/record`，可带查询参数）在页面加载后自动采集并上传当前页中匹配 `config.json` 的 `DMY_ID` 的提交。填写数字用户 ID，例如 `"DMY_ID": "41314"`，修改配置后需重启服务；脚本通过 `/api/id/dmy` 获取配置，按每行递交者链接中的 ID 匹配。未配置、ID 无效或当前页无匹配时不上传，不自动翻页。题号从题目链接读取并添加 `Dmy` 前缀，例如 `/p/5810` 保存为 `Dmy5810`，提交号也添加 `Dmy` 前缀；通过状态按 `st-pass` 判断，提交时间使用页面中的 Unix 时间戳。脚本默认 `debug = false`，可改为 `true` 仅打印采集结果。

UOJ 支持 `uoj.ac/submissions`（可带查询参数），通过 `/api/id/uoj` 获取 `config.json` 中的 `UOJ_ID` 用户名，例如 `"UOJ_ID": "marscheng"`，自动采集当前页中用户名匹配的提交，不自动翻页。未配置用户名或当前页无匹配时不上传。结果为 100 分记为通过，题号和提交号使用 `Uoj` 前缀，例如 `Uoj455`、`Uoj880803`。修改配置后需重启服务，并更新浏览器用户脚本；`debug = true` 时只打印结果，实际上传需设为 `false`。

LOJ 支持 `loj.ac/s`（可带查询参数），通过 `/api/id/loj` 获取 `config.json` 中的 `LOJ_ID` 用户名，例如 `"LOJ_ID": "marscheng"`。自动采集当前页中用户名匹配的提交，并在页面动态加载、手动筛选或翻页后重新采集；不自动翻页，同一提交内容未变化时不重复发送，等待评测的记录会等结果更新后再采集。通过状态为 `Accepted`，时间取完整日期的 `title` 属性，题号和提交号使用 `Loj` 前缀，例如 `Loj6500`、`Loj2634922`。修改配置后需重启服务，并更新浏览器用户脚本；`debug = true` 时只打印结果，实际上传需设为 `false`。

Codeforces 同时支持普通比赛与 Gym 的 `status`、`my` 页面（可带查询参数），沿用 `CF_ID` 配置匹配用户名。Gym 题号和提交号继续使用 `Cf` 前缀，例如 `Cf104053D`、`Cf396259403`；即使源码链接为 `#` 或隐藏，也能读取提交记录，只采集当前页。

CSES 支持 `cses.fi/problemset/result/<提交号>/`（可带查询参数）。在 `config.json` 中填写 `CSES_ID` 用户名，例如 `"CSES_ID": "marscheng"`，通过 `/api/id/cses` 获取配置，只采集提交详情中 Sender 匹配的记录。只读取当前结果页的总评结果，`ACCEPTED` 记为通过，未完成评测时等待状态更新；时间按页面明确给出的 UTC 偏移（如 `+0200`）转换。题号和提交号使用 `Cses` 前缀，例如 `Cses2088`、`Cses19262823`。修改配置后需重启服务并更新用户脚本；`debug = true` 时只打印结果，实际上传需设为 `false`。

## 快速开始

支持 Python 3.11–3.14，依赖和虚拟环境由 uv 管理。

```bash
# 安装依赖
uv sync

# 复制配置文件
cp config.json.sample config.json

# 编辑 config.json 填入你的 OJ 用户 ID 和题解目录
# 启动服务
uv run uvicorn main:app --host 127.0.0.1 --workers 1
```

`RECORDS_FILE`、`SOLUTIONS_DIR` 和 `SOLUTIONS_META_FILE` 用于配置记录数据、题解目录和题解元数据的实际位置。相对路径以项目根目录为基准，也可以填写绝对路径。例如，要让 API 直接保存题解到本地 OI 仓库：

```json
{
  "RECORDS_FILE": "data/records.json",
  "SOLUTIONS_DIR": "../OI/article/solutions",
  "SOLUTIONS_META_FILE": "data/solutions-meta.json",
  "LEDGER_FACTS_FILE": "../OI/data/facts.json",
  "LEDGER_LINKS_FILE": "../OI/data/ledger-links.json"
}
```

这样，mmpfp 中的 `data/solutions/<path>.md` 仍是默认目录约定，但 API 实际会读写 OI 仓库中的 `article/solutions/<path>.md`。题解文件由 OI 仓库管理，不会进入 mmpfp 的提交；请确保 `data/solutions/.gitignore` 继续忽略本地默认目录，并在 OI 仓库中提交 API 产生的修改。未配置这些字段时，会使用 `data/records.json`、`data/solutions` 和 `data/solutions-meta.json`。

`LEDGER_FACTS_FILE` 与 `LEDGER_LINKS_FILE` 配置能力证据库的两个平面文件（与 `data/prompt/` 同级，按“代码在 mmpfp，数据在 OI”的约定落在 OI 侧）。详见下节的「能力证据库」。

## Windows 桌面入口

桌面模式沿用当前配置和 uv 虚拟环境，使用 WebView2 显示原网页，并在后台运行同一个本地服务。首次使用在项目目录执行：

```powershell
uv sync --extra desktop
powershell -NoProfile -ExecutionPolicy Bypass -File .\create-desktop-shortcut.ps1
```

双击项目目录中的 `MMPFP.lnk` 后只启动后台服务和系统托盘，不弹出主窗口或命令行；也可以将快捷方式复制到桌面。快捷方式通过 Windows 的 `wscript.exe` 运行 `launch-desktop.vbs`，以隐藏方式调用 `.venv\Scripts\pythonw.exe desktop.py`，避免 uv 的控制台启动器弹出窗口。重新生成已有快捷方式时为脚本加上 `-Force`；旧的桌面快捷方式需重新复制。开发调试可使用 `uv run --extra desktop python desktop.py`。

点击系统托盘图标或菜单中的“打开窗口”显示主界面。窗口关闭按钮只会隐藏窗口，服务仍运行，浏览器采集脚本和 `http://127.0.0.1:8000/mcp` 仍然可用。重复双击快捷方式不会创建第二个实例，也不会弹出主界面。托盘“退出”会先保存解题日志的当前编辑内容和计时，再停止服务并释放端口；保存失败会取消退出并显示错误。退出后采集脚本和 MCP 不再可用。

桌面模式仍仅监听 `127.0.0.1:8000`。首次启动前请关闭原控制台服务；端口被其他程序占用时会提示冲突，不会接管或结束该程序。原 `uv run uvicorn main:app --host 127.0.0.1 --workers 1` 启动方式仍可单独使用。

需要 Microsoft Edge WebView2 Runtime，缺失时请安装该运行环境。日志位于 `logs/desktop.log`，浏览器主题等状态位于 `.desktop-storage/`，这些运行文件不进入 Git。桌面浏览器存储与 Chrome/Edge 的独立浏览器配置不共用。当前版本不打包独立 exe、不设置开机自启；图表和编辑器仍使用原有 CDN 资源，需要联网加载。

常规测试为 `uv run --no-sync python -m pytest`。安装桌面依赖后，可用 `uv run --no-sync python -m pytest tests/desktop_smoke.py -s` 运行真实窗口/托盘验证；该验证只使用临时数据和随机端口，不改动实际刷题记录，不会在常规测试中自动打开窗口。

## 安全边界

本项目的解题日志编辑接口是为本机前端提供的，默认不单独要求 Bearer Token。因此服务必须绑定 `127.0.0.1`，不要使用 `--host 0.0.0.0` 直接暴露到局域网或公网。若需要远程访问，必须先为 `/api/solutions/*` 写接口增加认证，并使用 HTTPS 和访问控制。

编辑接口的请求体示例：

```json
{"path": "math/example.md", "content": "# 题解"}
```

`/api/solutions/mkdir` 和 `/api/solutions/delete` 使用 `{"path": "..."}`。删除不允许使用空路径或知识库根目录，路径不能越界或通过符号链接访问。

文件内容限制为 2 MiB。

## MCP 查询与证据库

服务通过 [fastapi-mcp](https://github.com/tadata-org/fastapi_mcp) 扩展提供 MCP，
与网页共用进程和端口。运行 `uv sync` 安装依赖后按原命令启动即可。
支持 Streamable HTTP 的 MCP 客户端可连接 `http://127.0.0.1:8000/mcp`。

`/mcp` 在**同一个连接**里提供两组工具：下面四个只读的解题报告/提交查询，以及
[能力证据库](#能力证据库evidence-ledger)的 7 个读写工具。查询与账本都使用独立的内部
FastAPI 应用，主服务只增加 `/mcp` 入口，不改变已有网页/API 路径，也不将创建、保存、
删除解题日志的写接口发布为 MCP 工具。

**只读边界按工具划分**（`ToolAnnotations`）：四个查询工具是只读的；账本的两个读工具
（`ledger_search`、`ledger_get_fact`）也是只读的，三个写工具
标记为非只读，其中 `ledger_unlink` 另标 `destructiveHint=True`。
读取范围遵循 `config.json` 中的 `SOLUTIONS_DIR` 和当前服务已加载的提交记录。

| 工具 | 参数 | 返回值 |
| --- | --- | --- |
| `list_solution_reports` | 可选 `start_time`、`end_time`、`order`、`limit`、`time_field` | 报告相对路径列表 |
| `get_solution_report` | `relative_path` | `{"content": "报告完整 Markdown 内容"}` |
| `get_problem_submissions` | `pid` | 全部匹配的提交记录，按提交时间从新到旧排序 |
| `get_submissions_by_time` | 可选 `start_time`、`end_time`、`order`、`limit`、`offset` | 时间窗口内所有题目的提交记录，按指定顺序分页返回 |

“从现在开始，从新到旧，前 10 篇报告”对应以下工具调用：

```json
{"name": "list_solution_reports", "arguments": {"order": "desc", "limit": 10}}
```

也可以查询明确的时间窗口：

```json
{
  "name": "list_solution_reports",
  "arguments": {
    "start_time": "2026-09-01T00:00:00+08:00",
    "end_time": "2026-09-16T23:59:59+08:00",
    "order": "desc",
    "limit": 10
  }
}
```

时间窗口两端均包含。省略 `start_time` 表示不限下界，省略 `end_time` 表示查询到当前时刻（传入 `null` 与省略等价）；
时间格式为 ISO 8601，建议带时区，无时区时按服务器本地时间解释。
`order` 支持 `desc`（默认，从新到旧）和 `asc`（从旧到新），`limit` 默认 10，范围 1–1000。
`time_field` 默认 `created`，使用与前端相同的 `os.path.getctime`：Windows 上是文件创建时间，
Unix 上是元数据变更时间；也可设为 `modified`，按最后修改时间查询。时间相同时按相对路径升序。
查询递归包含所有 `.md` 报告（无论是否已标记完成），无匹配时返回 `[]`。

列表中的路径相对于 `SOLUTIONS_DIR`，使用 `/` 分隔，例如 `数学/P1001.md`，可直接用于读取：

```json
{"name": "get_solution_report", "arguments": {"relative_path": "数学/P1001.md"}}
```

读取时可以省略 `.md` 后缀。绝对路径、目录穿越和符号链接会被拒绝；文件不存在或参数无效时
返回 MCP 工具错误。MCP 响应的 `content` 文本中包含上述 JSON 返回值。

提交记录查询精确匹配采集器保存的 `pid`，例如 `P1001`、`Qoj123`、`Cf123A`、
`Hdu_123_1001`、`Atcoderabc001_1`；不要将不同平台的题号简化为同一个数字。

```json
{"name": "get_problem_submissions", "arguments": {"pid": "P1001"}}
```

每条记录包含 `time`（Unix 秒）、`status`（是否通过）、`pid`、`rid`。
按题号查询包含通过和未通过的所有本地记录，不截断数量；前端新采集的记录会立即反映在查询中，
不会主动请求 OJ 网站。MCP 使用与原服务相同的本机访问边界。

按时间窗口查询所有题目的提交记录：

```json
{
  "name": "get_submissions_by_time",
  "arguments": {
    "start_time": "2026-09-01T00:00:00+08:00",
    "end_time": "2026-09-16T23:59:59+08:00",
    "order": "desc",
    "limit": 100,
    "offset": 0
  }
}
```

时间格式、时区和边界规则与报告查询相同，但筛选的是每条记录的实际提交时间 `time`。
不传参数时返回截至现在、从新到旧的最近 10 条提交；包括所有平台、所有题目及通过/未通过的记录。
`limit` 范围为 1–1000，`offset` 默认 0，表示筛选、排序后跳过的记录数量。
时间相同时按 `rid` 升序；无匹配或超出分页范围时返回 `[]`。
例如以 `limit: 100` 分页时依次使用 `offset: 0`、`100`、`200`，直到返回不足 100 条；
翻页时建议固定 `end_time`，避免新提交改变分页位置。

## 能力证据库（Evidence Ledger）

把「每轮报告里手写的证据表」换成由 mmpfp 持久化、可增可查的账本。

**范围：只维护 fact + link 数据库。**账本存两类东西——**原子事实**（Fact：一次可
定位的观察）与 **Link**（“该事实以什么资格支撑哪项能力”的冻结判断，同一事实可挂
多项能力），并提供按能力反查与按 id 取单条。

**账本既不做能力画像，也不做引用校验。**样本数、Ability Rating、Plausible Range、
Confidence、证据强度都不在账本里，也没有任何能力画像 / 强度派生 / 对账 / 政策核查
逻辑——那些属于教练侧报告。引用是否写对同样不在这里判断：账本只如实返回已写入的
fact 与 link，怎么用它由使用方决定。账本只提供 `role`（core / auxiliary / out）、
`effect`、`independence` 这些**写入时就冻结的字段**，以及写在 Fact 上的 `difficulty`。

**`difficulty` 是 int，默认 `null`。**它表示题目难度（通常是 CF 等效 rating），记录在
**Fact** 上而不是 Link 上；Link 没有自己的难度，按难度检索时用的是它所属 Fact 的值。
`null` 表示尚未核定，**不会被任何难度筛选命中**；筛选传多个值时按“任一命中”（OR）
处理。历史行迁移后统一为 `null`，需要时再逐条回填。

难度有**两种**检索方式，同时给出时取交集：

- **精确值**：`difficulty`，多值 OR，如 `1475,2500`。
- **闭区间**：`difficulty_min` / `difficulty_max`，两端都可单独省略——只给下界表示
  “≥ 下界”，只给上界表示“≤ 上界”。两端都给出时必须 `min <= max`，否则按调用错误
  报 422，而不是静默返回空结果。

由于 null 不参与任何难度筛选，**区间查询取不到尚未核定难度的事实**。区间只作用于同一
条 Fact 上写入的单个难度值；同一题不同阶段给了不同难度时，它会按阶段分别参与筛选。

数据模型与完整设计见 `证据库改造需求.md`（OI 侧 `article/report/` 有同名副本）。

### 文件

只有两个平面文件，两者都是 JSON 数组、不嵌套（便于 diff 与人工审阅）：

| 文件 | 角色 | 默认位置 |
| --- | --- | --- |
| `LEDGER_FACTS_FILE` | 事实平面 | `data/facts.json` |
| `LEDGER_LINKS_FILE` | 链接平面 | `data/ledger-links.json` |

写入复用 `save_records_sync()` 的原子模式（同目录临时文件 → `flush` + `fsync` →
`os.replace`）并用 `RLock` 串行化。项目仍是**单进程单 worker**，不要多 worker 写账本。

### 失效管理

旧 Fact 被后续澄清修正时，写一条修正 Fact 并由它 `supersedes` 旧 id。旧 Fact 保持
**可读**（`ledger_get_fact` 会给出 `superseded: true` 与 `replaced_by`），但退出判断，
因此不会重复计数。给 `superseded` 的 Fact 新增 Link 会被拒。

### MCP 接口

账本工具与只读查询共用 `http://127.0.0.1:8000/mcp`，客户端一次连接即可。

| 工具 | 参数 | 说明 |
| --- | --- | --- |
| `ledger_add_fact` | `fact`（**不要传 `id`**） | 写一条原子事实，返回服务端分配的 `id` |
| `ledger_link` | `fact_id`、`skill_id`、`role`、`effect`、`why`、`created` | 冻结资格判断；`why` 必填 |
| `ledger_unlink` | `fact_id`、`skill_id` | 撤销一条 Link（标 `destructiveHint`） |
| `ledger_search` | `skill_id` 必填，可选 `role`、`effect`、`independence`、`difficulty`、`difficulty_min`、`difficulty_max`、`start_date`、`end_date`、`limit` | 按能力反查，返回 Fact + Link 合并行；难度可按精确值或闭区间筛 |
| `ledger_get_fact` | `fact_id` | 取单条（含全部 Links） |

**`id` 完全由服务端分配。**`ledger_add_fact` 返回形如 `EV-20260917-01` 的稳定 id；
调用方传入 `id` 会被拒（422），因此不可能借客户端编号互相覆盖。需要沿用历史报告编号
（如 `EV-R17-01`）的**迁移/回填**走内部接口 `LedgerStore.add_fact()`，不经过 MCP 写面。

**写工具不需要二次确认**：调用即落盘。`role`/`effect`/`independence` 等枚举非法、
`why` 为空、`fact_id` 不存在、`skill_id` 不在清单、重复 Link、给 `superseded` 的 Fact
加 Link 都会被拒；Fact/Link 模型 `extra="forbid"`，因此 rating、样本数之类的派生字段
「字段不存在即拒」。

### 网页端只读展示

`http://127.0.0.1:8000/ledger` 列出全部 Facts 与各自的 Links，**按最新优先**排序
（`date` 降序，同日内 `id` 降序），因此刚写入的事实一定在最前面；每条 Link 显示
`编号 · 中文名`（如 `A5 · 字符串`），被取代的 Fact 单独标注并给出取代它的 id。

接口为 `GET /api/ledger/facts`，默认返回整个账本（上限 5000 条）。响应含
`fact_count` / `link_count` / `returned` / `has_more` / `order`：**若 `has_more` 为真，
说明账本超过上限而结果被截断**，页面会显示提示，调用方应改用 `limit` 分页，
不要静默当成全量。

另有 `GET /api/ledger/search`，参数与 `ledger_search` 一致（`skill_id` 必填，可选
`role`、`effect`、`independence`、`difficulty`、`difficulty_min`、`difficulty_max`、
`start_date`、`end_date`、`limit`），供页面的「按能力 / 难度检索」面板使用。
HTTP 侧 `difficulty` 与 `independence` 都同时接受**逗号分隔**（`difficulty=1500,2500`）
与**重复同名参数**（`difficulty=1500&difficulty=2500`）两种写法，两者可混用；
`difficulty_min` / `difficulty_max` 是单个整数，直接写数值即可。

## 数据目录结构

```
data/
├── records.json          # 刷题记录
├── solutions/            # 解题日志（Markdown）
│   ├── math/
│   │   ├── 2024-01-01-abc.md
│   │   └── ...
│   └── ...
├── solutions-meta.json   # 解题日志元数据
├── facts.json            # 能力证据库：原子事实（默认位置，可被 LEDGER_FACTS_FILE 覆盖）
├── ledger-links.json     # 能力证据库：资格判断（默认位置，可被 LEDGER_LINKS_FILE 覆盖）
└── prompt/
    └── every_problem.md  # 解题 prompt 模板
```

## 开发

```bash
# 启动开发服务器
uv run uvicorn main:app --reload --host 127.0.0.1 --port 8000 --workers 1

# 运行测试
uv run pytest
```

服务按单进程、单 worker 设计；不要使用多个 worker 同时写入 JSON 数据文件。
