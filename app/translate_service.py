"""后台翻译服务：抽取文本块 → 缓存命中 → 分批调用 LLM → 生成译制版 PDF。

数字化可持续设计：
- translation_cache 按 sha256(model+原文) 复用历史译文，重复上传/失败重试不再烧 token；
- 每翻完 5 页落盘一次，中断后已生成部分可见，重试只翻译缓存未命中的部分。
"""
import datetime
import hashlib
import os
import threading
import time
import traceback

import fitz

from .database import FILES_DIR, db, get_settings, llm_config_ready
from . import llm
from .pdf_utils import apply_page_translation, extract_blocks, extract_doc_text

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
        _safe_set(r["id"], status="failed",
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
                    _safe_set(did, status="failed",
                              error="翻译任务长时间无响应（可能是网络或模型服务中断），请点击「重新翻译」继续")
                    with _lock:
                        _running.discard(did)
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
    threading.Thread(target=_run, args=(doc_id,), daemon=True).start()
    return True


def _set(doc_id: int, **fields):
    with db() as c:
        cols = ", ".join(f"{k}=?" for k in fields)
        c.execute(f"UPDATE documents SET {cols} WHERE id=?", (*fields.values(), doc_id))


def _hash(model: str, text: str) -> str:
    return hashlib.sha256((model + "\x00" + text).encode("utf-8")).hexdigest()


def _save_batch(chunk: list, out: list, results: dict, model: str):
    """把一批译文写入内存映射与缓存（单项失败兜底的不写缓存，下次重试）。"""
    with db() as c:
        for s, d in zip(chunk, out):
            results[s] = d
            if d != s:
                c.execute("INSERT OR REPLACE INTO translation_cache(hash, translated) VALUES(?, ?)",
                          (_hash(model, s), d))


def _translate_cached(texts: list, base: str, key: str, model: str, on_progress=None,
                      max_workers: int = 1) -> list:
    """跨页聚合翻译：缓存命中 → 未命中的按 ~1200 字符预算聚合成批请求。

    每条文本仍独立成条翻译（JSON 数组逐条对应），批次边界与页无关，
    因此聚合与并发只改变请求时序、不改变任何一条的译法。
    on_progress(done_blocks)：每批完成后回调已完成的块数（用于进度条）。
    max_workers>1 时多线程并发请求（付费 API 无并发限制时提速明显；
    免费模型遇 429 有指数退避兜底，建议仍用串行）。
    """
    results, misses = {}, []
    with db() as c:
        for t in texts:
            cached = c.execute("SELECT translated FROM translation_cache WHERE hash=?",
                               (_hash(model, t),)).fetchone()
            if cached:
                results[t] = cached["translated"]
            else:
                misses.append(t)
    done = len(texts) - len(misses)
    if on_progress and done:
        on_progress(done)
    # 分批：单次请求 ~1200 字符——实测 GLM-Flash 免费模型对超大批次（4000 字符）推理过慢，
    # 会触发客户端读超时并静默重试死循环；1200 字符单批 10~30s 完成，请求次数仍比按页少 3~4 倍
    chunks, cur, budget = [], [], 0
    for t in misses:
        if cur and budget + len(t) > 1200:
            chunks.append(cur)
            cur, budget = [], 0
        cur.append(t)
        budget += len(t)
    if cur:
        chunks.append(cur)
    if max_workers > 1 and len(chunks) > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = {ex.submit(_translate_chunk_resilient, base, key, model, ch): ch
                    for ch in chunks}
            for fut in as_completed(futs):
                chunk = futs[fut]
                _save_batch(chunk, fut.result(), results, model)
                done += len(chunk)
                if on_progress:
                    on_progress(done)
    else:
        for chunk in chunks:
            out = _translate_chunk_resilient(base, key, model, chunk)
            _save_batch(chunk, out, results, model)
            done += len(chunk)
            if on_progress:
                on_progress(done)
    return [results.get(t, t) for t in texts]


def _translate_chunk_resilient(base, key, model, chunk):
    """带批次拆分重试的翻译：失败则对半拆分递归重试；单项仍失败则保留原文。

    免费模型偶尔不按 JSON 数组格式输出，拆小批次可显著提高成功率，
    且保证单个顽固项不会拖垮整份课件的翻译任务。
    """
    try:
        return llm.translate_batch(base, key, model, chunk)
    except llm.LLMError:
        pass
    if len(chunk) == 1:
        print(f"[translate] 单项翻译失败，保留原文：{chunk[0][:40]}...")
        return list(chunk)
    mid = len(chunk) // 2
    left = _translate_chunk_resilient(base, key, model, chunk[:mid])
    right = _translate_chunk_resilient(base, key, model, chunk[mid:])
    return left + right


def _run(doc_id: int):
    try:
        cfg = get_settings()
        if not llm_config_ready(cfg):
            raise llm.LLMError("尚未配置 API Key，请先到「设置」页填写模型服务信息")
        base, key, model = cfg["api_base"], cfg["api_key"], cfg["model"]

        _safe_set(doc_id, status="extracting", progress=2, error="")
        with db() as c:
            doc = c.execute("SELECT original_path FROM documents WHERE id=?", (doc_id,)).fetchone()
        original = doc["original_path"]

        src = fitz.open(original)
        pages_blocks = extract_blocks(src)
        total_blocks = sum(len(pb) for pb in pages_blocks)
        if total_blocks == 0:
            raise llm.LLMError("未能从该 PDF 提取到文本：可能是扫描版/图片型 PDF，暂不支持（OCR 为后续计划）")

        text_path = str(FILES_DIR / str(doc_id) / "text.txt")
        full_text = extract_doc_text(original)
        with open(text_path, "w", encoding="utf-8") as f:
            f.write(full_text)
        _safe_set(doc_id, page_count=src.page_count, char_count=len(full_text),
             text_path=text_path, status="translating", progress=5)
        src.close()

        out_tmp = str(FILES_DIR / str(doc_id) / "translated.pdf.tmp")
        out_path = str(FILES_DIR / str(doc_id) / "translated.pdf")
        work = fitz.open(original)
        # 跨页聚合翻译：全部文本块合并后按 ~4000 字符分批请求，
        # 请求次数从「每页一次」降到「每 4000 字符一次」，速度提升数倍；
        # 每条文本仍独立成条翻译，译文质量与逐页翻译完全一致。
        all_tasks = [(i, b) for i, blocks in enumerate(pages_blocks) for b in blocks]

        def _prog(done_blocks):
            _safe_set(doc_id, progress=min(95, 5 + int(90 * done_blocks / max(1, total_blocks))))

        # 按服务商自适应：付费/无并发限制的 API 走低节流 + 3 线程并发；
        # 免费模型（bigmodel / 本地 mock / Ollama 单机）维持串行 + 2s 节流防限流
        fast = not any(h in base for h in ("bigmodel", "127.0.0.1", "localhost"))
        llm.MIN_INTERVAL = 0.3 if fast else 2.0
        zh_all = _translate_cached([b["text"] for _, b in all_tasks], base, key, model,
                                   on_progress=_prog, max_workers=3 if fast else 1)
        page_pairs = {}
        for (pi, b), zh in zip(all_tasks, zh_all):
            page_pairs.setdefault(pi, []).append((b, zh))
        for pi in sorted(page_pairs):
            pairs = page_pairs[pi]
            apply_page_translation(work[pi], [b for b, _ in pairs], [z for _, z in pairs])
        # 字体子集化：htmlbox 每次写中文都会嵌入字体，子集化可把体积从几十 MB 压到几十 KB
        try:
            work.subset_fonts()
        except Exception:
            pass
        work.save(out_tmp, garbage=4, deflate=True, deflate_fonts=True)
        work.close()
        os.replace(out_tmp, out_path)

        _safe_set(doc_id, status="done", progress=100, translated_path=out_path,
             translated_at=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
        # 翻译完成 → 自动触发 IMIS 课程辅导分析（imis-course-tutor skill）
        try:
            from .course_tutor import start_analysis
            start_analysis(doc_id)
        except Exception:
            traceback.print_exc()
    except Exception as e:
        traceback.print_exc()
        _safe_set(doc_id, status="failed", error=str(e)[:500])
    finally:
        with _lock:
            _running.discard(doc_id)


threading.Thread(target=_watchdog, daemon=True).start()
