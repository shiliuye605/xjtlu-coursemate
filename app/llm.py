"""LLM 客户端：兼容 OpenAI Chat Completions 协议。

用户自带 API Key（BYOK），支持 DeepSeek / 智谱 GLM / OpenAI / Moonshot / SiliconFlow
以及任何 OpenAI 兼容端点（含本地 Ollama）。Key 只在本地使用，不经过任何第三方。
被墙服务商（Google Gemini / OpenRouter）自动探测本机代理端口并走代理。
"""
import json
import hashlib
import re
import threading
import time
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import requests


class LLMError(Exception):
    pass


class TemporaryServiceError(LLMError):
    def __init__(self, message, retry_after=30, code=""):
        super().__init__(message)
        self.retry_after = retry_after
        self.code = str(code)


class RateLimitError(TemporaryServiceError):
    pass


class TranslationFormatError(LLMError):
    """A successful model response that can be retried with a smaller batch."""

    def __init__(self, message, partial=None):
        super().__init__(message)
        self.partial = partial or {}


_throttle_lock = threading.Lock()
_next_request_at = {}
_session_local = threading.local()
_glm_request_slot = threading.BoundedSemaphore(1)
_cooldown_lock = threading.Lock()
_cooldowns = {}
MIN_INTERVAL = 2.0  # 默认请求间隔；按接口独立调度，翻译可传入自己的策略

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


def _session():
    """Reuse HTTP connections without sharing Sessions between worker threads."""
    if not hasattr(_session_local, "session"):
        _session_local.session = requests.Session()
    return _session_local.session


def _throttle(endpoint="", min_interval=None):
    interval = MIN_INTERVAL if min_interval is None else max(0.0, min_interval)
    if interval == 0:
        return
    with _throttle_lock:
        now = time.monotonic()
        slot = max(now, _next_request_at.get(endpoint, 0.0))
        _next_request_at[endpoint] = slot + interval
    if slot > now:
        time.sleep(slot - now)


def _headers(api_key: str):
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _account_id(url, api_key, model):
    return (url.rstrip('/').lower(), hashlib.sha256(api_key.encode()).hexdigest(), model)


def _record_cooldown(account, minimum=0, initial=30, reason='模型暂时限流'):
    with _cooldown_lock:
        previous, failures = _cooldowns.get(account, (0, 0))[:2]
        failures += 1
        delay = max(minimum, min(180, initial * 2 ** min(failures - 1, 5)))
        until = max(previous, time.monotonic() + delay)
        _cooldowns[account] = (until, failures, reason)
        return until - time.monotonic()


def _connection_error(account, error):
    # A peer closing a connection is recoverable; certificate verification is not.
    if 'CERTIFICATE_VERIFY_FAILED' in str(error) or 'SSLCertVerificationError' in str(error):
        return LLMError('模型服务的安全证书验证失败，请检查系统时间、网络或代理证书设置')
    if isinstance(error, (requests.exceptions.InvalidURL, requests.exceptions.InvalidSchema, requests.exceptions.MissingSchema)):
        return LLMError('模型服务地址无效，请到设置中检查服务地址')
    return TemporaryServiceError(f'模型连接暂时中断（{type(error).__name__}）',
                                 retry_after=_record_cooldown(account, initial=10, reason='模型连接暂时中断'))


