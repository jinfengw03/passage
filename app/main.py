import asyncio
import base64
import binascii
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import agent, config, fetcher, providers, skills, store, social
from . import resume as resume_parser


@asynccontextmanager
async def lifespan(app):
    store.init()
    agent.recover()
    social.recover()
    yield
    tasks = list(agent.TASKS.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    await social.collector.close()


app = FastAPI(title="渡 · Passage", lifespan=lifespan, docs_url="/api/docs")
STATIC = Path(__file__).resolve().parent.parent / "static"


@app.middleware("http")
async def local_access(request: Request, call_next):
    host = urlsplit("http://" + request.headers.get("host", "")).hostname
    if host not in ("127.0.0.1", "localhost", "::1", "testserver"):
        return JSONResponse({"detail": "当前版本仅支持本机访问"}, status_code=403)
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        if request.headers.get("x-application-helper") != "1":
            return JSONResponse({"detail": "请求缺少本地应用标识"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "不允许跨站写入"}, status_code=403)
        try:
            size = int(request.headers.get("content-length", "0"))
        except ValueError:
            return JSONResponse({"detail": "无效请求长度"}, status_code=400)
        if size > 8 * 1024 * 1024:
            return JSONResponse({"detail": "上传超过 8 MB 限制"}, status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(ValueError)
async def validation_error(request, error):
    return JSONResponse({"detail": str(error)[:350]}, status_code=400)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Profile(Input):
    display_name: str = Field(default="", max_length=60)
    university: str = Field(default="", max_length=200)
    major: str = Field(default="", max_length=200)
    gpa: str = Field(default="", max_length=120)
    language: str = Field(default="", max_length=200)
    research: str = Field(default="", max_length=2500)
    experience: str = Field(default="", max_length=2500)
    targets: str = Field(default="", max_length=2000)
    degree: str = Field(default="", max_length=80)
    intake: str = Field(default="", max_length=80)
    budget: str = Field(default="", max_length=150)
    goals: str = Field(default="", max_length=2000)


class Settings(Input):
    base_url: str = Field(max_length=300)
    model: str = Field(max_length=200)
    api_key: str | None = Field(default=None, max_length=1000)
    search_key: str | None = Field(default=None, max_length=1000)
    search_provider: str = "tavily"
    max_steps: int = Field(default=12, ge=3, le=20)
    max_searches: int = Field(default=4, ge=0, le=10)
    max_pages: int = Field(default=8, ge=0, le=20)
    max_output_tokens: int = Field(default=2400, ge=500, le=8000)
    timeout_seconds: int = Field(default=240, ge=30, le=600)
    profile_to_model: bool = True

    @field_validator("base_url")
    @classmethod
    def endpoint(cls, value):
        p = urlsplit(value)
        if p.username or p.password or p.query or p.fragment or not p.hostname:
            raise ValueError("服务地址不能包含凭据、查询参数或片段")
        if p.scheme != "https" and not (p.scheme == "http" and p.hostname in ("localhost", "127.0.0.1", "::1")):
            raise ValueError("远程模型服务必须使用 HTTPS；本机模型可使用 HTTP")
        return value.rstrip("/")

    @field_validator("search_provider")
    @classmethod
    def search_name(cls, value):
        if value != "tavily":
            raise ValueError("当前版本支持 Tavily 搜索")
        return value


class Research(Input):
    question: str = Field(min_length=2, max_length=6000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=12)
    parent_id: str | None = None


class ImportDocument(Input):
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(default="", max_length=100000)
    url: str = Field(default="", max_length=2000)
    published_at: str = Field(default="", max_length=100)
    pdf_base64: str = Field(default="", max_length=7000000)

    @field_validator("url")
    @classmethod
    def link(cls, value):
        if value and (urlsplit(value).scheme not in ("http", "https") or not urlsplit(value).hostname):
            raise ValueError("来源链接应为 HTTP(S) 地址")
        return value


class Link(Input):
    url: str = Field(min_length=8, max_length=2000)


class Memory(Input):
    text: str = Field(min_length=1, max_length=1000)
    status: str = "confirmed"

    @field_validator("status")
    @classmethod
    def status_value(cls, value):
        if value not in ("confirmed", "suggested"):
            raise ValueError("无效记忆状态")
        return value


class Project(Input):
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(default="", max_length=2000)
    notes: str = Field(default="", max_length=4000)
    status: str = Field(default="研究中", max_length=40)


def require(ident, kind):
    item = store.get(ident)
    if not item or item["kind"] != kind:
        raise HTTPException(404, "记录不存在")
    return item


@app.get("/api/state")
def state():
    return {"profile": store.profile(), "settings": config.public(), "skills": [
        {k: v for k, v in skill.items() if k != "body"} for skill in skills.catalog()], "sources": fetcher.SOURCES,
        "runs": [agent.public(r) for r in store.all_of("run", 100)], "memories": store.all_of("memory"),
        "projects": store.all_of("project"), "evidence": [agent.source_view(e) for e in store.all_of("evidence")], "social": social.statuses()}


Platform = Literal["xiaohongshu", "linkedin"]


class SocialSettings(Input):
    enabled: bool
    interval_seconds: int = Field(default=20, ge=10, le=120)
    daily_limit: int = Field(default=30, ge=1, le=100)


class SocialSearch(Input):
    query: str = Field(min_length=1, max_length=300)


@app.put("/api/social/{platform}")
async def configure_social(platform: Platform, body: SocialSettings):
    if not body.enabled:
        # Immediately prevent queued work from navigating, even if another task holds the lock.
        social.update(platform, enabled=False)
    social.update(platform, **body.model_dump())
    return social.collector.public(platform)


@app.post("/api/social/{platform}/login")
async def login_social(platform: Platform):
    return await social.collector.login(platform)


@app.post("/api/social/{platform}/check")
async def check_social(platform: Platform):
    return await social.collector.check(platform)


@app.post("/api/social/{platform}/search")
async def search_social(platform: Platform, body: SocialSearch):
    results = await social.search(platform, body.query)
    return {"results": [agent.source_view(item) for item in results], "count": len(results)}


@app.post("/api/social/{platform}/read")
async def read_social(platform: Platform, body: Link):
    return agent.source_view(await social.collector.collect(platform, body.url, "read"))


@app.post("/api/social/{platform}/disconnect")
async def disconnect_social(platform: Platform):
    social.update(platform, enabled=False)
    return await social.collector.disconnect(platform)


@app.delete("/api/social/{platform}/session")
async def forget_social(platform: Platform):
    social.update(platform, enabled=False)
    return await social.collector.disconnect(platform, forget=True)


class ResumePDF(Input):
    pdf_base64: str = Field(min_length=1, max_length=7000000)


class ResumeText(Input):
    text: str = Field(min_length=30, max_length=30000)


@app.post("/api/profile/resume/extract")
async def extract_resume(body: ResumePDF):
    return await asyncio.to_thread(resume_parser.extract, body.pdf_base64)


@app.post("/api/profile/resume/analyze")
async def analyze_resume(body: ResumeText):
    return await resume_parser.analyze(body.text, Profile)


@app.put("/api/profile")
def save_profile(body: Profile):
    prior = store.profile()
    if prior:
        store.put("profile_version", {"profile": prior})
    return store.put("profile", body.model_dump(), "profile")


@app.put("/api/settings")
def save_settings(body: Settings):
    return config.save(body.model_dump(exclude_none=True))


@app.post("/api/settings/test")
async def test_settings():
    settings = config.read()
    if not settings["model"]:
        raise ValueError("请先保存模型名称")
    settings["max_output_tokens"] = 100
    message, usage = await providers.complete(settings, [{"role": "user", "content": "Reply with OK."}])
    return {"ok": True, "message": "模型连接成功。研究任务中的工具调用能力仍需实际验证。", "usage": usage}


@app.post("/api/settings/test-search")
async def test_search():
    results = await providers.search(config.read(), "graduate admissions university official")
    return {"ok": True, "message": f"搜索连接成功，返回 {len(results)} 条结果"}


@app.post("/api/runs", status_code=201)
async def create_run(body: Research):
    if not config.read()["model"]:
        raise HTTPException(409, "请先在设置中配置模型名称和服务连接")
    if len(agent.TASKS) >= 6:
        raise HTTPException(409, "研究队列已满")
    for ident in body.evidence_ids:
        require(ident, "evidence")
    if body.parent_id:
        require(body.parent_id, "run")
    run = agent.new_run(body.question, body.evidence_ids, body.parent_id)
    agent.start(run["id"])
    return agent.public(run)


@app.get("/api/runs/{ident}")
def get_run(ident: str):
    return agent.public(require(ident, "run"))


@app.post("/api/runs/{ident}/cancel")
async def cancel(ident: str):
    require(ident, "run")
    task = agent.TASKS.get(ident)
    if task:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        # A task cancelled before its coroutine starts cannot update itself.
        run = require(ident, "run")
        if run["status"] in ("running", "queued"):
            run["status"] = "cancelled"
            store.put("run", run, ident)
        agent.TASKS.pop(ident, None)
    return agent.public(require(ident, "run"))


@app.post("/api/runs/{ident}/resume")
async def resume(ident: str):
    run = require(ident, "run")
    if run["status"] not in ("interrupted", "failed", "cancelled"):
        raise HTTPException(409, "此状态的任务不能恢复")
    agent.start(ident)
    return {"ok": True}


@app.get("/api/runs/{ident}/export")
def export_run(ident: str):
    run = require(ident, "run")
    report = run.get("report") or {}
    text = f"# {run['question']}\n\n{report.get('summary', '尚未生成完整报告')}\n\n"
    for item in report.get("findings", []):
        text += f"- {item['claim']}\n  依据：{', '.join(item['evidence_ids'])}\n  局限：{item['caveat']}\n\n"
    for key, title in (("unknowns", "待核实"), ("next_steps", "下一步")):
        text += f"## {title}\n\n" + "\n".join("- " + x for x in report.get(key, [])) + "\n\n"
    text += "## 来源\n\n" + "\n".join(f"- {x['id']} · {x['title']} · {x.get('url', '')} · {x.get('access', '')} · 采集 {x.get('fetched_at', '')}" for x in run["sources"])
    return Response(text, media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="research-{ident[:8]}.md"'})


@app.delete("/api/runs/{ident}")
async def delete_run(ident: str):
    await cancel(ident)
    store.delete(ident)
    return {"ok": True}


@app.get("/api/evidence/{ident}")
def get_evidence(ident: str):
    return require(ident, "evidence")


@app.post("/api/evidence", status_code=201)
async def import_evidence(body: ImportDocument):
    content = body.content
    extra = {}
    if body.pdf_base64:
        try:
            raw = base64.b64decode(body.pdf_base64, validate=True)
        except binascii.Error as error:
            raise ValueError("无效文件编码") from error
        if len(raw) > fetcher.MAX_BYTES or not raw.startswith(b"%PDF"):
            raise ValueError("请选择 5 MB 以内的 PDF 文件")
        try:
            extra = await asyncio.to_thread(fetcher.extract, raw, "application/pdf")
        except Exception as error:
            raise ValueError("PDF 无法解析；请使用带文本层、未加密的 PDF，或粘贴文字") from error
        content = extra["content"]
    if len(content.strip()) < 20:
        raise ValueError("请提供至少 20 字的资料正文")
    item = store.put("evidence", {"title": body.title, "url": body.url, "content": content,
        "published_at": body.published_at, "fetched_at": store.now(), "source_type": "import",
        "access": "user_import", "truncated": extra.get("truncated", False)})
    return agent.source_view(item)


@app.post("/api/evidence/fetch")
async def fetch_evidence(body: Link):
    try:
        return agent.source_view(await social.read(body.url))
    except OSError as error:
        raise ValueError("连接网站失败，请检查网络或稍后重试") from error


@app.delete("/api/evidence/{ident}")
def delete_evidence(ident: str):
    require(ident, "evidence")
    store.delete(ident)
    return {"ok": True}


@app.post("/api/memories")
def add_memory(body: Memory):
    return store.put("memory", body.model_dump())


@app.put("/api/memories/{ident}")
def edit_memory(ident: str, body: Memory):
    previous = require(ident, "memory")
    return store.put("memory", {**previous, **body.model_dump()}, ident)


@app.delete("/api/memories/{ident}")
def delete_memory(ident: str):
    require(ident, "memory")
    store.delete(ident)
    return {"ok": True}


@app.post("/api/projects")
def add_project(body: Project):
    return store.put("project", body.model_dump())


@app.put("/api/projects/{ident}")
def edit_project(ident: str, body: Project):
    require(ident, "project")
    return store.put("project", body.model_dump(), ident)


@app.delete("/api/projects/{ident}")
def delete_project(ident: str):
    require(ident, "project")
    store.delete(ident)
    return {"ok": True}


@app.get("/api/export")
def export_data():
    data = {"version": 1, "exported_at": store.now(), "profile": store.profile(),
        "memories": store.all_of("memory", 10000), "projects": store.all_of("project", 10000),
        "evidence": store.all_of("evidence", 10000), "runs": [agent.public(r) for r in store.all_of("run", 10000)]}
    return JSONResponse(data, headers={"Content-Disposition": 'attachment; filename="passage-data.json"'})


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
