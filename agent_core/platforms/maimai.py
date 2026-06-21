"""maimai platform adapter (stub)."""

import logging

from agent_core.platforms.base import Job, PlatformAdapter

logger = logging.getLogger(__name__)


class MaimaiAdapter(PlatformAdapter):
    name = "maimai"

    async def search(self, keywords, location, cookie_path=None, headless=False):
        logger.info(f"[maimai] Search: {keywords}")
        raise NotImplementedError("maimai adapter not yet implemented")

    def normalize(self, raw):
        return Job(id=raw.get("id",""), title=raw.get("title",""),
                   company=raw.get("company",""), location=raw.get("location",""),
                   description=raw.get("description",""),
                   platforms=[self.name], urls={self.name:raw.get("url","")})
