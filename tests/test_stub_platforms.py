"""Tests for intentionally-unimplemented platform stubs."""

import pytest

from agent_core.platforms import job51, maimai


@pytest.mark.asyncio
async def test_job51_search_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        await job51.Job51Adapter().search([], "")


@pytest.mark.asyncio
async def test_maimai_search_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        await maimai.MaimaiAdapter().search([], "")
