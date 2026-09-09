"""Small public-source probe. Stores a report, not people's profiles.

Run: .venv/bin/python -m scripts.probe_sources
"""
import concurrent.futures
import json
import tempfile
import time
from pathlib import Path
from app import fetcher, store

TARGETS = [
    ("CMU 毕业去向", "https://www.cmu.edu/career/outcomes/index.html"),
    ("UW 毕业手册入口", "https://www.washington.edu/ceremony/commencement-program/"),
    ("一亩三分地公开首页", "https://www.1point3acres.com/"),
    ("小红书", "https://www.xiaohongshu.com/"),
    ("LinkedIn", "https://www.linkedin.com/"),
    ("英国政府学生签证", "https://www.gov.uk/student-visa"),
]


def probe(target):
    name, url = target
    start = time.monotonic()
    result = {"name": name, "url": url, "tested_at": store.now()}
    try:
        doc = fetcher.fetch(url)
        result.update(status="readable", title=doc["title"], characters=len(doc["content"]), access=doc["access"])
    except Exception as error:
        result.update(status="not_collected", reason=str(error)[:350])
    result["seconds"] = round(time.monotonic() - start, 2)
    return result


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="passage-probe-") as tmp:
        store.DATA = Path(tmp)
        store.init()
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(probe, TARGETS))
        report = {"note": "一次小样本探测，不代表稳定成功率。受限平台在网络请求前停止；未抓取个人名单。", "results": results}
        Path("docs").mkdir(exist_ok=True)
        Path("docs/source-probe.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps(report, ensure_ascii=False, indent=2))
