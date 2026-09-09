"""Bounded public-web reader: DNS pinned connections, robots, host throttling."""
import hashlib
import http.client
import io
import ipaddress
import socket
import ssl
import threading
import time
import urllib.parse
import urllib.robotparser
from datetime import datetime, timezone

from bs4 import BeautifulSoup
from pypdf import PdfReader
from . import store

USER_AGENT = "ApplicationHelper/0.1 (personal research; robots-compliant)"
MAX_BYTES = 5 * 1024 * 1024
MANUAL = {
    "linkedin.com": "LinkedIn 使用独立浏览器采集通道，请在平台连接中登录并启用。",
    "xiaohongshu.com": "小红书使用独立浏览器采集通道，请在平台连接中登录并启用。",
    "xhslink.com": "小红书分享链接需通过已连接的浏览器采集通道读取。",
    "reddit.com": "Reddit 需要适用的数据访问授权，当前请使用授权资料导入。",
}
SOURCES = [
    {"name": "大学与政府官网", "domain": "按问题定向查找", "mode": "public", "description": "公开网页 / PDF · robots 校验 · 6 小时缓存"},
    {"name": "公开博客与实验室", "domain": "按问题定向查找", "mode": "public", "description": "正文提取 · 公开职业路径 · 来源追溯"},
    {"name": "一亩三分地", "domain": "1point3acres.com", "mode": "probe", "description": "仅尝试允许的公开页面；登录、积分及受限内容不读取"},
    {"name": "小红书", "domain": "xiaohongshu.com", "mode": "browser", "description": "平台连接中登录后，可搜索笔记并读取当前可见正文、评论；遇验证暂停"},
    {"name": "LinkedIn", "domain": "linkedin.com", "mode": "browser", "description": "平台连接中登录后，可搜索人物并读取职业主页；不读取消息与联系人"},
    {"name": "Reddit", "domain": "reddit.com", "mode": "manual", "description": MANUAL["reddit.com"]},
    {"name": "csapp", "domain": "待确认网址", "mode": "pending", "description": "名称尚未对应到用户确认的网站"},
]
_guard = threading.Lock()
_locks = {}
_last = {}
_robots = {}