def _rate_limit(resp, account):
    """Do not confuse a temporary 429 with exhausted quota or invalid access."""
    try:
        error = resp.json().get('error', {})
        if not isinstance(error, dict):
            error = {'message': str(error)}
    except (ValueError, AttributeError, TypeError):
        error = {}
    code = str(error.get('code', ''))
    message = str(error.get('message') or '请求过于频繁，请稍后重试')[:300]
    permanent = {'1113', '1308', '1309', '1310', '1311', '1313', '1314',
                 '1315', '1316', '1317', '1318', '1319', '1320', '1321',
                 'insufficient_quota', 'billing_hard_limit_reached'}
    if code in permanent or error.get('type') == 'insufficient_quota':
        return LLMError(f'模型账户限制（{code or "quota"}）：{message}。请检查服务商账户额度或权限；已完成译文有缓存。')
    retry_after = 0.0
    value = getattr(resp, 'headers', {}).get('Retry-After', '')
    try:
        retry_after = max(0.0, float(value))
    except (ValueError, TypeError):
        try:
            retry_after = max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
        except (ValueError, TypeError, OverflowError):
            pass
    delay = _record_cooldown(account, minimum=retry_after)
    return RateLimitError(f'模型服务限流（429{", " + code if code else ""}）：{message}',
                          retry_after=delay, code=code)


def _wait_for_cooldown(account, on_wait=None, deadline=None):
    notified = None
    while True:
        with _cooldown_lock:
            state = _cooldowns.get(account, (0, 0, '模型服务暂时不可用'))
            until = state[0]
        remaining = until - time.monotonic()
        if remaining <= 0:
            return
        if deadline is not None and until > deadline:
            raise LLMError('模型服务持续受限或连接中断，超过自动等待 15 分钟的上限。已完成译文有缓存，请稍后继续或在设置中切换可用模型。')
        if on_wait and until != notified:
            reason = state[2] if len(state) > 2 else '模型服务暂时不可用'
            on_wait(remaining, reason + '，等待后自动继续；已完成译文已保存')
            notified = until
        time.sleep(min(remaining, 5))


def _post(url, api_key, on_wait=None, deadline=None, **kwargs):
    """Hold the free GLM account slot until the entire response is consumed.

    This also covers background course analysis/chat, preventing a newly
    uploaded document from repeatedly colliding with an ongoing analysis.
    """
    host = (urlparse(url).hostname or '').lower()
    model = kwargs['json']['model'].lower()
    limited = (host in ('open.bigmodel.cn','api.z.ai')
               and (model.startswith('glm-4.5') or model in ('glm-4-flash','glm-4-flash-250414')))
    if limited:
        if not _glm_request_slot.acquire(blocking=False):
            if on_wait:
                on_wait(0, '正在等待前一个模型请求完成，完成后自动继续')
            while not _glm_request_slot.acquire(timeout=1):
                if deadline is not None and time.monotonic() >= deadline:
                    raise LLMError('等待模型请求超时，已完成译文有缓存，请稍后继续')
    try:
        account = _account_id(url, api_key, kwargs['json']['model'])
        _wait_for_cooldown(account, on_wait, deadline)
        if on_wait:
            on_wait(0, '')
        resp = _session().post(url, headers=_headers(api_key), **kwargs)
    except BaseException:
        if limited:
            _glm_request_slot.release()
        raise
    if limited:
        original_close, close_lock, released = resp.close, threading.Lock(), False
        def close():
            nonlocal released
            with close_lock:
                if released:
                    return
                try:
                    original_close()
                finally:
                    released = True
                    _glm_request_slot.release()
        resp.close = close
    return resp


