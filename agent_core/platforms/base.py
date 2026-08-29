"""Platform adapter base + unified Job model for cross-platform normalization."""

import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime

from pydantic import BaseModel

logger = logging.getLogger(__name__)


def parse_salary_text(text: str | None) -> tuple[int | None, int | None]:
    """Unified salary-string parser shared by every platform adapter.

    Supports monthly salaries in K/k, 千, 万 and pure-number forms:
      "15K-25K" -> (15000, 25000); "8千-1.2万" -> (8000, 12000);
      "15000-25000" -> (15000, 25000); "20K" -> (20000, None).

    Conservative rules:
      - 面议 / empty / no digits -> (None, None)
      - daily/hourly forms (元/天, 元/时, 时薪...) -> (None, None), because they
        are not monthly and must never be compared against monthly min_salary
      - annual forms (万/年, 年薪) -> (None, None) for the same reason
    """
    if not text or not isinstance(text, str) or not text.strip():
        return None, None
    t = text.strip().lower().replace(" ", "")
    daily_hourly = ("元/天", "元/日", "/天", "/日", "元/时", "/时", "时薪", "日薪", "每天")
    if any(m in t for m in daily_hourly):
        return None, None
    if "年" in t and ("/年" in t or "年薪" in t):
        return None, None

    parts = [p for p in re.split(r"[-~—至]", t) if p]
    values: list[int] = []
    for part in parts:
        m = re.search(r"(\d+(?:\.\d+)?)", part)
        if not m:
            continue
        num = float(m.group(1))
        if "万" in part:
            num *= 10000
        elif "千" in part:
            num *= 1000
        elif "k" in part:
            num *= 1000
        elif "万" in t:
            # Range like "15-20万": the first segment has no unit, infer it
            # from the second segment's 万 multiplier.
            num *= 10000
        elif "千" in t:
            num *= 1000
        elif "k" in t:
            num *= 1000
        values.append(int(num))

    if not values:
        return None, None
    return values[0], values[1] if len(values) >= 2 else None


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
    education: str = ""  # Best-effort education requirement (platform-provided, not persisted)
    published_at: str = (
        ""  # Platform-reported publish/update time (ISO format), empty if unavailable
    )

    def dedup_key(self) -> str:
        return f"{self.company_normalized}|{_norm_title(self.title)}"

    def to_storage(self):
        from agent_core.storage.models import JobRecord

        return JobRecord(
            id=self.id,
            title=self.title,
            company=self.company,
            company_normalized=self.company_normalized,
            location=self.location,
            salary_min=self.salary_min,
            salary_max=self.salary_max,
            description=self.description,
            platforms=list(self.platforms),
            urls=dict(self.urls),
            direction=self.direction,
            first_seen=self.first_seen.isoformat() if self.first_seen else "",
            last_seen=self.last_seen.isoformat() if self.last_seen else "",
            is_new=self.is_new,
            security_id=self.security_id,
            lid=self.lid,
            published_at=self.published_at,
        )

    @classmethod
    def from_storage(cls, record) -> "Job":
        from agent_core.storage.models import JobRecord

        if isinstance(record, JobRecord):
            r = record
        else:
            r = JobRecord.from_db_row(dict(record))
        return cls(
            id=r.id,
            title=r.title,
            company=r.company,
            company_normalized=r.company_normalized,
            location=r.location,
            salary_min=r.salary_min,
            salary_max=r.salary_max,
            description=r.description,
            platforms=r.platforms,
            urls=r.urls,
            direction=r.direction,
            first_seen=datetime.fromisoformat(r.first_seen) if r.first_seen else None,
            last_seen=datetime.fromisoformat(r.last_seen) if r.last_seen else None,
            is_new=bool(r.is_new),
            security_id=getattr(r, "security_id", ""),
            lid=getattr(r, "lid", ""),
            published_at=getattr(r, "published_at", ""),
        )


class PlatformAdapter(ABC):
    name: str = ""

    @abstractmethod
    async def search(
        self,
        keywords: list[str],
        location: str,
        cookie_path: str | None = None,
        headless: bool = False,
        rate_limit_seconds: int | None = None,
    ) -> list[Job]: ...

    def normalize(self, raw_item: dict) -> Job:
        """Map the unified raw dict onto a Job tagged with this adapter.

        Shared by every adapter (platform-specific mapping happens in each
        adapter's ``_api_item_to_job``, which feeds this method the common
        shape: id/title/company/location/salary_min/salary_max/description/url).
        """
        company = raw_item.get("company", "") or ""
        return Job(
            id=raw_item.get("id", ""),
            title=raw_item.get("title", ""),
            company=company,
            # Keep a usable company key even when the job bypasses search._dedup
            # (e.g. direct adapter use). search._dedup still overwrites this with
            # the alias-normalized canonical name for full pipeline searches.
            company_normalized=raw_item.get("company_normalized") or company,
            location=raw_item.get("location", ""),
            salary_min=raw_item.get("salary_min"),
            salary_max=raw_item.get("salary_max"),
            description=raw_item.get("description", ""),
            platforms=[self.name],
            urls={self.name: raw_item.get("url", "")},
        )

    async def fetch_full_jd(self, job, cookie_path: str) -> str:
        """Default JD fetch for enterprise (public-API) adapters.

        Enterprise job pages are JS-rendered; Playwright extracts the JD from
        the detail URL in ``job.lid``. Returns the JD text (capped at 5000
        chars) or "" on error / missing URL.
        """
        lid = getattr(job, "lid", "") or ""
        if not lid.startswith("http"):
            return ""

        try:
            from agent_core.platforms.playwright_jd import fetch_jd_playwright

            jd = await fetch_jd_playwright(
                url=lid,
                platform=self.name,
                cookie_path=cookie_path,
                headless=True,
            )
            if jd and len(jd) > 50:
                logger.info(f"[{self.name}] Fetched JD for {lid[:60]}: {len(jd)} chars")
                return jd[:5000]
        except Exception as e:
            logger.warning(f"[{self.name}] Playwright JD fetch failed: {e}")

        return ""


# Pure-decoration words stripped from titles before dedup. Kept deliberately
# conservative: terms that change job identity (应届/实习/兼职/外包) are NOT
# listed — removing them would wrongly merge distinct roles.
_TITLE_NOISE_WORDS = (
    "急招",
    "急聘",
    "诚聘",
    "高薪",
    "双休",
    "周末双休",
    "五险一金",
    "包吃住",
    "包食宿",
    "包吃",
    "包住",
    "朝九晚六",
    "弹性工作",
    "福利好",
    "待遇优厚",
    "待遇好",
    "直招",
    "直聘",
)


def _norm_title(title: str) -> str:
    t = title.strip().lower()
    t = re.sub(r"[（(][^)）]*[)）]", "", t)
    for w in _TITLE_NOISE_WORDS:
        t = t.replace(w, "")
    t = re.sub(r"招聘$", "", t)  # trailing "招聘" is decoration, but "招聘专员" is a role
    t = re.sub(r"[，。、！？!?·•:：;；/|\\\-_~]+", "", t)
    t = re.sub(r"\s+", "", t)
    return t