def validate_url(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("仅支持无账户信息的 HTTP(S) 公网链接")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if port not in (80, 443):
            raise ValueError("网页采集仅允许 80/443 端口")
        addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
        ips = list(dict.fromkeys(row[4][0] for row in addresses))
        if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
            raise ValueError("不能采集本机、内网或保留地址")
        return parsed, ips, port
    except (socket.gaierror, UnicodeError) as error:
        raise ValueError("无法解析网站地址，请检查网络或网址") from error


def check_policy(host):
    for domain, explanation in MANUAL.items():
        if host == domain or host.endswith("." + domain):
            raise ValueError(explanation)


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, hostname, ip, port):
        super().__init__(hostname, port, timeout=15, context=ssl.create_default_context())
        self.ip = ip

    def connect(self):
        raw = socket.create_connection((self.ip, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


def request(url, max_bytes=MAX_BYTES, enforce_robots=False):
    for _ in range(5):
        parsed, ips, port = validate_url(url)
        check_policy(parsed.hostname)
        if enforce_robots:
            robots_allowed(url)
        with _guard:
            lock = _locks.setdefault(parsed.hostname, threading.Lock())
        with lock:
            time.sleep(max(0, 2 - (time.monotonic() - _last.get(parsed.hostname, 0))))
            _last[parsed.hostname] = time.monotonic()
            connection = PinnedHTTPS(parsed.hostname, ips[0], port) if parsed.scheme == "https" else http.client.HTTPConnection(ips[0], port, timeout=15)
            try:
                path = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
                connection.request("GET", path, headers={"Host": parsed.netloc, "User-Agent": USER_AGENT,
                                                          "Accept": "text/html,application/pdf,text/plain", "Accept-Encoding": "identity"})
                response = connection.getresponse()
                headers = dict((k.lower(), v) for k, v in response.getheaders())
                if response.status in (301, 302, 303, 307, 308):
                    url = urllib.parse.urljoin(url, headers.get("location", ""))
                    continue
                data = response.read(max_bytes + 1)
                if len(data) > max_bytes:
                    raise ValueError("文件超过 5 MB 采集上限")
                return response.status, headers, data, url
            finally:
                connection.close()
    raise ValueError("重定向次数过多")


def robots_allowed(url):
    parsed = urllib.parse.urlsplit(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    entry = _robots.get(origin)
    if not entry or time.monotonic() - entry[0] > 3600:
        status, _, body, _ = request(origin + "/robots.txt", max_bytes=512000)
        if status == 404:
            parser = None
        elif status == 200:
            if b"<html" in body.lower() or b"<!doctype" in body.lower():
                raise ValueError("robots.txt 返回验证页面，暂停采集")
            parser = urllib.robotparser.RobotFileParser()
            parser.parse(body.decode("utf-8", errors="replace").splitlines())
        else:
            raise ValueError(f"无法确认 robots.txt（HTTP {status}），暂停采集")
        _robots[origin] = (time.monotonic(), parser)
    parser = _robots[origin][1]
    if parser and not parser.can_fetch(USER_AGENT, url):
        raise ValueError("网站 robots.txt 不允许此页面的自动采集")
    if parser:
        delay = parser.crawl_delay(USER_AGENT) or 0
        if delay > 2:
            # Conservative: defer sites whose required delay exceeds this reader's window.
            raise ValueError(f"网站要求 {delay} 秒采集间隔，当前适配器暂停该来源")


def extract(data, content_type, url=""):
    if "pdf" in content_type or data.startswith(b"%PDF"):
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("暂不支持加密 PDF")
        pages = [f"[第 {i + 1} 页]\n{page.extract_text() or ''}" for i, page in enumerate(reader.pages[:40])]
        content = "\n\n".join(pages)
        if len(content.strip()) < 100:
            raise ValueError("PDF 缺少可提取文字，扫描件 OCR 尚未接入")
        return {"title": str((reader.metadata or {}).get("/Title") or "PDF 文档"), "content": content[:45000],
                "published_at": "", "truncated": len(reader.pages) > 40 or len(content) > 45000}
    if "text/plain" in content_type:
        return {"title": url or "文本资料", "content": data.decode("utf-8", errors="replace")[:45000], "published_at": "", "truncated": len(data) > 45000}
    if "html" not in content_type:
        raise ValueError("目前仅支持 HTML、文字和带文本层的 PDF")
    soup = BeautifulSoup(data, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else url
    date = soup.find("meta", attrs={"property": "article:published_time"}) or soup.find("meta", attrs={"name": "date"})
    published = date.get("content", "") if date else ""
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "form", "iframe"]):
        tag.decompose()
    body = soup.find("article") or soup.find("main") or soup.body or soup
    content = "\n".join(line.strip() for line in body.get_text("\n", strip=True).splitlines() if line.strip())
    links = []
    seen = set()
    for link in body.find_all("a", href=True):
        href = urllib.parse.urljoin(url, link["href"])
        label = link.get_text(" ", strip=True)
        if href.startswith(("https://", "http://")) and href not in seen and label:
            links.append({"title": label[:180], "url": href[:2000]})
            seen.add(href)
    if (len(content) < 120 and not (len(content) >= 35 and links)) or any(term in title.lower() for term in ("just a moment", "access denied", "security verification", "验证码", "安全验证")):
        raise ValueError("未获取有效正文：可能需要登录、验证或浏览器渲染")
    return {"title": title[:300], "content": content[:45000], "published_at": published[:100], "truncated": len(content) > 45000,
            "links": links[:40]}


def fetch(url):
    parsed = urllib.parse.urlsplit(url)
    check_policy(parsed.hostname or "")
    clean = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
    cache_id = "cache-" + hashlib.sha256(clean.encode()).hexdigest()[:24]
    cache = store.get(cache_id)
    previous = store.get(cache["evidence_id"]) if cache else None
    if previous:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(previous["fetched_at"])).total_seconds()
        if age < 21600:
            return {**previous, "cached": True}
    status, headers, body, final_url = request(clean, enforce_robots=True)
    if status != 200:
        raise ValueError(f"网页返回 HTTP {status}；不会重试登录或访问限制")
    item = extract(body, headers.get("content-type", ""), final_url)
    # Each capture is immutable: a later refresh must not alter old report evidence.
    captured = store.put("evidence", {**item, "url": final_url, "requested_url": clean, "fetched_at": store.now(),
                                     "source_type": "web", "access": "full_text", "cached": False})
    store.put("cache", {"evidence_id": captured["id"]}, cache_id)
    return captured
