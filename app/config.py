import json
import os
import tempfile
from . import store

DEFAULTS = {
    "base_url": "https://api.deepseek.com", "model": "", "api_key": "",
    "search_provider": "tavily", "search_key": "", "max_steps": 24,
    "max_searches": 10, "max_pages": 20, "max_output_tokens": 6000,
    "max_total_tokens": 300000, "timeout_seconds": 600, "profile_to_model": True,
}
SECRET_FIELDS = ("api_key", "search_key")


def read():
    path = store.DATA / "settings.json"
    saved = json.loads(path.read_text()) if path.exists() else {}
    result = {**DEFAULTS, **saved}
    # Environment values are fallback-only; explicitly saved values take precedence.
    for key, env in (("api_key", "LLM_API_KEY"), ("search_key", "TAVILY_API_KEY"),
                     ("base_url", "LLM_BASE_URL"), ("model", "LLM_MODEL")):
        if key not in saved and os.environ.get(env):
            result[key] = os.environ[env]
    return result


def public():
    result = read()
    for key in SECRET_FIELDS:
        result[key + "_configured"] = bool(result.pop(key))
    return result


def save(changes):
    result = read()
    for key, value in changes.items():
        if key in DEFAULTS:
            result[key] = value
    store.DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = store.DATA / "settings.json"
    fd, temporary = tempfile.mkstemp(prefix="settings-", suffix=".tmp", dir=store.DATA)
    temp = temporary
    with os.fdopen(fd, "w") as file:
        json.dump(result, file, ensure_ascii=False)
    os.replace(temp, path)
    os.chmod(path, 0o600)
    return public()