def chat(base_url, api_key, model, messages, temperature=0.3, max_tokens=None,
         stream=False, timeout=(15, 300), extra=None, min_interval=None,
         max_attempts=5, rate_limit_fail_fast=False, on_wait=None, deadline=None):
    url = base_url.rstrip("/") + "/chat/completions"
    account = _account_id(url, api_key, model)
    payload = {"model": model, "messages": messages, "temperature": temperature, "stream": stream}
    if max_tokens:
        payload["max_tokens"] = max_tokens
    if extra:
        payload.update(extra)  # 服务商特有参数（如智谱 thinking 开关）
    last_err = "请求失败"
    attempts = max(1, max_attempts)
    for attempt in range(attempts):
        _throttle(base_url.rstrip("/").lower(), min_interval)
        try:
            resp = _post(url, api_key, on_wait=on_wait, deadline=deadline,
                         json=payload, stream=stream, timeout=timeout,
                         proxies=_proxies_for(url))
        except requests.RequestException as e:
            exc = _connection_error(account, e)
            print(f"[llm] 请求异常（第 {attempt + 1}/{attempts} 次）：{exc}")
            if not isinstance(exc, TemporaryServiceError) or rate_limit_fail_fast or attempt == attempts - 1:
                raise exc from e
            continue
        if resp.status_code == 429:
            try:
                # Register the cooldown before close() releases the account slot.
                exc = _rate_limit(resp, account)
            finally:
                resp.close()
            if not isinstance(exc, RateLimitError) or rate_limit_fail_fast or attempt == attempts - 1:
                raise exc
            print(f'[llm] {exc}，{exc.retry_after:.0f}s 后自动重试')
            continue
        if resp.status_code >= 500:
            last_err = f"模型服务返回 {resp.status_code}"
            delay = _record_cooldown(account, initial=10, reason='模型服务暂时不可用')
            resp.close()
            if rate_limit_fail_fast or attempt == attempts - 1:
                raise TemporaryServiceError(last_err, retry_after=delay)
            print(f"[llm] {last_err}，{delay:.0f}s 后重试（第 {attempt + 1}/{attempts} 次）")
            continue
        if resp.status_code != 200:
            detail = resp.text[:300]
            try:
                detail = resp.json().get("error", {}).get("message", detail)
            except Exception:
                pass
            resp.close()
            raise LLMError(f"模型服务返回 {resp.status_code}：{detail}")
        with _cooldown_lock:
            _cooldowns.pop(account, None)
        return resp
    raise LLMError(f"{last_err}；重试 {attempts} 次后仍未恢复，请稍后重试")


def chat_once(base_url, api_key, model, messages, **kw):
    resp = chat(base_url, api_key, model, messages, stream=False, **kw)
    try:
        return resp.json()["choices"][0]["message"]["content"] or ""
    except Exception:
        raise LLMError("模型返回格式无法解析")
    finally:
        resp.close()


def chat_stream(base_url, api_key, model, messages, **kw):
    """生成器：逐段产出文本增量（SSE 解析）。"""
    resp = chat(base_url, api_key, model, messages, stream=True, **kw)
    try:
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw:
                continue
            if raw.startswith("data:"):
                raw = raw[5:].strip()
            if raw == "[DONE]":
                # Consume the HTTP terminator so Requests can reuse this socket.
                continue
            try:
                obj = json.loads(raw)
                delta = obj["choices"][0].get("delta", {}).get("content")
                if delta:
                    yield delta
            except Exception:
                continue
    finally:
        resp.close()


# ---------------- 课件翻译 ----------------
TRANSLATE_SYSTEM = (
    "你是逐条课件翻译引擎。输入 JSON 对象，输出相同键的 JSON 对象。"
    "每个键是不可更改的文本ID，不是序号；每个值独立翻译为完整的简体中文字符串。"
    "绝对不要合并不同ID下的文本；即使某个文本像上一条的续句，也必须在自己的ID下单独翻译。"
    "输出必须包含输入的全部ID，键必须原样复制，不能重新编号。"
    "译文简洁，保留数字、公式、代码、专有名词和专业缩写。"
    "结合本批次主题使用准确的中文学术术语，例如数据表中的Field译为字段，需求验证中的Realism译为现实可行性。"
    "有些标题使用逐字母空格排版，先还原词语再翻译，例如IN DEPTH表示深入解析。"
    "不要扩写、解释或添加内容。一个条目含多项列表时，译文仍为一个字符串，内部使用\\n换行。"
    "译文内引用使用中文引号“”，不要使用半角双引号。"
    "只输出紧凑的合法JSON对象，不缩进。"
)


def _translation_ids(texts):
    """Preserve the established opaque IDs and explicitly handle a collision."""
    ids = ['t' + hashlib.sha256(text.encode('utf-8')).hexdigest()[:8] for text in texts]
    if len(set(ids)) != len(set(texts)):
        ids = ['t' + hashlib.sha256(text.encode('utf-8')).hexdigest() for text in texts]
    return ids


