import asyncio
import json
import socket
import stat
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import agent, config, fetcher, skills, store
from app.main import app

HEADERS = {"X-Application-Helper": "1"}


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    for key in ("LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL", "TAVILY_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    store.init()
    fetcher._robots.clear()
    yield
    agent.TASKS.clear()


@pytest.fixture
def client():
    with TestClient(app, headers=HEADERS) as client:
        yield client


def test_profile_persistence_and_history(client):
    data = {"university": "测试大学", "gpa": "87/100", "targets": "测试项目"}
    assert client.put("/api/profile", json=data).status_code == 200
    assert client.get("/api/state").json()["profile"]["gpa"] == "87/100"
    client.put("/api/profile", json={**data, "gpa": "89/100"})
    assert store.all_of("profile_version")[0]["profile"]["gpa"] == "87/100"
    store.init()
    assert store.profile()["gpa"] == "89/100"


def test_secrets_are_write_only_and_can_be_cleared(client):
    settings = {**config.DEFAULTS, "model": "test-model", "api_key": "secret-model", "search_key": "secret-search"}
    result = client.put("/api/settings", json=settings)
    assert result.status_code == 200
    assert "secret-model" not in client.get("/api/state").text
    assert "secret-search" not in client.get("/api/export").text
    assert stat.S_IMODE((store.DATA / "settings.json").stat().st_mode) == 0o600
    del settings["api_key"]
    client.put("/api/settings", json=settings)
    assert config.read()["api_key"] == "secret-model"
    client.put("/api/settings", json={**settings, "api_key": ""})
    assert config.read()["api_key"] == ""


def test_cross_origin_and_rebinding_protection(client):
    assert client.put("/api/profile", json={}, headers={"Origin": "https://attacker.example"}).status_code == 403
    assert client.get("/api/state", headers={"Host": "attacker.example"}).status_code == 403
    response = client.post("/api/memories", json={"text": "example"}, headers={"X-Application-Helper": ""})
    assert response.status_code == 403
    assert client.get("/").headers["content-security-policy"].startswith("default-src 'self'")


def test_configuration_and_input_validation(client):
    for endpoint in ("http://example.com", "https://user:password@example.com", "https://example.com?key=secret"):
        assert client.put("/api/settings", json={"base_url": endpoint, "model": "test"}).status_code == 422
    assert client.post("/api/runs", json={"question": "分析目标项目"}).status_code == 409
    assert client.post("/api/evidence", json={"title": "短文", "content": "不够长"}).status_code == 400
    assert client.post("/api/evidence", json={"title": "链接", "content": "测试资料" * 10, "url": "javascript:alert(1)"}).status_code == 422


def test_import_library_and_memory_lifecycle(client):
    response = client.post("/api/evidence", json={"title": "招生条件", "content": "测试大学要求申请者完成数学与计算机先修课程。" * 3})
    assert response.status_code == 201
    ident = response.json()["id"]
    assert store.library("数学")[0]["id"] == ident
    assert store.library("%' OR 1=1 --") == []
    memory = client.post("/api/memories", json={"text": "希望两年制项目", "status": "suggested"}).json()
    client.put("/api/memories/" + memory["id"], json={"text": memory["text"], "status": "confirmed"})
    assert store.get(memory["id"])["status"] == "confirmed"
    client.delete("/api/memories/" + memory["id"])
    assert store.get(memory["id"]) is None
    client.delete("/api/evidence/" + ident)
    assert client.get("/api/evidence/" + ident).status_code == 404


@pytest.mark.parametrize("url", ["http://127.0.0.1/a", "http://[::1]/a", "http://10.0.0.1", "http://169.254.169.254", "file:///etc/passwd", "https://example.com:444", "http://user:pass@example.com"])
def test_reader_rejects_private_and_unsafe_urls(url):
    with pytest.raises(ValueError):
        fetcher.validate_url(url)


def test_dns_mixed_public_private_rejected():
    addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ("8.8.8.8", "127.0.0.1")]
    with patch("socket.getaddrinfo", return_value=addresses), pytest.raises(ValueError):
        fetcher.validate_url("https://public.example")


