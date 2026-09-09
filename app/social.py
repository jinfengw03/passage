"""Low-volume, visible-browser collection using isolated, user-owned sessions.

No password handling, private API calls, stealth patches or challenge solving.
All Playwright objects live on the application event loop.
"""
import asyncio
import hashlib
import os
from pathlib import Path
import re
import shutil
import time
from urllib.parse import quote, urlsplit, urlunsplit

from . import store

PLATFORMS = {
    "xiaohongshu": {"name": "小红书", "domains": ("xiaohongshu.com", "xhslink.com"),
                    "home": "https://www.xiaohongshu.com/explore", "cookie": "web_session"},
    "linkedin": {"name": "LinkedIn", "domains": ("linkedin.com",),
                 "home": "https://www.linkedin.com/login", "cookie": "li_at"},
}


def platform_for_url(url):
    try:
        p = urlsplit(url)
        if p.scheme != "https" or p.username or p.password or p.port not in (None, 443):
            return None
        for name, spec in PLATFORMS.items():
            if any(p.hostname == domain or (p.hostname or "").endswith("." + domain) for domain in spec["domains"]):
                return name
    except ValueError:
        pass
    return None


def validate_target(platform, url, search=False):
    if platform not in PLATFORMS or platform_for_url(url) != platform:
        raise ValueError("仅可读取所选平台的 HTTPS 页面")
    p = urlsplit(url)
    if search:
        expected = "/search_result" if platform == "xiaohongshu" else "/search/results/people/"
        if p.path.rstrip("/") != expected.rstrip("/"):
            raise ValueError("不是受支持的站内搜索页面")
    elif platform == "linkedin":
        if not re.fullmatch(r"/in/[^/]+/?", p.path):
            raise ValueError("LinkedIn 当前仅支持 /in/ 开头的职业主页，不读取消息、联系人或招聘后台")
    elif not (p.hostname in ("xhslink.com", "www.xhslink.com") or re.fullmatch(r"/(explore|discovery/item|search_result)/[A-Za-z0-9]+/?", p.path)):
        raise ValueError("请提供具体小红书笔记链接或 xhslink 分享链接")
    return url


def settings(platform):
    if platform not in PLATFORMS:
        raise ValueError("未知平台")
    saved = store.get("social-" + platform) or {}
    return {"platform": platform, "name": PLATFORMS[platform]["name"], "enabled": False,
            "interval_seconds": 20, "daily_limit": 30, "status": "disconnected", "message": "尚未建立独立登录会话", **saved}


def update(platform, **values):
    item = settings(platform)
    item.update(values)
    return store.put("social", item, "social-" + platform)


def statuses():
    result = []
    for platform in PLATFORMS:
        item = settings(platform)
        usage = store.get("social-usage-" + platform + "-" + store.now()[:10]) or {}
        result.append({key: item.get(key) for key in ("platform", "name", "enabled", "interval_seconds", "daily_limit", "status", "message", "updated_at")} | {"today_requests": usage.get("count", 0)})
    return result


def redacted(text):
    text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[联系邮箱已省略]", text)
    return re.sub(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)", "[联系电话已省略]", text)


def blocker(snapshot):
    url = snapshot.get("url", "").lower()
    text = snapshot.get("body", "").lower()
    if any(word in url for word in ("/checkpoint/", "/challenge/", "/captcha")) or snapshot.get("challenge") or any(word in text[:2500] for word in ("安全验证", "访问过于频繁", "操作过于频繁", "异常访问", "verify you are human", "unusual activity", "security verification", "temporarily restricted")):
        return "challenge", "平台要求验证或限制了访问，请在独立浏览器中手动处理，完成后点击检查登录状态"
    if any(word in url for word in ("/login", "/authwall", "/uas/")) or snapshot.get("login"):
        return "needs_login", "需要登录，请在独立浏览器中登录后检查状态"
    return None


