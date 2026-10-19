"""后台翻译服务：抽取文本块 → 缓存命中 → 分批调用 LLM → 生成译制版 PDF。

数字化可持续设计：
- translation_cache 按 sha256(model+原文) 复用历史译文，重复上传/失败重试不再烧 token；
- 同批重复文本只翻译一次；成功的批次立即写入缓存，重试时复用。
"""
import datetime
import hashlib
import os
import re
import threading
import time
import traceback
from collections import Counter, deque
from dataclasses import dataclass
from urllib.parse import urlparse

import fitz

from .database import FILES_DIR, db, get_settings, llm_config_ready
from . import llm
from .pdf_utils import apply_page_translation, extract_blocks, extract_doc_text, normalize_page_rotations

_lock = threading.Lock()
_running: set = set()
# 看门狗：记录每个活跃文档最近一次进度变化时间，长时间无进展自动标记失败
_progress_seen: dict = {}   # doc_id -> (progress, first_seen_at)


def _safe_set(doc_id: int, **fields):
    """状态写入兜底：即使数据库暂时繁忙，也保证最终写入（重试 3 次）。"""
    for i in range(3):
        try:
            _set(doc_id, **fields)
            return
        except Exception:
            time.sleep(1.5 * (i + 1))
    traceback.print_exc()


def recover_stale_jobs():
    """服务启动时调用：把上次异常退出遗留的 translating/extracting 标记为失败。

    已翻译的部分有缓存，重试时不会重复消耗 token。
    """
    with db() as c:
        rows = c.execute(
            "SELECT id FROM documents WHERE status IN ('extracting','translating')").fetchall()
    for r in rows:
        _safe_set(r["id"], status="failed", status_message="", retry_at=0,
                  error="服务重启中断了翻译任务，请点击「重新翻译」继续（已完成部分有缓存）")
        with _lock:
            _running.discard(r["id"])
    if rows:
        print(f"[translate] 启动恢复：重置 {len(rows)} 个中断的翻译任务")


def _watchdog():
    """每 60s 巡检：活跃文档 30 分钟无进度 → 判定线程死亡，标记失败可重试。

    阈值需大于 429 限流退避的最长等待（5+10+20+40+80 ≈ 155s）×若干轮，
    并容忍免费模型高峰期单批 5~10 分钟的排队慢速，避免误杀仍在推进的任务。"""
    while True:
        time.sleep(60)
        try:
            with db() as c:
                rows = c.execute(
                    "SELECT id, progress FROM documents WHERE status IN ('extracting','translating')"
                ).fetchall()
            now = time.time()
            for r in rows:
                did, prog = r["id"], r["progress"]
                last = _progress_seen.get(did)
                if last is None or last[0] != prog:
                    _progress_seen[did] = (prog, now)
                elif now - last[1] > 1800:
                    print(f"[translate] 看门狗：文档 {did} 超过 30 分钟无进展，标记失败")
                    _safe_set(did, status="failed", status_message="", retry_at=0,
                              error="翻译任务长时间无响应（可能是网络或模型服务中断），请点击「重新翻译」继续")
                    _progress_seen.pop(did, None)
            # 清理已结束文档的记录
            alive = {r["id"] for r in rows}
            for did in list(_progress_seen):
                if did not in alive:
                    _progress_seen.pop(did, None)
        except Exception:
            traceback.print_exc()


def start_translation(doc_id: int) -> bool:
    with _lock:
        if doc_id in _running:
            return False
        _running.add(doc_id)
        try:
            # Publish the job before returning the upload response / starting the thread.
            _set(doc_id, status="translating", error="", retry_at=0,
                 status_message="任务已加入队列，正在准备翻译")
        except Exception:
            _running.discard(doc_id)
            raise
    threading.Thread(target=_run, args=(doc_id,), daemon=True).start()
    return True


def _set(doc_id: int, **fields):
    with db() as c:
        cols = ", ".join(f"{k}=?" for k in fields)
        c.execute(f"UPDATE documents SET {cols} WHERE id=?", (*fields.values(), doc_id))