def test_manual_platforms_block_before_network():
    with patch("socket.getaddrinfo", side_effect=AssertionError("must not access network")):
        for url in ("https://www.linkedin.com/in/test", "https://www.xiaohongshu.com/explore/test", "https://www.reddit.com/r/test"):
            with pytest.raises(ValueError):
                fetcher.fetch(url)


def test_robots_fail_closed_and_rules():
    with patch.object(fetcher, "request", return_value=(200, {}, b"User-agent: *\nDisallow: /private", "")):
        fetcher.robots_allowed("https://example.com/public")
        with pytest.raises(ValueError):
            fetcher.robots_allowed("https://example.com/private/a")
    fetcher._robots.clear()
    with patch.object(fetcher, "request", return_value=(503, {}, b"", "")), pytest.raises(ValueError):
        fetcher.robots_allowed("https://example.com/public")


def test_extract_ignores_navigation_and_scripts():
    html = ("<html><title>Admissions</title><nav>irrelevant menu</nav><script>steal()</script>"
            "<article><h1>Official requirements</h1>" + "Math and computing prerequisite. " * 20 + "</article></html>")
    result = fetcher.extract(html.encode(), "text/html")
    assert "Math" in result["content"]
    assert "steal" not in result["content"] and "irrelevant" not in result["content"]


def test_short_directory_page_retains_followable_links():
    html = b'<html><title>Graduation</title><main>Download the official graduation ceremony program. <a href="/program.pdf">2026 Program PDF</a></main></html>'
    doc = fetcher.extract(html, "text/html", "https://example.com/commencement")
    assert doc["links"] == [{"title": "2026 Program PDF", "url": "https://example.com/program.pdf"}]


def test_web_cache_preserves_old_evidence_snapshots():
    body = b'<html><title>Program</title><main>' + b'Official admissions information. ' * 10 + b'</main></html>'
    with patch.object(fetcher, "request", return_value=(200, {"content-type": "text/html"}, body, "https://example.com")) as request:
        first = fetcher.fetch("https://example.com")
        second = fetcher.fetch("https://example.com")
        assert first["id"] == second["id"] and second["cached"]
        assert request.call_count == 1
        old = {**first, "fetched_at": "2020-01-01T00:00:00+00:00"}
        store.put("evidence", old, old["id"])
        third = fetcher.fetch("https://example.com")
        assert third["id"] != first["id"]
        assert store.get(first["id"])["fetched_at"].startswith("2020")


