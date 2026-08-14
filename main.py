from contextlib import asynccontextmanager
import json
from os import path
from datetime import datetime

from fastapi import BackgroundTasks, FastAPI
from fastapi.responses import HTMLResponse

from pydantic import BaseModel

from config import day_id, month_id, day_len, month_len, DATA_FILE, LUOGU_ID, QOJ_ID, CF_ID, HDU_ID, ATCODER_ID


class Record(BaseModel):
    time: int
    status: bool
    pid: str
    rid: str


records_cache = []
day_count_cache = [0] * day_len
day_sum_cache = [0] * day_len
month_count_cache = [0] * month_len
month_sum_cache = [0] * month_len
pass_count = 0


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
                day_count_cache[day_id(time)] += 1
                month_count_cache[month_id(time)] += 1
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
    with open(DATA_FILE, "r") as f:
        raw = json.load(f)
    unique = {r["rid"]: r for r in raw}.values()
    records_cache = sorted(unique, key=lambda r: r["time"])
    load_count_cache()
    yield
    with open(DATA_FILE, "w") as f:
        json.dump(records_cache, f)

app = FastAPI(lifespan=lifespan)


def save_to_disk_sync():
    with open(DATA_FILE, "w") as f:
        json.dump(records_cache, f, indent=2)


@app.get("/", response_class=HTMLResponse)
def index():
    return open(path.join("page", "index.html"), encoding="utf-8").read()


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
def push_record(record: list[Record], background_tasks: BackgroundTasks):
    global records_cache

    records_len = len(records_cache)
    temp_dict = {r["rid"]: r for r in records_cache}
    for rec in record:
        temp_dict[rec.rid] = rec.model_dump()
    records_cache = sorted(temp_dict.values(), key=lambda r: r["time"])
    if records_len < len(records_cache):
        background_tasks.add_task(load_count_cache)
        background_tasks.add_task(save_to_disk_sync)


@app.get("/api/day_count")
def day_count(start_date: str, end_date: str):
    return day_count_cache[day_id(start_date): day_id(end_date) + 1]


@app.get("/api/day_sum")
def day_sum(start_date: str, end_date: str):
    return day_sum_cache[day_id(start_date): day_id(end_date) + 1]


@app.get("/api/month_count")
def month_count(start_date: str, end_date: str):
    return month_count_cache[month_id(start_date): month_id(end_date) + 1]


@app.get("/api/month_sum")
def month_sum(start_date: str, end_date: str):
    return month_sum_cache[month_id(start_date): month_id(end_date) + 1]
