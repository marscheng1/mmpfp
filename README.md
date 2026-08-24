# MMPFP — 刷题记录追踪 & MCP 知识库服务

## 项目说明

刷题记录追踪应用，支持多 OJ 平台（Luogu, QOJ, Codeforces, HDU, AtCoder）的刷题记录统计。内置 **MCP 知识库服务**，可将配置的题解目录暴露为 AI 可调用的工具。

## 快速开始

```bash
# 安装依赖
uv sync

# 复制配置文件
cp config.json.sample config.json

# 编辑 config.json 填入你的 OJ 用户 ID 和题解目录
# 启动服务
uv run uvicorn main:app --reload --host 127.0.0.1 --workers 1
```

`SOLUTIONS_DIR` 用于配置题解文件的实际位置。相对路径以项目根目录为基准，也可以填写绝对路径。例如，要让 API 直接保存到本地 OI 仓库：

```json
{
  "SOLUTIONS_DIR": "../OI/article/solutions"
}
```

这样，mmpfp 中的 `data/solutions/<path>.md` 仍是默认目录约定，但 API 实际会读写 OI 仓库中的 `article/solutions/<path>.md`。题解文件由 OI 仓库管理，不会进入 mmpfp 的提交；请确保 `data/solutions/.gitignore` 继续忽略本地默认目录，并在 OI 仓库中提交 API 产生的修改。

## MCP 知识库服务

项目使用 [FastAPI-MCP](https://github.com/sofa-fasto/fastapi-mcp) 自动将知识库 API 端点暴露为 MCP 工具。

### 端点

| 端点 | 说明 |
|------|------|
| `GET /mcp` | SSE 连接端点（MCP 传输层，MCP 客户端连接此端点） |
| `POST /mcp/messages/` | 消息端点（MCP 消息交换） |
| `GET /api/knowledge/list` | 知识库列表 REST API（Bearer Token 认证） |
| `GET /api/knowledge/read` | 知识库读取 REST API |
| `GET /api/knowledge/search` | 知识库搜索 REST API |

### 提供的工具（通过 MCP 协议）

| 工具 | 对应 API | 说明 |
|------|----------|------|
| `list_articles` | `GET /api/knowledge/list` | 列出知识库文章，支持按时间、最近 K 篇筛选 |
| `read_article` | `GET /api/knowledge/read` | 读取指定文章的 Markdown 内容 |
| `search_articles` | `GET /api/knowledge/search` | 搜索文章路径和正文 |

MCP 只暴露以上 3 个只读工具，不暴露前端写接口、记录接口或元数据接口。

### 认证方式

知识库接口使用 **Bearer Token** 认证。请先设置环境变量 `MCP_AUTH_TOKEN`；未设置时服务会为当前进程生成随机令牌，重启后失效，不应依赖该行为进行客户端配置。

MCP 客户端连接 SSE 时，在 HTTP 请求头中携带 `Authorization: Bearer <token>`，FastAPI-MCP 会将该令牌自动转发到内部 API 调用。

### API 参数说明

#### GET /api/knowledge/list

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `limit` | int | 否 | 限制返回数量（最近 K 篇） |
| `time_range` | string | 否 | 时间范围，格式 `"YYYY-MM-DD,YYYY-MM-DD"`，例如 `"2024-01-01,2024-12-31"`，`"2024-06-01,"` 表示之后 |
| `sort_by` | string | 否 | 排序字段：`created_at` / `modified_at` / `name`，默认 `created_at` |
| `order` | string | 否 | 排序方向：`asc` / `desc`，默认 `desc` |

`modified_at` 表示文件最近修改时间；`created_at` 在不同操作系统上可能具有不同语义。

#### GET /api/knowledge/read

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `file_path` | string | 是 | 相对路径，如 `"math/2024-01-01-abc.md"` |

#### GET /api/knowledge/search

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `query` | string | 是 | 搜索关键词（大小写不敏感，最长 200 个字符；同时搜索路径和正文） |
| `limit` | int | 否 | 最大返回数量，默认 10 |

搜索结果包含 `matched_in` 字段，值为 `path` 或 `content`。

### 配置 MCP 客户端

以 Claude Desktop 为例，在 `claude_desktop_config.json` 中配置：

```json
{
  "mcpServers": {
    "mmpfp-knowledge": {
      "type": "sse",
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Bearer <MCP_AUTH_TOKEN>"
      }
    }
  }
}
```

请将 `<MCP_AUTH_TOKEN>` 替换为服务启动时设置的 Token。

### 安全边界

本项目的解题日志编辑接口是为本机前端提供的，默认不单独要求 Bearer Token。因此服务必须绑定 `127.0.0.1`，不要使用 `--host 0.0.0.0` 直接暴露到局域网或公网。若需要远程访问，必须先为 `/api/solutions/*` 写接口增加认证，并使用 HTTPS 和访问控制。

编辑接口的请求体示例：

```json
{"path": "math/example.md", "content": "# 题解"}
```

`/api/solutions/mkdir` 和 `/api/solutions/delete` 使用 `{"path": "..."}`。删除不允许使用空路径或知识库根目录，路径不能越界或通过符号链接访问。

文件内容和搜索读取均限制为 2 MiB；搜索结果 `limit` 最大为 100。

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MCP_AUTH_TOKEN` | 无（建议显式设置） | MCP 知识库服务的 Bearer Token |

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