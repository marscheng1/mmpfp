from datetime import datetime
import os
import json

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")

# 从 config.json 读取 OJ 用户 ID 配置
_config_path = os.path.join(PROJECT_ROOT, "config.json")
with open(_config_path, "r", encoding="utf-8") as _f:
    _config = json.load(_f)

LUOGU_ID = _config["LUOGU_ID"]
QOJ_ID = _config["QOJ_ID"]
CF_ID = _config["CF_ID"]
HDU_ID = _config["HDU_ID"]
ATCODER_ID = _config["ATCODER_ID"]

day_start = datetime(2000, 1,  1)

day_len = 50000
month_len = 6000


def day_id(s: str | datetime):
    if isinstance(s, str):
        return (datetime.strptime(s, "%Y-%m-%d") - day_start).days
    else:
        return (s - day_start).days


def month_id(s: str | datetime):
    """s: yyyy-mm"""
    if isinstance(s, str):
        lst = s.split('-')
        return (int(lst[0]) - 2000) * 12 + int(lst[1]) - 1
    else:
        return (s.year - 2000) * 12 + s.month - 1


def _configured_path(key: str, default: str) -> str:
    configured_path = _config.get(key, default)
    if not os.path.isabs(configured_path):
        configured_path = os.path.join(PROJECT_ROOT, configured_path)
    return os.path.abspath(os.path.expanduser(configured_path))


DATA_FILE = _configured_path(
    "RECORDS_FILE", os.path.join(DATA_DIR, "records.json"))
_solutions_dir = _config.get(
    "SOLUTIONS_DIR", os.path.join(DATA_DIR, "solutions"))
if not os.path.isabs(_solutions_dir):
    _solutions_dir = os.path.join(PROJECT_ROOT, _solutions_dir)
SOLUTIONS_DIR = os.path.abspath(os.path.expanduser(_solutions_dir))
META_FILE = _configured_path(
    "SOLUTIONS_META_FILE", os.path.join(DATA_DIR, "solutions-meta.json"))
PROMPT_FILE = os.path.join(DATA_DIR, "prompt", "every_problem.md")
PAGE_DIR = os.path.join(PROJECT_ROOT, "page")