def translate_batch(base_url, api_key, model, texts, request_options=None):
    """Match translations by opaque content ID, never by model output position."""
    ids = _translation_ids(texts)
    # Ordinary spaces reduce NBSP tokenization costs without changing cache identity.
    # Hash order prevents neighboring slide fragments from being mistaken for
    # one sentence. Restore layout order strictly through the original ID map.
    user = json.dumps({i: t.replace('\u00a0', ' ') for i, t in zip(ids, texts)}, ensure_ascii=False,
                      separators=(',', ':'), sort_keys=True)
    messages = [{"role": "system", "content": TRANSLATE_SYSTEM},
                {"role": "user", "content": user}]
    options = dict(request_options or {})
    on_response = options.pop('on_response', None)
    host = (urlparse(base_url).hostname or "").lower()
    if host in ("open.bigmodel.cn", "api.z.ai") and model.lower().startswith("glm-4.5"):
        options["extra"] = {**options.get("extra", {}), "thinking": {"type": "disabled"}}
    if host in ("open.bigmodel.cn", "api.z.ai"):
        options["extra"] = {**options.get("extra", {}), "response_format": {"type": "json_object"}}
    started = time.monotonic()
    output_budget = min(6000, max(512, sum(map(len, texts)) + len(texts) * 24 + 128))
    content = _translation_content(base_url, api_key, model, messages, temperature=0,
                                   max_tokens=output_budget, **options)
    if on_response:
        on_response(user, content)
    values = _parse_json_object(content, allow_partial=True, expected_ids=ids)
    partial = {}
    if isinstance(values, dict):
        partial = {index: values[i] for index, i in enumerate(ids)
                   if isinstance(values.get(i), str) and values[i].strip()}
    print(f"[translate] 批次 {len(texts)} 条 / {sum(map(len, texts))} 字符，"
          f"{time.monotonic() - started:.2f}s，匹配 {len(partial)}/{len(texts)}")
    if len(partial) == len(texts):
        return [partial[i] for i in range(len(texts))]
    raise TranslationFormatError(f"翻译ID匹配不完整（{len(partial)}/{len(texts)}）", partial)


def _translation_content(base_url, api_key, model, messages, **options):
    """Bound long generations and retain completed entries instead of discarding a batch."""
    timeout = options.pop('timeout', (15, 90))
    if isinstance(timeout, tuple):
        timeout = (timeout[0], min(timeout[1], 90))
    on_metrics = options.pop('on_metrics', None)
    requested = time.perf_counter()
    resp = chat(base_url, api_key, model, messages, stream=True, timeout=timeout, **options)
    started = time.monotonic()  # Waiting for another local task is not model generation time.
    headers_at, first_text_at = time.perf_counter(), None
    usage = {}
    parts = []
    try:
        resp.encoding = 'utf-8'
        for raw in resp.iter_lines(decode_unicode=True):
            if time.monotonic() - started > 150:
                break
            if not raw or not raw.startswith('data:'):
                continue
            raw = raw[5:].strip()
            if raw == '[DONE]':
                continue  # Read through the HTTP terminator for connection reuse.
            try:
                obj = json.loads(raw)
                if isinstance(obj.get('usage'), dict):
                    usage = obj['usage']
                delta = obj['choices'][0].get('delta', {}).get('content')
                if delta:
                    if first_text_at is None:
                        first_text_at = time.perf_counter()
                    parts.append(delta)
            except (ValueError, KeyError, IndexError):
                continue
    except requests.RequestException as exc:
        if not parts:
            account = _account_id(base_url.rstrip('/') + '/chat/completions', api_key, model)
            raise _connection_error(account, exc) from exc
    finally:
        resp.close()
        elapsed = time.perf_counter() - requested
        metrics = {'seconds': round(elapsed, 3), 'headers_seconds': round(headers_at - requested, 3),
                   'first_text_seconds': round(first_text_at - requested, 3) if first_text_at else None,
                   'output_characters': sum(map(len, parts)), 'usage': usage}
        if on_metrics:
            on_metrics(metrics)
        print(f'[llm] 翻译首字 {metrics["first_text_seconds"]}s，总请求 {metrics["seconds"]}s')
    return ''.join(parts)


