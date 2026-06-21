"""Platform adapter base + unified Job model for cross-platform normalization."""

import re
from abc import ABC, abstractmethod
from datetime import datetime

from pydantic import BaseModel


class Job(BaseModel):
    id: str = ""
    title: str = ""
    company: str = ""
    company_normalized: str = ""
    location: str = ""
    salary_min: int | None = None
    salary_max: int | None = None
    description: str = ""
    platforms: list[str] = []
    urls: dict[str, str] = {}
    direction: str = ""
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    is_new: bool = True
    security_id: str = ""
    lid: str = ""

    def dedup_key(self) -> str:
        return f"{self.company_normalized}|{_norm_title(self.title)}"

    def to_storage(self):
        from agent_core.storage.models import JobRecord
        return JobRecord(
            id=self.id, title=self.title, company=self.company,
            company_normalized=self.company_normalized, location=self.location,
            salary_min=self.salary_min, salary_max=self.salary_max,
            description=self.description, platforms=list(self.platforms),
            urls=dict(self.urls), direction=self.direction,
            first_seen=self.first_seen.isoformat() if self.first_seen else "",
            last_seen=self.last_seen.isoformat() if self.last_seen else "",
            is_new=self.is_new, security_id=self.security_id, lid=self.lid)

    @classmethod
    def from_storage(cls, record) -> "Job":
        from agent_core.storage.models import JobRecord
        if isinstance(record, JobRecord):
            r = record
        else:
            r = JobRecord.from_db_row(dict(record))
        return cls(id=r.id, title=r.title, company=r.company,
                   company_normalized=r.company_normalized, location=r.location,
                   salary_min=r.salary_min, salary_max=r.salary_max,
                   description=r.description, platforms=r.platforms,
                   urls=r.urls, direction=r.direction,
                   first_seen=datetime.fromisoformat(r.first_seen) if r.first_seen else None,
                   last_seen=datetime.fromisoformat(r.last_seen) if r.last_seen else None,
                   is_new=bool(r.is_new), security_id=getattr(r, 'security_id', ''),
                   lid=getattr(r, 'lid', ''))


class PlatformAdapter(ABC):
    name: str = ""

    @abstractmethod
    async def search(self, keywords: list[str], location: str,
                     cookie_path: str | None = None, headless: bool = False) -> list[Job]:
        ...

    @abstractmethod
    def normalize(self, raw_item: dict) -> Job:
        ...


def _norm_title(title: str) -> str:
    t = title.strip().lower()
    t = re.sub(r'[（(][^)）]*[)）]', '', t)
    t = re.sub(r'\s+', '', t)
    return t
