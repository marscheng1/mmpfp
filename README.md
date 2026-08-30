# MMPFP — 刷题记录追踪与解题日志

## 项目说明

刷题记录追踪应用，支持多 OJ 平台（Luogu、QOJ、Codeforces、HDU、AtCoder）的刷题记录统计，并提供本地解题日志编辑器。

## 快速开始

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
  "SOLUTIONS_META_FILE": "data/solutions-meta.json"
}
```

这样，mmpfp 中的 `data/solutions/<path>.md` 仍是默认目录约定，但 API 实际会读写 OI 仓库中的 `article/solutions/<path>.md`。题解文件由 OI 仓库管理，不会进入 mmpfp 的提交；请确保 `data/solutions/.gitignore` 继续忽略本地默认目录，并在 OI 仓库中提交 API 产生的修改。未配置这些字段时，会使用 `data/records.json`、`data/solutions` 和 `data/solutions-meta.json`。

## 安全边界

本项目的解题日志编辑接口是为本机前端提供的，默认不单独要求 Bearer Token。因此服务必须绑定 `127.0.0.1`，不要使用 `--host 0.0.0.0` 直接暴露到局域网或公网。若需要远程访问，必须先为 `/api/solutions/*` 写接口增加认证，并使用 HTTPS 和访问控制。

编辑接口的请求体示例：

```json
{"path": "math/example.md", "content": "# 题解"}
```

`/api/solutions/mkdir` 和 `/api/solutions/delete` 使用 `{"path": "..."}`。删除不允许使用空路径或知识库根目录，路径不能越界或通过符号链接访问。

文件内容限制为 2 MiB。

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
