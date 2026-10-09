"""LLM 客户端：兼容 OpenAI Chat Completions 协议。

用户自带 API Key（BYOK），支持 DeepSeek / 智谱 GLM / OpenAI / Moonshot / SiliconFlow
以及任何 OpenAI 兼容端点（含本地 Ollama）。Key 保存在本地，并作为认证信息发送至配置的模型服务端点。
被墙服务商（Google Gemini / OpenRouter）自动探测本机代理端口并走代理。
"""
import json
import re
import threading
import time
from urllib.parse import urlparse

import requests


class LLMError(Exception):
    pass


_throttle_lock = threading.Lock()
_last_request_at = 0.0
MIN_INTERVAL = 2.0  # 全局请求节流：免费模型限流（如 GLM-Flash 并发 1）时防止打满

# 国内直连不通、需要走本机代理的服务商域名
PROXY_DOMAINS = ("generativelanguage.googleapis.com", "openrouter.ai")
_PROXY_PORTS = (7897, 7890, 10809, 1080)  # Clash Verge / Clash / v2rayN / 常见 SOCKS
_proxy_lock = threading.Lock()
_detected_proxy = None   # 探测结果缓存：dict 或 False（无可用代理）


def _proxies_for(url: str):
    """被墙域名返回本机代理配置（探测一次缓存结果），直连域名返回 None。"""
    global _detected_proxy
    host = (urlparse(url).hostname or "")
    if not any(d in host for d in PROXY_DOMAINS):
        return None
    with _proxy_lock:
        if _detected_proxy is None:
            _detected_proxy = False
            for port in _PROXY_PORTS:
                px = {"http": f"http://127.0.0.1:{port}", "https": f"http://127.0.0.1:{port}"}
                try:
                    r = requests.get("https://www.google.com/generate_204",
                                     proxies=px, timeout=4)
                    if r.status_code == 204:
                        _detected_proxy = px
                        print(f"[llm] 检测到本机代理 :{port}，被墙域名（Gemini/OpenRouter）将走代理")
                        break
                except Exception:
                    continue
            if _detected_proxy is False:
                print("[llm] 未检测到可用本机代理，被墙域名（Gemini/OpenRouter）将无法连接")
        return _detected_proxy or None


def _throttle():
    global _last_request_at
    with _throttle_lock:
        wait = _last_request_at + MIN_INTERVAL - time.time()
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.time()


def _headers(api_key: str):
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def chat(base_url, api_key, model, messages, temperature=0.3, max_tokens=None,
         stream=False, timeout=(15, 300), extra=None):
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {"model": model, "messages": messages, "temperature": temperature, "stream": stream}
    if max_tokens:
        payload["max_tokens"] = max_tokens
    if extra:
        payload.update(extra)  # 服务商特有参数（如智谱 thinking 开关）
    last_err = "请求失败"
    for attempt in range(5):  # 429/5xx 指数退避：5s → 10s → 20s → 40s → 80s
        _throttle()
        try:
            resp = requests.post(url, headers=_headers(api_key), json=payload,
                                 stream=stream, timeout=timeout,
                                 proxies=_proxies_for(url))
        except requests.RequestException as e:
            last_err = f"无法连接模型服务 {url}（{e}）"
            print(f"[llm] 请求异常重试（第 {attempt + 1}/5 次）：{last_err[:120]}")
            if attempt == 4:
                raise LLMError(last_err)
            time.sleep(3)
            continue
        if resp.status_code == 429:
            wait = 5 * (2 ** attempt)
            print(f"[llm] 触发限流(429)，{wait}s 后重试（第 {attempt + 1}/5 次）")
            time.sleep(wait)
            continue
        if resp.status_code >= 500:
            wait = 5 * (2 ** attempt)
            print(f"[llm] 服务端错误({resp.status_code})，{wait}s 后重试")
            time.sleep(wait)
            continue
        if resp.status_code != 200:
            detail = resp.text[:300]
            try:
                detail = resp.json().get("error", {}).get("message", detail)
            except Exception:
                pass
            raise LLMError(f"模型服务返回 {resp.status_code}：{detail}")
        return resp
    raise LLMError(f"{last_err}；已多次重试仍限流（429），免费模型请放慢节奏或稍后再试")


def chat_once(base_url, api_key, model, messages, **kw):
    resp = chat(base_url, api_key, model, messages, stream=False, **kw)
    try:
        return resp.json()["choices"][0]["message"]["content"] or ""
    except Exception:
        raise LLMError("模型返回格式无法解析")


def chat_stream(base_url, api_key, model, messages, **kw):
    """生成器：逐段产出文本增量（SSE 解析）。"""
    resp = chat(base_url, api_key, model, messages, stream=True, **kw)
    for raw in resp.iter_lines(decode_unicode=True):
        if not raw:
            continue
        if raw.startswith("data:"):
            raw = raw[5:].strip()
        if raw == "[DONE]":
            break
        try:
            obj = json.loads(raw)
            delta = obj["choices"][0].get("delta", {}).get("content")
            if delta:
                yield delta
        except Exception:
            continue


# ---------------- 课件翻译 ----------------
TRANSLATE_SYSTEM = (
    "你是专业的学术课件翻译引擎，负责把大学英文课件翻译成简体中文。要求："
    "1) 逐条翻译输入 JSON 数组中的每个字符串，输出等长的 JSON 数组；"
    "2) 术语准确，专业缩写首次出现时保留英文，如 ACID、CRM、API、ER Model；"
    "3) 译文简洁、符合课堂讲义风格；"
    "4) 数字、公式、代码、专有名词保持原样；"
    "5) 只输出 JSON 数组本身，不要任何解释或代码块标记。"
)


def translate_batch(base_url, api_key, model, texts):
    """把一批英文文本翻译为中文，返回等长列表。"""
    user = json.dumps(texts, ensure_ascii=False)
    messages = [{"role": "system", "content": TRANSLATE_SYSTEM},
                {"role": "user", "content": user}]
    # max_tokens=6000：聚合长批的输出上限保护，防止默认值截断 JSON 导致整批重试
    content = chat_once(base_url, api_key, model, messages, temperature=0.1, max_tokens=6000)
    arr = _parse_json_array(content)
    if arr is None:
        retry = [messages[0]["content"] + " 上次输出无法解析，请务必只输出合法 JSON 数组。",
                 {"role": "user", "content": user}]
        content = chat_once(base_url, api_key, model,
                            [{"role": "system", "content": retry[0]}, retry[1]], temperature=0.0)
        arr = _parse_json_array(content)
    if not isinstance(arr, list) or len(arr) != len(texts):
        raise LLMError(f"翻译结果解析失败（期望 {len(texts)} 条，模型未按要求输出）")
    return [str(x) if x is not None else s for x, s in zip(arr, texts)]


def _parse_json_array(content):
    if not content:
        return None
    m = re.search(r"\[.*\]", content, re.S)
    if not m:
        return None
    try:
        arr = json.loads(m.group(0))
        return arr if isinstance(arr, list) else None
    except Exception:
        return None


def test_connection(base_url, api_key, model):
    t0 = time.time()
    reply = chat_once(base_url, api_key, model,
                      [{"role": "user", "content": "连接测试，请只回复：OK"}],
                      max_tokens=10, temperature=0)
    return {"ok": True, "reply": reply.strip()[:50], "latency": round(time.time() - t0, 2)}