# Only visible DOM is read. Script state, cookies and internal responses never
# enter extracted content. Contacts, messages, and recommendations are excluded.
SNAPSHOT_JS = r"""({platform, mode}) => {
 const visible = e => !!e && e.getBoundingClientRect().width > 0 && e.getBoundingClientRect().height > 0 && getComputedStyle(e).visibility !== 'hidden';
 const text = e => (e?.innerText || '').trim();
 const first = selectors => { for (const s of selectors) {const e=[...document.querySelectorAll(s)].find(visible); if(e)return e;} return null; };
 const all = s => [...document.querySelectorAll(s)].filter(visible);
 const result={url:location.href,title:document.title,body:text(document.body).slice(0,4000),
   challenge:!!first(['.captcha-container','[class*="captcha-box"]','iframe[src*="captcha"]','iframe[src*="challenge"]']),
   login:!!first(['.login-container','.login-modal','input[type="password"]']),items:[],content:'',comments:[]};
 if(mode==='search') {
  const rows=all(platform==='xiaohongshu'?'.note-item':'.reusable-search__result-container, .entity-result, [data-view-name="search-entity-result-universal-template"]');
  for(const row of rows){
   const link=[...row.querySelectorAll('a[href]')].find(a=>platform==='xiaohongshu'?/\/(explore|search_result)\/[a-zA-Z0-9]+/.test(a.pathname):/^\/in\/[^/]+\/?$/.test(a.pathname));
   if(link && text(row)) result.items.push({title:text(row).split('\n').filter(Boolean).slice(0,2).join(' · ').slice(0,200),content:text(row).slice(0,1800),url:link.href});
   if(result.items.length>=8)break;
  }
  result.empty = /暂无搜索结果|没有找到相关|no results found|no results matching/i.test(result.body);
 } else if(platform==='xiaohongshu') {
  const title=first(['#detail-title','.note-content .title','.note-container .title']);
  const desc=first(['#detail-desc','.note-content .desc','.note-scroller .desc']);
  result.title=text(title)||document.title;
  result.content=text(desc);
  result.comments=all('.comments-container .comment-item, .comments-el .comment-item').slice(0,10).map(e=>text(e).slice(0,1200));
 } else {
  const main=document.querySelector('main');
  const name=main?.querySelector('h1');
  const intro=main?.querySelector('.text-body-medium.break-words');
  const sections=[...(main?.querySelectorAll('section')||[])].filter(visible).filter(e=>{
   const heading=text(e.querySelector('h2'));
   return /^(experience|education|about|skills|licenses|certifications|projects|工作经历|工作經歷|经历|經歷|教育|简介|簡介|技能|项目|專案|证书)/i.test(heading);
  });
  result.title=text(name)||document.title;
  result.content=[text(name),text(intro),...sections.map(text)].filter(Boolean).join('\n\n');
 }
 return result;
}"""