def call(name, arguments, ident="call-1"):
    return {"id": ident, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


def test_agent_tool_loop_evidence_and_privacy():
    evidence = store.put("evidence", {"title": "测试原文", "content": "完成数学先修课程。", "access": "user_import", "source_type": "import"})
    store.put("profile", {"university": "测试大学", "display_name": "不发送的姓名"}, "profile")
    run = agent.new_run("分析这个项目", [evidence["id"]])
    responses = [
        {"role": "assistant", "tool_calls": [call("load_skill", {"name": "bg-match"})]},
        {"role": "assistant", "tool_calls": [call("finish_research", {"summary": "需要先修课", "findings": [{"claim": "需完成数学课", "evidence_ids": [evidence["id"]], "caveat": "用户导入，待官方核实"}], "unknowns": ["适用申请季"], "next_steps": ["核实原文"]})]}
    ]
    async def fake_complete(settings, messages, tools):
        assert "不发送的姓名" not in json.dumps(messages, ensure_ascii=False)
        return responses.pop(0), {"total_tokens": 100}
    run["status"] = "running"
    with patch.object(agent.providers, "complete", fake_complete):
        asyncio.run(agent.run_loop(run, {**config.DEFAULTS, "model": "fake"}))
    saved = store.get(run["id"])
    assert saved["status"] == "completed" and saved["usage"]["total_tokens"] == 200
    assert saved["report"]["findings"][0]["evidence_ids"] == [evidence["id"]]
    assert "messages" not in agent.public(saved)


def test_fabricated_citations_rejected_and_budget_enforced():
    run = agent.new_run("测试")
    run["skills"] = ["bg-match"]
    report = {"summary": "测试", "findings": [{"claim": "假的事实", "evidence_ids": ["invented"], "caveat": ""}], "unknowns": [], "next_steps": []}
    with pytest.raises(ValueError, match="真实证据"):
        asyncio.run(agent.dispatch(run, config.DEFAULTS, "finish_research", report))
    run["search_count"] = config.DEFAULTS["max_searches"]
    with pytest.raises(ValueError, match="上限"):
        asyncio.run(agent.dispatch(run, config.DEFAULTS, "search_web", {"query": "test"}))


def test_memory_suggestions_idempotent_and_do_not_change_profile():
    run = agent.new_run("我想两年制项目")
    for _ in range(2):
        asyncio.run(agent.dispatch(run, config.DEFAULTS, "propose_memory", {"text": "倾向两年制项目"}))
    assert len(store.all_of("memory")) == 1
    assert store.all_of("memory")[0]["status"] == "suggested"
    assert not store.profile()


def test_checkpoint_recovery_drops_incomplete_tool_round():
    run = agent.new_run("test")
    run["status"] = "running"
    run["messages"] = [{"role": "user", "content": "test"}, {"role": "assistant", "tool_calls": [call("load_skill", {"name": "bg-match"}, "a"), call("search_library", {"query": "test"}, "b")]}, {"role": "tool", "tool_call_id": "a", "content": "ok"}]
    agent.checkpoint(run)
    agent.recover()
    saved = store.get(run["id"])
    assert saved["status"] == "interrupted"
    assert len(saved["messages"]) == 1
    assert len(run["messages"]) == 3


def test_cancelled_worker_preserves_sources():
    config.save({"model": "fixture-model"})
    run = agent.new_run("测试取消")
    async def wait_complete(*args, **kwargs):
        await asyncio.sleep(60)
    async def exercise():
        with patch.object(agent.providers, "complete", wait_complete):
            agent.start(run["id"])
            await asyncio.sleep(.03)
            task = agent.TASKS[run["id"]]
            task.cancel()
            await task
    asyncio.run(exercise())
    assert store.get(run["id"])["status"] == "cancelled"
    assert run["id"] not in agent.TASKS


def test_provider_error_is_actionable_without_secret_response():
    import httpx
    from app import providers
    class FakeClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
        async def post(self, *args, **kwargs):
            return httpx.Response(401, json={"detail": "echoed-secret"})
    with patch.object(providers.httpx, "AsyncClient", return_value=FakeClient()):
        with pytest.raises(providers.ProviderError) as error:
            asyncio.run(providers.post_json("https://example.com", {}, "private-key"))
        assert "401" in str(error.value)
        assert "secret" not in str(error.value) and "private-key" not in str(error.value)


def test_privacy_switch_disables_profile_and_memories():
    store.put("profile", {"university": "私有院校"}, "profile")
    store.put("memory", {"text": "私有偏好", "status": "confirmed"})
    run = agent.new_run("分析要求")
    agent.initialize(run, {**config.DEFAULTS, "profile_to_model": False})
    context = json.dumps(run["messages"], ensure_ascii=False)
    assert "私有院校" not in context and "私有偏好" not in context


def test_skill_catalog_discovery():
    catalog = skills.catalog()
    assert len(catalog) == 6
    assert "毕业候选" in skills.load("alumni-paths")["body"]
    with pytest.raises(ValueError):
        skills.load("../../etc/passwd")
