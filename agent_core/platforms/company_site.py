"""Company-specific career site adapters."""

import logging

from agent_core.platforms.base import Job, PlatformAdapter

logger = logging.getLogger(__name__)

COMPANY_SITES = {
    "catl": {"name": "CATL/宁德时代", "url": "https://talent.catl.com/#/jobs"},
    "byd": {"name": "BYD/比亚迪", "url": "https://job.byd.com/"},
    "huawei": {"name": "华为制造", "url": "https://career.huawei.com/"},
    "haier": {"name": "海尔", "url": "https://maker.haier.net/"},
    "sany": {"name": "三一重工", "url": "https://campus.sany.com.cn/"},
}


class CompanySiteAdapter(PlatformAdapter):
    name = "company_site"

    def __init__(self, company_key):
        self.company_key = company_key

    async def search(self, keywords, location, cookie_path=None, headless=False):
        logger.info(f"[{self.company_key}] Search: {keywords}")
        raise NotImplementedError(f"{self.company_key} adapter not yet implemented")

    def normalize(self, raw):
        return Job(
            id=raw.get("id", ""),
            title=raw.get("title", ""),
            company=raw.get("company", ""),
            location=raw.get("location", ""),
            description=raw.get("description", ""),
            platforms=[self.name],
            urls={self.name: raw.get("url", "")},
        )
