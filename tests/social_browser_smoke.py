"""Exercise real DOM selectors and browser lifecycle with intercepted fixtures.

No real account, site search or private profile is used by this test.
"""
import asyncio
import json
import tempfile
from pathlib import Path

from app import social, store


async def main():
    with tempfile.TemporaryDirectory(prefix="passage-social-test-") as tmp:
        store.DATA = Path(tmp)
        store.init()
        collector = social.BrowserCollector()
        try:
            for platform in ("xiaohongshu", "linkedin"):
                context = await collector.context(platform)
                if platform == "xiaohongshu":
                    html = '<section class="note-item"><a href="https://www.xiaohongshu.com/explore/abc123?xsec_token=fixture">测试申请经验</a><p>申请者的背景和项目体验，仅为测试资料。</p></section>'
                    detail = '<main class="note-container"><div id="detail-title">测试笔记</div><div id="detail-desc">' + '测试申请经验，完成先修课程并核实申请要求。' * 8 + '</div></main>'
                    url = "https://www.xiaohongshu.com/search_result?keyword=test"
                    note = "https://www.xiaohongshu.com/explore/abc123?xsec_token=fixture"
                    domain = ".xiaohongshu.com"
                else:
                    html = '<main><div class="reusable-search__result-container"><a href="https://www.linkedin.com/in/fixture">Fixture Person</a><p>Software engineer at Test Company</p></div></main>'
                    detail = '<main><h1>Fixture Person</h1><div class="text-body-medium break-words">Software engineer</div><section><h2>Experience</h2><p>Test Company, Software Engineer, 2024-2026</p></section><section><h2>Education</h2><p>Test University MSCS</p></section><section><h2>People you may know</h2><p>Unrelated person MUST NOT BE STORED</p></section></main>'
                    url = "https://www.linkedin.com/search/results/people/?keywords=test"
                    note = "https://www.linkedin.com/in/fixture"
                    domain = ".linkedin.com"
                async def respond(route):
                    content = html if "search" in route.request.url else detail
                    await route.fulfill(status=200, content_type="text/html", body=content)
                await context.route("**/*", respond)
                await context.add_cookies([{"name": social.PLATFORMS[platform]["cookie"], "value": "fixture-only-not-real", "domain": domain, "path": "/", "secure": True}])
                page = await collector.page(platform)
                await page.goto(note)
                status = await collector.check(platform)
                assert status["status"] == "ready", status
                social.update(platform, enabled=True, interval_seconds=0, daily_limit=10)
                results = await collector.collect(platform, url, "search")
                assert len(results) == 1 and results[0]["access"] == "snippet"
                assert "fixture-only-not-real" not in json.dumps(results)
                result = await collector.collect(platform, note, "read")
                assert result["access"] == "visible_text"
                assert "MUST NOT BE STORED" not in result["content"]
                await context.unroute("**/*", respond)
                async def challenge(route):
                    await route.fulfill(status=429, body="Too many requests")
                await context.route("**/*", challenge)
                try:
                    await collector.collect(platform, note, "read")
                    raise AssertionError("429 must stop collection")
                except ValueError:
                    assert social.settings(platform)["status"] == "challenge"
                await collector.disconnect(platform, forget=True)
                assert not (store.DATA / "browser-sessions" / platform).exists()
            print("Social browser smoke passed: both DOM adapters, isolated login sessions, search/read, private field exclusion, 429 pause, and session removal. Fixtures only.")
        finally:
            await collector.close()


if __name__ == "__main__":
    asyncio.run(main())