class BrowserCollector:
    def __init__(self):
        self.playwright = None
        self.start_lock = asyncio.Lock()
        self.contexts = {}
        self.pages = {}
        self.locks = {name: asyncio.Lock() for name in PLATFORMS}

    async def context(self, platform):
        settings(platform)
        if platform in self.contexts:
            return self.contexts[platform]
        from playwright.async_api import async_playwright
        async with self.start_lock:
            if not self.playwright:
                self.playwright = await async_playwright().start()
        directory = store.DATA / "browser-sessions" / platform
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(directory.parent, 0o700)
        os.chmod(directory, 0o700)
        executable = os.environ.get("APPLICATION_HELPER_BROWSER")
        if not executable:
            executable = next((shutil.which(name) for name in ("microsoft-edge", "google-chrome", "chromium", "chromium-browser") if shutil.which(name)), None)
        try:
            context = await self.playwright.chromium.launch_persistent_context(
                str(directory), executable_path=executable, headless=False, viewport={"width": 1280, "height": 900},
                accept_downloads=False, timeout=20000)
        except Exception:
            raise ValueError("无法打开独立浏览器。请在桌面会话启动应用，并安装 Chromium/Edge；可用 APPLICATION_HELPER_BROWSER 指定浏览器") from None

        async def constrain(route):
            request = route.request
            parsed = urlsplit(request.url)
            if parsed.scheme not in ("https", "http", "data", "blob"):
                await route.abort()
                return
            host = (parsed.hostname or "").lower()
            if host in ("localhost", "127.0.0.1", "::1") or host.endswith((".local", ".localhost")):
                await route.abort()
                return
            try:
                import ipaddress
                if host and not ipaddress.ip_address(host).is_global:
                    await route.abort()
                    return
            except ValueError:
                pass
            if request.is_navigation_request() and platform_for_url(request.url) != platform:
                # Early popup navigation may have no frame yet; deny it until its scope is known.
                try:
                    is_main = request.frame == request.frame.page.main_frame
                except Exception:
                    is_main = True
                if is_main:
                    await route.abort()
                    return
            await route.continue_()

        await context.route("**/*", constrain)
        context.set_default_timeout(8000)
        self.contexts[platform] = context
        context.on("close", lambda _: (self.contexts.pop(platform, None), self.pages.pop(platform, None)))
        return context

    async def page(self, platform):
        context = await self.context(platform)
        page = self.pages.get(platform)
        if not page or page.is_closed():
            page = context.pages[0] if context.pages else await context.new_page()
            self.pages[platform] = page
        return page

    async def snapshot(self, platform, mode="read"):
        page = await self.page(platform)
        return await page.evaluate(SNAPSHOT_JS, {"platform": platform, "mode": mode})

    async def login(self, platform):
        async with self.locks[platform]:
            page = await self.page(platform)
            try:
                await page.goto(PLATFORMS[platform]["home"], wait_until="domcontentloaded", timeout=30000)
                await page.bring_to_front()
            except Exception:
                update(platform, status="connection_error", message="浏览器已打开，但平台页面加载失败；请检查网络后在窗口中重试")
                return self.public(platform)
            update(platform, status="awaiting_login", message="请在独立浏览器中完成登录，然后点击检查登录状态")
            return self.public(platform)

    def public(self, platform):
        return next(item for item in statuses() if item["platform"] == platform)

    async def check(self, platform):
        async with self.locks[platform]:
            if platform not in self.contexts:
                update(platform, status="disconnected", message="请先打开登录窗口；已有登录态会从本机加载")
                return self.public(platform)
            page = await self.page(platform)
            snapshot = await self.snapshot(platform)
            blocked = blocker(snapshot)
            cookies = await self.contexts[platform].cookies()
            has_session = any(cookie["name"] == PLATFORMS[platform]["cookie"] and cookie.get("value") and platform_for_url("https://" + cookie["domain"].lstrip(".")) == platform for cookie in cookies)
            if blocked:
                update(platform, status=blocked[0], message=blocked[1])
            elif has_session and platform_for_url(page.url) == platform:
                update(platform, status="ready", message="检测到登录态；具体搜索和正文访问将在采集时验证")
            else:
                update(platform, status="needs_login", message="尚未检测到登录态，请完成登录后再检查")
            return self.public(platform)

    async def disconnect(self, platform, forget=False):
        async with self.locks[platform]:
            context = self.contexts.pop(platform, None)
            self.pages.pop(platform, None)
            if context:
                await context.close()
            if forget:
                shutil.rmtree(store.DATA / "browser-sessions" / platform, ignore_errors=False) if (store.DATA / "browser-sessions" / platform).exists() else None
            update(platform, enabled=False, status="disconnected", message="登录态已从本机移除" if forget else "采集已关闭，登录态保留在本机")
            return self.public(platform)

    async def collect(self, platform, url, mode):
        validate_target(platform, url, search=mode == "search")
        async with self.locks[platform]:
            prefs = settings(platform)
            if not prefs["enabled"]:
                raise ValueError(f"请先在平台连接中启用 {PLATFORMS[platform]['name']} 自动采集")
            if prefs["status"] in ("challenge", "needs_login", "awaiting_login", "connection_error", "disconnected"):
                raise ValueError(prefs["message"])
            usage_id = "social-usage-" + platform + "-" + store.now()[:10]
            usage = store.get(usage_id) or {"count": 0, "last_request": 0}
            if usage["count"] >= prefs["daily_limit"]:
                raise ValueError("已达到该平台今日请求上限（UTC 日期），请明天再试或调整平台配置")
            wait = max(0, prefs["interval_seconds"] - (time.time() - usage["last_request"]))
            await asyncio.sleep(wait)
            # Recheck after waiting, before any page navigation.
            if not settings(platform)["enabled"]:
                raise ValueError("该平台采集已关闭")
            page = await self.page(platform)
            store.put("social_usage", {"count": usage["count"] + 1, "last_request": time.time()}, usage_id)
            try:
                response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                if response and response.status in (401, 403, 429):
                    update(platform, status="needs_login" if response.status == 401 else "challenge", message=f"平台返回 HTTP {response.status}，自动采集已暂停；请手动检查后重新检测状态")
                    raise ValueError(settings(platform)["message"])
                await page.wait_for_timeout(1800)
                if platform_for_url(page.url) != platform:
                    raise ValueError("页面跳转到平台外，已停止读取")
                snap = await self.snapshot(platform, mode)
                blocked = blocker(snap)
                if blocked:
                    update(platform, status=blocked[0], message=blocked[1])
                    raise ValueError(blocked[1])
                validate_target(platform, page.url, search=mode == "search")
                if mode == "search":
                    if not snap["items"] and not snap.get("empty"):
                        raise ValueError("未识别到搜索结果：页面可能尚未加载或平台结构已变化，未保存空结果")
                    results = []
                    seen = set()
                    for item in snap["items"][:8]:
                        if platform_for_url(item["url"]) != platform:
                            continue
                        key = urlunsplit((*urlsplit(item["url"])[:3], "", ""))
                        if key in seen:
                            continue
                        seen.add(key)
                        results.append(self.save(platform, item["url"], item["title"], item["content"], "snippet", []))
                    update(platform, status="ready", message=f"最近一次搜索读取 {len(results)} 条可见结果（最多 8 条）")
                    return results
                content = snap["content"].strip()
                if len(content) < 40:
                    raise ValueError("未识别到足够的笔记正文或职业资料；不把导航、推荐或登录页面当作正文")
                comments = snap.get("comments", [])
                if comments:
                    content += "\n\n[当前页面可见评论，非全部评论]\n" + "\n\n".join(comments)
                item = self.save(platform, page.url, snap["title"], content, "visible_text", [])
                update(platform, status="ready", message="最近一次正文读取成功；只覆盖当时已显示的内容")
                return item
            except ValueError:
                raise
            except Exception:
                update(platform, status="connection_error", message="平台页面读取失败或浏览器已关闭，请打开窗口检查网络及登录状态")
                raise ValueError(settings(platform)["message"]) from None

    def save(self, platform, url, title, content, access, links):
        if platform == "linkedin":
            p = urlsplit(url)
            url = urlunsplit((p.scheme, p.netloc, p.path, "", ""))
        return store.put("evidence", {"platform": platform, "title": redacted(title)[:300], "url": url,
            "content": redacted(content)[:30000], "access": access, "source_type": "browser", "links": links,
            "fetched_at": store.now(), "published_at": "", "truncated": len(content) > 30000,
            "coverage": "只读取当前页面已经显示的内容；未自动展开、翻页或收集全部评论"})

    async def close(self):
        for platform in list(self.contexts):
            context = self.contexts.pop(platform)
            await context.close()
        self.pages.clear()
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None


collector = BrowserCollector()


async def read(url):
    platform = platform_for_url(url)
    if platform:
        return await collector.collect(platform, url, "read")
    from . import fetcher
    return await asyncio.to_thread(fetcher.fetch, url)


async def search(platform, query):
    if platform not in PLATFORMS or not query.strip() or len(query) > 300:
        raise ValueError("请选择已支持的平台，并提供 1–300 字搜索词")
    url = ("https://www.xiaohongshu.com/search_result?keyword=" + quote(query) + "&source=web_explore_feed" if platform == "xiaohongshu" else "https://www.linkedin.com/search/results/people/?keywords=" + quote(query))
    return await collector.collect(platform, url, "search")


def recover():
    for platform in PLATFORMS:
        saved = store.get("social-" + platform)
        if saved and saved["status"] not in ("challenge", "needs_login", "connection_error", "disconnected"):
            update(platform, status="disconnected", message="服务重启，已保留登录态；请打开登录窗口并检查状态后继续")
