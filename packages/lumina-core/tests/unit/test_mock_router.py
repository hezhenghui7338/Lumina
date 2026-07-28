"""MockModelRouter tests."""
import pytest
from lumina_core.models.router import get_router
from tests.support.mock_router import MockModelRouter, load_json_fixture

@pytest.mark.asyncio
async def test_mock_router_summarize(mock_router, llm_fixtures_dir):
    router = get_router()
    assert isinstance(router, MockModelRouter)
    raw = await router.complete("summarize", profile="summarize", json_mode=True)
    data = load_json_fixture(llm_fixtures_dir / "summary_segment0.json")
    assert data["label"] in raw or "引子" in raw

@pytest.mark.asyncio
async def test_mock_router_chat(mock_router):
    raw = await get_router().chat([{"role": "user", "content": "hi"}], profile="chat")
    assert "answer" in raw or "主角" in raw