def _hash(model: str, text: str) -> str:
    # Old positional arrays can have the right length but mismatched entries.
    # Keep their cache on disk for rollback, but never reuse it as a verified ID mapping.
    return hashlib.sha256(("id-v2\x00" + model + "\x00" + text).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TranslationPolicy:
    batch_chars: int
    max_workers: int
    min_interval: float
    max_items: int = 40


def translation_policy(base: str) -> TranslationPolicy:
    host = (urlparse(base).hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "::1"):
        return TranslationPolicy(3600, 1, 0.0)
    if host == "api.z.ai" or host == "bigmodel.cn" or host.endswith(".bigmodel.cn"):
        return TranslationPolicy(3600, 1, 2.0)
    return TranslationPolicy(3600, 3, 0.3)


def translation_model(cfg: dict) -> str:
    """Opt into the tested free model only on the official mainland endpoint."""
    host = (urlparse(cfg.get('api_base', '')).hostname or '').lower()
    if cfg.get('translation_mode') == 'fast' and host == 'open.bigmodel.cn':
        return 'glm-4-flash-250414'
    return cfg.get('model', '')


def _make_batches(texts, batch_chars=3600, max_items=40):
    """Count JSON/ID overhead as well as source text; bound payload and label count."""
    chunks, current, budget = [], [], 0
    for text in texts:
        # Include the established opaque ID, JSON framing and escaped source
        # characters rather than filling a request with too many tiny labels.
        cost = _batch_cost(text)
        if current and (budget + cost > batch_chars or len(current) >= max_items):
            chunks.append(current)
            current, budget = [], 0
        current.append(text)
        budget += cost
    if current:
        chunks.append(current)
    return chunks


def _batch_cost(text):
    return len(text) + 16 + text.count('"') + text.count('\\') + text.count('\n')


def _needs_translation(text: str) -> bool:
    """Keep page numbers, formulas, Chinese-only text and bare URLs untouched."""
    if text.strip() in {'Access', 'Microsoft', 'Microsoft Access', 'MS Access'}:
        return False
    if re.fullmatch(r"[\dA-Z\s./:_+\-]+", text.strip()) and re.search(r"\d", text):
        return False  # Academic years / identifiers such as 2026/27S1 and IOM205.
    return bool(re.search(r"[A-Za-z]", text)) and not re.fullmatch(
        r"(?:https?://|www\.)\S+|[^\s@]+@[^\s@]+\.[^\s@]+", text.strip())


# Exact, context-independent slide labels do not need a model request. Keep
# this deliberately small: sentences and ambiguous technical terms use the LLM.
_SLIDE_LABELS = {
    'in summary': '总结', 'summary': '总结', 'references': '参考文献',
    'table of contents': '目录', 'contents': '目录', 'learning objectives': '学习目标',
    'learning outcomes': '学习成果', 'key takeaways': '关键要点',
    'further reading': '延伸阅读', 'thank you': '谢谢', 'any questions': '有什么问题？',
    'questions and answers': '问答', 'group discussion': '小组讨论',
}


def _local_translation(text):
    if not _needs_translation(text):
        return text
    label = re.sub(r'\s+', ' ', text.strip()).lower()
    suffix = '：' if label.endswith((':', '：')) else ''
    value = _SLIDE_LABELS.get(label.rstrip(':：').strip())
    return value + suffix if value is not None else None


def _save_batch(chunk: list, out: list, results: dict, model: str):
    """把一批译文写入内存映射与缓存（单项失败兜底的不写缓存，下次重试）。"""
    with db() as c:
        for s, d in zip(chunk, out):
            results[s] = d
            c.execute("INSERT OR REPLACE INTO translation_cache(hash, translated) VALUES(?, ?)",
                      (_hash(model, s), d))


def _translate_cached(texts: list, base: str, key: str, model: str, on_progress=None,
                      max_workers: int = 1, batch_chars: int = 3600,
                      request_options=None, max_items: int = 40) -> list:
    """Deduplicate and batch cache lookups while preserving every input position."""
    started = time.monotonic()
    counts = Counter(texts)
    results = {t: value for t in counts if (value := _local_translation(t)) is not None}
    lookup = {_hash(model, t): t for t in counts if t not in results}
    hashes = list(lookup)
    with db() as c:
        for start in range(0, len(hashes), 400):
            group = hashes[start:start + 400]
            marks = ",".join("?" for _ in group)
            for cached in c.execute(
                    f"SELECT hash, translated FROM translation_cache WHERE hash IN ({marks})", group):
                if cached["translated"]:
                    results[lookup[cached["hash"]]] = cached["translated"]
    misses = [t for t in counts if t not in results]
    done = sum(counts[t] for t in results)
    if on_progress and done:
        on_progress(done)
    chunks = _make_batches(misses, batch_chars, max_items)
    print(f"[translate] {len(texts)} 个文本块 / {len(counts)} 个唯一块，"
          f"缓存及原样保留 {done} 块，待请求 {len(chunks)} 批，并发 {max_workers}")
    if max_workers > 1 and len(chunks) > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed, CancelledError
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = {ex.submit(_translate_chunk_resilient, base, key, model, ch, request_options): ch
                    for ch in chunks}
            failure = None
            for fut in as_completed(futs):
                chunk = futs[fut]
                try:
                    out = fut.result()
                except CancelledError:
                    continue
                except Exception as exc:
                    failure = failure or exc
                    for pending in futs:
                        pending.cancel()
                    continue
                _save_batch(chunk, out, results, model)
                done += sum(counts[t] for t in chunk)
                if on_progress:
                    on_progress(done)
            if failure:
                raise failure
    else:
        pending, attempts = deque(misses), Counter()
        current_chars, current_items = batch_chars, max_items
        while pending:
            chunk, budget = [], 0
            while pending:
                cost = _batch_cost(pending[0])
                if chunk and (budget + cost > current_chars or len(chunk) >= current_items):
                    break
                chunk.append(pending.popleft())
                budget += cost
            for text in chunk:
                attempts[text] += 1
            try:
                translated = _translate_request(base, key, model, chunk, request_options)
                partial = dict(enumerate(translated))
            except llm.TranslationFormatError as exc:
                partial = exc.partial
            good = [i for i in range(len(chunk)) if partial.get(i)]
            if good:
                _save_batch([chunk[i] for i in good], [partial[i] for i in good], results, model)
                done += sum(counts[chunk[i]] for i in good)
                if on_progress:
                    on_progress(done)
            missing = [chunk[i] for i in range(len(chunk)) if not partial.get(i)]
            if any(attempts[text] >= 3 for text in missing):
                raise llm.LLMError('模型多次遗漏或错配译文，任务已停止。已完成内容有缓存，可点击「重新翻译」继续。')
            if missing:
                pending.extend(missing)
                print(f'[translate] 已保存 {len(good)}/{len(chunk)} 条，{len(missing)} 条遗漏并入后续批次')
                if len(missing) > len(chunk) / 4:
                    current_chars = max(600, current_chars // 2)
                    current_items = min(current_items, max(1, len(chunk) // 2))
    print(f"[translate] 文本翻译耗时 {time.monotonic() - started:.2f}s")
    return [results.get(t, t) for t in texts]


def _translate_request(base, key, model, chunk, request_options=None):
    options = {**(request_options or {}), 'rate_limit_fail_fast': True}
    options.setdefault('deadline', time.monotonic() + 900)
    for attempt in range(12):
        try:
            return llm.translate_batch(base, key, model, chunk, request_options=options)
        except llm.TemporaryServiceError as exc:
            if attempt == 11 or time.monotonic() + exc.retry_after > options['deadline']:
                raise llm.LLMError(f'{exc}。模型服务持续受限或连接中断，自动等待已达上限；已完成译文有缓存，请稍后继续。') from exc
            print(f'[translate] {exc}；冷却 {exc.retry_after:.0f}s 后自动继续，保留已完成译文')
            if options.get('on_wait'):
                reason = '模型暂时限流' if isinstance(exc, llm.RateLimitError) else '模型连接暂时中断'
                options['on_wait'](exc.retry_after, reason + '，等待后自动继续；已完成译文已保存')


def _translate_chunk_resilient(base, key, model, chunk, request_options=None, _depth=0):
    """Reuse valid ID-tagged entries and retry only missing entries, at most two levels.

    Never label untranslated content as a completed translation. Successful
    partial entries are cached even when the remainder of the batch fails.
    """
    options = dict(request_options or {})
    options.setdefault('deadline', time.monotonic() + 900)
    try:
        return _translate_request(base, key, model, chunk, options)
    except llm.TranslationFormatError as exc:
        partial = exc.partial
    result = [partial.get(i) for i in range(len(chunk))]
    good = [i for i, value in enumerate(result) if value]
    if good:
        _save_batch([chunk[i] for i in good], [result[i] for i in good], {}, model)
    missing = [i for i, value in enumerate(result) if not value]
    if _depth >= 2:
        raise llm.LLMError("模型多次遗漏或错配译文，任务已停止。已完成内容有缓存，可点击「重新翻译」继续。")
    # No full-batch regeneration just because one ID was omitted.
    half = max(1, (len(missing) + 1) // 2)
    groups = [missing] if good or len(missing) == 1 else [missing[:half], missing[half:]]
    for indices in groups:
        if not indices:
            continue
        values = _translate_chunk_resilient(base, key, model, [chunk[i] for i in indices],
                                             options, _depth + 1)
        _save_batch([chunk[i] for i in indices], values, {}, model)
        for i, value in zip(indices, values):
            result[i] = value
    return result


def _run(doc_id: int):
    src = work = None
    try:
        cfg = get_settings()
        if not llm_config_ready(cfg):
            raise llm.LLMError("尚未配置 API Key，请先到「设置」页填写模型服务信息")
        base, key, model = cfg["api_base"], cfg["api_key"], translation_model(cfg)

        _safe_set(doc_id, status="extracting", progress=2, error="", status_message="正在解析课件", retry_at=0)
        with db() as c:
            doc = c.execute("SELECT original_path FROM documents WHERE id=?", (doc_id,)).fetchone()
        original = doc["original_path"]

        started = time.monotonic()
        work = fitz.open(original)
        normalize_page_rotations(work)
        pages_blocks = extract_blocks(work)
        total_blocks = sum(len(pb) for pb in pages_blocks)
        if total_blocks == 0:
            _safe_set(doc_id,page_count=work.page_count)
            try:
                from .study_ai import register_pages
                register_pages(doc_id,[page.get_text('text').strip() for page in work])
            except Exception:traceback.print_exc()
            raise llm.LLMError("未能从该 PDF 提取到文本：可能是扫描版/图片型 PDF，暂不支持（OCR 为后续计划）")

        text_path = str(FILES_DIR / str(doc_id) / "text.txt")
        full_text = "\n\n".join(f"【第 {i} 页】\n{page.get_text('text').strip()}"
                                  for i, page in enumerate(work, 1))
        with open(text_path, "w", encoding="utf-8") as f:
            f.write(full_text)
        _safe_set(doc_id, page_count=work.page_count, char_count=len(full_text),
             text_path=text_path, status="translating", progress=5, status_message="", retry_at=0)

        # Register durable page jobs before the first translation API request.
        # A failed/closed UI never cancels these independently saved jobs.
        try:
            from .study_ai import register_pages
            register_pages(doc_id,[page.get_text('text').strip() for page in work])
        except Exception:
            traceback.print_exc()

        out_tmp = str(FILES_DIR / str(doc_id) / "translated.pdf.tmp")
        out_path = str(FILES_DIR / str(doc_id) / "translated.pdf")
        # Cross-page batching uses the provider policy; cached text stays reusable.
        all_tasks = [(i, b) for i, blocks in enumerate(pages_blocks) for b in blocks]

        def _prog(done_blocks):
            _safe_set(doc_id, progress=min(90, 5 + int(85 * done_blocks / max(1, total_blocks))))

        def _waiting(seconds, message):
            with db() as c:
                row = c.execute('SELECT status FROM documents WHERE id=?', (doc_id,)).fetchone()
            if not row or row['status'] not in ('extracting', 'translating'):
                raise llm.LLMError('翻译任务已停止')
            _safe_set(doc_id, retry_at=time.time() + seconds if seconds > 0 else 0,
                      status_message=message)

        policy = translation_policy(base)
        zh_all = _translate_cached([b["text"] for _, b in all_tasks], base, key, model,
                                   on_progress=_prog, max_workers=policy.max_workers,
                                   batch_chars=policy.batch_chars, max_items=policy.max_items,
                                   request_options={"min_interval": policy.min_interval,
                                                    "max_attempts": 2,
                                                    "timeout": (15, 120), "on_wait": _waiting})
        page_pairs = {}
        for (pi, b), zh in zip(all_tasks, zh_all):
            page_pairs.setdefault(pi, []).append((b, zh))
        render_started = time.monotonic()
        for pi in sorted(page_pairs):
            pairs = page_pairs[pi]
            apply_page_translation(work[pi], [b for b, _ in pairs], [z for _, z in pairs])
            _safe_set(doc_id, progress=min(99, 90 + int(9 * (pi + 1) / work.page_count)))
        # 字体子集化：htmlbox 每次写中文都会嵌入字体，子集化可把体积从几十 MB 压到几十 KB
        try:
            work.subset_fonts()
        except Exception:
            pass
        work.save(out_tmp, garbage=4, deflate=True, deflate_fonts=True)
        work.close()
        os.replace(out_tmp, out_path)
        print(f"[translate] 文档 {doc_id} PDF 回写 {time.monotonic() - render_started:.2f}s，"
              f"总耗时 {time.monotonic() - started:.2f}s")

        _safe_set(doc_id, status="done", progress=100, translated_path=out_path,
             error="", status_message="", retry_at=0,
             translated_at=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
        # 翻译完成 → 自动触发 IMIS 课程辅导分析（imis-course-tutor skill）
        try:
            from .course_tutor import start_analysis
            start_analysis(doc_id)
        except Exception:
            traceback.print_exc()
    except Exception as e:
        traceback.print_exc()
        _safe_set(doc_id, status="failed", error=str(e)[:500], status_message="", retry_at=0)
    finally:
        for pdf in (src, work):
            if pdf is not None and not pdf.is_closed:
                pdf.close()
        with _lock:
            _running.discard(doc_id)


threading.Thread(target=_watchdog, daemon=True).start()
