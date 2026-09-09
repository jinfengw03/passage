import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app import agent, config, social, store
from app.main import app


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    store.init()


@pytest.mark.parametrize("url", ["https://linkedin.com.evil.example/in/a", "https://www.linkedin.com@evil.example/in/a", "http://www.linkedin.com/in/a", "https://www.linkedin.com:9999/in/a", "https://www.linkedin.com/messaging/", "https://www.linkedin.com/mynetwork/"])
def test_linkedin_scope(url):
    with pytest.raises(ValueError):
        social.validate_target("linkedin", url)


def test_supported_urls_and_shares():
    assert social.validate_target("linkedin", "https://www.linkedin.com/in/example/")
    assert social.validate_target("xiaohongshu", "https://www.xiaohongshu.com/explore/abc123?xsec_token=note-token")
    assert social.validate_target("xiaohongshu", "https://xhslink.com/a/abc")


def test_blockers_require_manual_recovery():
    assert social.blocker({"url": "https://www.linkedin.com/checkpoint/challenge", "body": ""})[0] == "challenge"
    assert social.blocker({"url": "https://www.xiaohongshu.com/explore", "body": "访问过于频繁"})[0] == "challenge"
    assert social.blocker({"url": "https://www.linkedin.com/login", "body": ""})[0] == "needs_login"
    assert social.blocker({"url": "https://www.linkedin.com/in/example", "body": "Software engineer, education"}) is None


def test_default_requires_connection_before_any_browser_launch():
    collector = social.BrowserCollector()
    with patch.object(collector, "page", new_callable=AsyncMock) as page:
        with pytest.raises(ValueError, match="启用"):
            asyncio.run(collector.collect("linkedin", "https://www.linkedin.com/in/example", "read"))
        page.assert_not_called()


def test_challenge_state_and_daily_limit_stop_before_navigation():
    collector = social.BrowserCollector()
    social.update("linkedin", enabled=True, status="challenge", message="手动验证")
    with patch.object(collector, "page", new_callable=AsyncMock) as page:
        with pytest.raises(ValueError, match="手动验证"):
            asyncio.run(collector.collect("linkedin", "https://www.linkedin.com/in/example", "read"))
        social.update("linkedin", status="ready", daily_limit=1)
        store.put("social_usage", {"count": 1, "last_request": 0}, "social-usage-linkedin-" + store.now()[:10])
        with pytest.raises(ValueError, match="今日请求上限"):
            asyncio.run(collector.collect("linkedin", "https://www.linkedin.com/in/example", "read"))
        page.assert_not_called()


def test_data_excludes_contact_details_and_has_coverage():
    item = social.collector.save("linkedin", "https://www.linkedin.com/in/example?tracking=abc", "Example", "Engineer, test@example.com, 13812345678", "visible_text", [])
    assert "test@example.com" not in item["content"]
    assert "13812345678" not in item["content"]
    assert item["url"] == "https://www.linkedin.com/in/example"
    assert item["coverage"] and item["access"] == "visible_text"


def test_configuration_routes_do_not_expose_sessions():
    with TestClient(app, headers={"X-Application-Helper": "1"}) as client:
        response = client.put("/api/social/linkedin", json={"enabled": True, "interval_seconds": 20, "daily_limit": 25})
        assert response.status_code == 200
        assert response.json()["enabled"]
        assert client.put("/api/social/linkedin", json={"enabled": True, "interval_seconds": 1}).status_code == 422
        assert client.post("/api/social/unknown/login").status_code == 422
        assert client.post("/api/social/linkedin/check").json()["status"] == "disconnected"
        assert "cookie" not in client.get("/api/state").text.lower()
        assert client.delete("/api/social/linkedin/session").status_code == 200
        assert not social.settings("linkedin")["enabled"]


def test_social_tool_uses_shared_research_budget():
    run = agent.new_run("查找测试校友")
    run["search_count"] = config.DEFAULTS["max_searches"]
    with pytest.raises(ValueError, match="上限"):
        asyncio.run(agent.dispatch(run, config.DEFAULTS, "search_social", {"platform": "linkedin", "query": "test"}))
    run["search_count"] = 0
    with pytest.raises(ValueError, match="允许范围"):
        asyncio.run(agent.dispatch(run, config.DEFAULTS, "search_social", {"platform": "untrusted", "query": "test"}))


def test_restart_does_not_silently_clear_challenge():
    social.update("linkedin", enabled=True, status="challenge", message="需要验证")
    social.update("xiaohongshu", enabled=True, status="ready")
    social.recover()
    assert social.settings("linkedin")["status"] == "challenge"
    assert social.settings("xiaohongshu")["status"] == "restorable"


def test_cookie_expiry_and_platform_scope():
    cookies = [
        {"name": "li_at", "value": "fixture", "domain": ".linkedin.com", "expires": -1},
        {"name": "expired", "domain": ".linkedin.com", "expires": 1},
        {"name": "foreign", "domain": ".example.org", "expires": -1},
    ]
    assert social.valid_cookies("linkedin", cookies) == cookies[:1]
    assert social.has_auth("linkedin", cookies)
    assert not social.has_auth("xiaohongshu", cookies)


def test_restart_retains_paused_and_disabled_states():
    social.update("linkedin", enabled=False, status="disconnected")
    social.update("xiaohongshu", enabled=True, status="needs_login")
    social.recover()
    assert not social.settings("linkedin")["enabled"]
    assert social.settings("linkedin")["status"] == "disconnected"
    assert social.settings("xiaohongshu")["status"] == "needs_login"
