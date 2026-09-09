"""Isolated browser-test server. Never imported by the production application."""
import json
from app.main import app
from app import providers, store


async def fake_complete(settings, messages, tools=None):
    if not tools and "从简历中提取申请档案" in messages[0]["content"]:
        return {"content": json.dumps({"fields": {"university": {"value": "Example University", "evidence": "Example University"}, "experience": {"value": "Research assistant 2024", "evidence": "Research assistant 2024"}}})}, {}
    if not tools:
        return {"role": "assistant", "content": "OK"}, {"total_tokens": 2}
    called = [call["function"]["name"] for message in messages for call in message.get("tool_calls", [])]
    if "load_skill" not in called:
        return {"role": "assistant", "tool_calls": [{"id": "fixture-skill-" + skill, "type": "function", "function": {"name": "load_skill", "arguments": json.dumps({"name": skill})}} for skill in ("bg-match", "program-compare")]}, {"total_tokens": 100}
    elif "search_library" not in called:
        name, args = "search_library", {"query": "测试资料"}
    else:
        evidence = store.library("测试资料")[0]
        name, args = "finish_research", {"summary": "测试夹具：已完成端到端研究流程验证。", "findings": [{"claim": "测试资料中列出了数学先修要求。", "evidence_ids": [evidence["id"]], "caveat": "仅为测试数据，不构成申请建议。"}], "unknowns": ["尚未连接真实模型服务。"], "next_steps": ["配置真实服务后开展研究。"]}
    return {"role": "assistant", "tool_calls": [{"id": "fixture-" + str(len(messages)), "type": "function", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}]}, {"total_tokens": 100}


providers.complete = fake_complete