def _parse_json_object(content, allow_partial=False, expected_ids=None):
    if not isinstance(content, str):
        return None
    # Accept Markdown fences/leading prose, but reject duplicate IDs.
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate translation ID')
            result[key] = value
        return result
    try:
        start = content.index('{')
        value, _ = json.JSONDecoder(object_pairs_hook=unique).raw_decode(content[start:])
        return value if isinstance(value, dict) else None
    except (ValueError, TypeError):
        if not allow_partial:
            return None
    if expected_ids:
        return _recover_id_entries(content, set(expected_ids))
    # A stream may end mid-object. Reuse only fully decoded ID/value pairs.
    result = {}
    try:
        pos = content.index('{') + 1
        result, decoder = {}, json.JSONDecoder()
        while pos < len(content):
            while pos < len(content) and content[pos] in ' \r\n\t,':
                pos += 1
            key, end = decoder.raw_decode(content[pos:])
            pos += end
            while pos < len(content) and content[pos].isspace():
                pos += 1
            if content[pos] != ':' or not isinstance(key, str) or key in result:
                return None
            pos += 1
            while pos < len(content) and content[pos].isspace():
                pos += 1
            value, end = decoder.raw_decode(content[pos:])
            pos += end
            boundary = pos
            while boundary < len(content) and content[boundary].isspace():
                boundary += 1
            if boundary < len(content) and content[boundary] not in ',}':
                break  # An unescaped quote inside a string is not a complete value.
            result[key] = value
    except (ValueError, TypeError, IndexError):
        pass
    return result or None


def _recover_id_entries(content, expected_ids):
    """Recover quote mistakes only inside fixed, explicit ID boundaries.

    Some GLM responses contain unescaped quotation marks even in JSON mode.
    Do not treat the text before the first inner quote as a full translation.
    """
    page_ids=[re.escape(key) for key in expected_ids if re.fullmatch(r'p\d+(?:s\d+)?',key)]
    pattern=r't[0-9a-f]{8,64}'+('|'+'|'.join(sorted(page_ids,key=len,reverse=True)) if page_ids else '')
    markers = list(re.finditer(r'(?:\{\s*|,\s*)"('+pattern+r')"\s*:\s*', content))
    result, seen = {}, set()
    for index, marker in enumerate(markers):
        key = marker.group(1)
        if key in seen:
            return None
        seen.add(key)
        if key not in expected_ids:
            continue
        end = markers[index + 1].start() if index + 1 < len(markers) else len(content)
        raw = content[marker.end():end].strip()
        if index + 1 == len(markers):
            raw = re.sub(r'\s*}\s*(?:```\s*)?$', '', raw).rstrip()
        if len(raw) < 2 or not raw.startswith('"') or not raw.endswith('"'):
            continue  # An interrupted last string is never a complete entry.
        try:
            value = json.loads(raw)
        except ValueError:
            escaped, slash = [], False
            for char in raw[1:-1]:
                if slash:
                    escaped.append(char)
                    slash = False
                elif char == '\\':
                    escaped.append(char)
                    slash = True
                elif char == '"':
                    escaped.append('\\"')
                elif char in '\n\r\t':
                    escaped.append({'\n':'\\n','\r':'\\r','\t':'\\t'}[char])
                else:
                    escaped.append(char)
            try:
                value = json.loads('"' + ''.join(escaped) + '"')
            except ValueError:
                continue
        if isinstance(value, str) and value.strip():
            result[key] = value
    return result or None


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
