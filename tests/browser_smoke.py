"""Browser integration tests against an isolated DB and fake model, plus UI screenshots."""
import json
import base64
from tests.test_resume import pdf
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "test-results"
RESULTS.mkdir(exist_ok=True)


def ready(url):
    for _ in range(60):
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except OSError:
            time.sleep(.2)
    raise RuntimeError("Test server did not start")


with tempfile.TemporaryDirectory(prefix="passage-browser-") as tmp:
    env = {**os.environ, "APPLICATION_HELPER_DATA": tmp}
    process = subprocess.Popen([str(ROOT / ".venv/bin/python"), "-m", "uvicorn", "tests.browser_app:app", "--host", "127.0.0.1", "--port", "8766"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ready("http://127.0.0.1:8766")
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get("BROWSER_PATH", "/usr/bin/microsoft-edge"), headless=True, args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
            page.goto("http://127.0.0.1:8766")
            page.get_by_text("把信息变成").wait_for()
            page.screenshot(path=str(RESULTS / "home-desktop.png"), full_page=True)

            def go(route):
                page.goto("http://127.0.0.1:8766/#" + route)
                expected = {"research": "把信息变成", "profile": "个人档案", "settings": "连接与设置", "library": "资料库", "memory": "长期记忆", "projects": "目标项目", "history": "研究记录", "skills": "Skills 与信息源", "social": "平台连接"}[route]
                page.locator("main h1").filter(has_text=expected).wait_for()
                page.wait_for_function("target => location.hash === '#' + target", arg=route)

            go("profile")
            page.locator('[name=university]').fill("测试大学")
            page.locator('[name=major]').fill("计算机科学")
            page.locator('[name=gpa]').fill("87/100")
            page.locator('[name=targets]').fill("测试硕士项目")
            page.get_by_role("button", name="保存档案").click()
            page.get_by_text("个人档案已保存", exact=True).wait_for()
            page.reload()
            assert page.locator('[name=gpa]').input_value() == "87/100"

            go("settings")
            page.locator('[name=model]').fill("fixture-model")
            page.locator('[name=api_key]').fill("fixture-secret")
            page.get_by_role("button", name="保存设置", exact=True).click()
            page.get_by_text("设置已保存", exact=True).wait_for()
            assert page.locator('[name=api_key]').input_value() == ""
            assert "fixture-secret" not in page.content()

            go("profile")
            page.get_by_role("button", name="导入简历 PDF", exact=True).click()
            page.locator('#resume-upload input[type=file]').set_input_files({"name":"fixture-resume.pdf","mimeType":"application/pdf","buffer":base64.b64decode(pdf())})
            page.get_by_role("button", name="提取文字", exact=True).click()
            page.locator('#resume-analyze').wait_for()
            assert 'GPA 3.8/4.0' in page.locator('#resume-analyze textarea').input_value()
            page.get_by_role("button", name="发送给模型并解析", exact=True).click()
            page.locator('#resume-review').wait_for()
            assert not page.locator('[name=select_university]').is_checked()
            assert page.locator('[name=select_experience]').is_checked()
            page.get_by_role("button", name="填入选中字段", exact=True).click()
            assert page.locator('#profile-form [name=university]').input_value() == '测试大学'
            assert page.locator('#profile-form [name=experience]').input_value() == 'Research assistant 2024'
            page.get_by_role("button", name="保存档案", exact=True).click()
            page.get_by_text("个人档案已保存", exact=True).wait_for()
            page.reload()
            assert page.locator('#profile-form [name=experience]').input_value() == 'Research assistant 2024'

            go("social")
            form = page.locator('.social-config-form[data-platform="xiaohongshu"]')
            form.locator('[name=interval_seconds]').fill("25")
            form.locator('[name=daily_limit]').fill("15")
            form.get_by_role("button", name="保存采集配置").click()
            page.get_by_text("平台采集配置已保存", exact=True).wait_for()
            page.reload()
            assert page.locator('.social-config-form[data-platform="xiaohongshu"] [name=daily_limit]').input_value() == "15"
            assert page.get_by_role("button", name="打开登录窗口", exact=True).count() == 2
            go("library")
            page.get_by_role("button", name="添加资料").click()
            page.locator('[name=title]').fill("测试资料：招生要求")
            page.locator('[name=content]').fill("测试资料明确要求数学先修课。" * 8 + '<script>window.injected=true</script>')
            page.get_by_role("button", name="保存资料", exact=True).click()
            page.get_by_text("资料已保存", exact=True).wait_for()
            page.get_by_role("button", name="测试资料：招生要求", exact=True).click()
            page.locator("dialog[open]").wait_for()
            assert page.evaluate("window.injected") is None
            page.get_by_role("button", name="关闭", exact=True).click()

            go("memory")
            page.get_by_role("button", name="添加记忆").click()
            page.locator('[name=text]').fill("测试偏好：两年制项目")
            page.get_by_role("button", name="保存记忆").click()
            page.get_by_text("测试偏好：两年制项目", exact=True).wait_for()

            go("projects")
            for name in ("测试大学 A · MSCS", "测试大学 B · MSE"):
                page.get_by_role("button", name="收藏项目").click()
                page.locator('[name=name]').fill(name)
                page.get_by_role("button", name="保存项目").click()
                page.get_by_role("heading", name=name, exact=True).wait_for()
            for checkbox in page.locator('[data-project]').all():
                checkbox.check()
            page.get_by_role("button", name="比较已选项目").click()
            page.locator("#research-form textarea").wait_for()
            assert "测试大学 A" in page.locator("#research-form textarea").input_value()
            page.get_by_role("button", name="开始研究").click()
            page.get_by_text("测试夹具：已完成端到端研究流程验证。", exact=True).wait_for(timeout=15000)
            assert page.locator("#cancel-run").is_hidden()
            assert page.locator("#resume-run").is_hidden()
            assert page.locator(".skill-pill").count() == 2
            page.screenshot(path=str(RESULTS / "research-desktop.png"), full_page=True)
            page.get_by_role("button", name="来源 1", exact=False).click()
            page.get_by_role("heading", name="测试资料：招生要求").wait_for()
            page.get_by_role("button", name="关闭", exact=True).click()
            with page.expect_download() as download:
                page.get_by_role("link", name="导出报告").click()
            assert download.value.suggested_filename.endswith(".md")

            page.locator("#research-form textarea").fill("继续核查测试资料")
            old_url = page.url
            page.get_by_role("button", name="开始研究").click()
            page.wait_for_function("old => location.href !== old", arg=old_url)
            page.get_by_text("测试夹具：已完成端到端研究流程验证。", exact=True).wait_for(timeout=15000)

            page.set_viewport_size({"width": 390, "height": 844})
            go("research")
            page.screenshot(path=str(RESULTS / "home-mobile.png"), full_page=True)
            for route in ("research", "profile", "library", "memory", "projects", "history", "skills", "settings", "social"):
                go(route)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"Mobile overflow: {route}"
            assert not errors, errors
            browser.close()
            (RESULTS / "browser-result.json").write_text(json.dumps({"passed": True, "scope": "Isolated browser flow with fake model; no real admission facts or paid provider validation", "console_errors": errors}, indent=2))
            print("Browser smoke passed: profile, settings, imports, XSS, memories, projects, multi-skill tool loop, citations, export, follow-up, mobile layouts.")
    finally:
        process.terminate()
        process.wait(timeout=10)
