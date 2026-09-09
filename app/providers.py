import asyncio
import httpx


class ProviderError(ValueError):
    pass


async def post_json(url, payload, key="", timeout=45):
    # Provider endpoints are explicitly configured by the local user; public-web
    # tools use the separate DNS-pinned reader and cannot call this function.
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
                response = await client.post(url, json=payload, headers=headers)
            if response.status_code in (429, 502, 503, 504) and attempt == 0:
                await asyncio.sleep(1)
                continue
            if response.status_code >= 400:
                descriptions = {401: "凭据无效", 403: "访问被拒绝", 404: "端点或模型不存在", 429: "限流或余额不足"}
                raise ProviderError(f"服务返回 HTTP {response.status_code}：{descriptions.get(response.status_code, '请求失败，请检查模型及接口配置')}")
            return response.json()
        except httpx.TimeoutException as error:
            raise ProviderError("服务响应超时，请稍后重试") from error
        except httpx.HTTPError as error:
            raise ProviderError("无法连接服务，请检查网络和服务地址") from error
        except (ValueError, UnicodeError) as error:
            if isinstance(error, ProviderError):
                raise
            raise ProviderError("服务返回了无效 JSON") from error


async def complete(settings, messages, tools=None):
    body = {"model": settings["model"], "messages": messages, "max_tokens": settings["max_output_tokens"]}
    if tools:
        body["tools"] = tools
    response = await post_json(settings["base_url"].rstrip("/") + "/chat/completions", body, settings["api_key"])
    try:
        return response["choices"][0]["message"], response.get("usage", {})
    except (KeyError, IndexError, TypeError) as error:
        raise ProviderError("模型响应不符合 Chat Completions 格式") from error


async def search(settings, query):
    if not settings["search_key"]:
        raise ProviderError("尚未配置 Tavily Search Key，可先使用资料库或直接读取公开链接")
    data = await post_json("https://api.tavily.com/search", {"query": query, "max_results": 5,
                          "search_depth": "basic", "include_answer": False, "include_raw_content": False}, settings["search_key"])
    return data.get("results", [])[:5]
