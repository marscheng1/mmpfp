from datetime import datetime

LUOGU_ID = 1119066

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


DATA_FILE = "records.json"
