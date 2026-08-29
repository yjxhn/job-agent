"""Storage data models for jobs, applications, schedules."""

import json
from dataclasses import asdict, dataclass, field


@dataclass
class JobRecord:
    id: str = ""
    title: str = ""
    company: str = ""
    company_normalized: str = ""
    location: str = ""
    salary_min: int | None = None
    salary_max: int | None = None
    description: str = ""
    platforms: list[str] = field(default_factory=list)
    urls: dict[str, str] = field(default_factory=dict)
    direction: str = ""
    first_seen: str = ""
    last_seen: str = ""
    is_new: bool = True
    security_id: str = ""
    lid: str = ""
    published_at: str = ""

    def to_db_row(self) -> dict:
        d = asdict(self)
        d["platforms"] = json.dumps(self.platforms, ensure_ascii=False)
        d["urls"] = json.dumps(self.urls, ensure_ascii=False)
        d["is_new"] = 1 if self.is_new else 0
        return d

    @classmethod
    def from_db_row(cls, row: dict) -> "JobRecord":
        row = dict(row)
        # Tolerate extra columns added by later migrations (prescreen_score,
        # prescreen_confidence, user_flag, ...). The dataclass only declares
        # the fields it cares about; blindly passing the rest through to
        # __init__ raises TypeError on the first new column. Drop anything
        # the dataclass doesn't know about so a schema bump never breaks
        # loading existing rows.
        known = {f.name for f in __import__("dataclasses").fields(cls)}
        row = {k: v for k, v in row.items() if k in known}
        row["platforms"] = json.loads(row.get("platforms", "[]"))
        row["urls"] = json.loads(row.get("urls", "{}"))
        row["is_new"] = bool(row.get("is_new", 1))
        return cls(**row)


@dataclass
class ApplicationRecord:
    id: int = 0
    job_id: str = ""
    status: str = "已投递"
    resume_version: str = ""
    applied_at: str = ""
    updated_at: str = ""
    notes: str = ""


VALID_STATUSES = [
    "待投递",
    "已投递",
    "HR已读",
    "约面",
    "一面",
    "二面",
    "Offer",
    "入职",
    "已终止",
]
