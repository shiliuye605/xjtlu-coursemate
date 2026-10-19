"""西浦课件通 · XJTLU CourseMate —— FastAPI 后端入口。

路由分组：课程 / 课件与翻译 / 设置（BYOK）/ AI 助教（流式）/ 课程总结 / 内置示例。
静态前端由同一服务托管，本地一键运行，数据不出本机。
"""
import datetime
import json
import os
import shutil

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .database import (BASE_DIR, FILES_DIR, SUMMARY_DIR, db, get_settings,
                       init_db, llm_config_ready, set_settings)
from . import llm, demo_model, study_ai
from .pdf_utils import summary_markdown_to_pdf
from .translate_service import recover_stale_jobs, start_translation, translation_model
from .course_tutor import start_analysis

app = FastAPI(title="XJTLU CourseMate API", version="1.0")
init_db()


@app.on_event("startup")
def _startup():
    recover_stale_jobs()
    # 重启会中断进行中的辅导分析线程，把僵尸 running 状态重置为可重试
    with db() as c:
        c.execute("UPDATE documents SET analysis_status='failed' WHERE analysis_status='running'")
    study_ai.start_workers()


@app.on_event('shutdown')
def _shutdown():
    study_ai.stop_workers()
STATIC_DIR = BASE_DIR / "static"
SAMPLE_DIR = BASE_DIR / "sample_data"
MAX_SIZE = 80 * 1024 * 1024

PRESETS = {
    "glm-free": {"label": "智谱 GLM-Flash（免费，推荐）", "free": True,
                 "api_base": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4.5-flash",
                 "help": "完全免费、国内直连，翻译/对话质量对课件场景足够。步骤：注册 https://open.bigmodel.cn → 控制台「API Keys」→ 新建并复制 → 粘贴到下方 API Key。免费模型：glm-4.5-flash（旧版 glm-4-flash 也可用）。"},
    "siliconflow": {"label": "SiliconFlow（含免费模型）", "free": True,
                    "api_base": "https://api.siliconflow.cn/v1", "model": "Qwen/Qwen2.5-7B-Instruct",
                    "help": "注册 https://cloud.siliconflow.cn 赠送体验金；Qwen/Qwen2.5-7B-Instruct 等小模型永久免费，翻译课件够用。在「API 密钥」页新建 Key。"},
    "gemini": {"label": "Google Gemini（免费额度）", "free": True,
               "api_base": "https://generativelanguage.googleapis.com/v1beta/openai", "model": "gemini-3.5-flash",
               "help": "免费额度约 1500 次/天，质量很好。注册 https://aistudio.google.com → Get API key → 弹窗里点「复制密钥」。注意：国内访问需走代理（应用会自动检测本机代理）。"},
    "openrouter": {"label": "OpenRouter（免费模型）", "free": True,
                   "api_base": "https://openrouter.ai/api/v1", "model": "deepseek/deepseek-chat-v3.1:free",
                   "help": "注册 https://openrouter.ai → Keys 页创建。名称带 :free 后缀的模型免费但有限速；模型名以官网 Models 页「免费」标签为准。国内访问可能需要代理。"},
    "ollama": {"label": "本地 Ollama（离线免费）", "free": True,
               "api_base": "http://127.0.0.1:11434/v1", "model": "qwen2.5:7b",
               "help": "完全免费、数据不出本机：安装 https://ollama.com → 终端运行 ollama pull qwen2.5:7b（约 4.7GB）→ 保持 ollama serve 运行。API Key 随便填（如 ollama）。速度取决于你的机器配置。"},
    "deepseek": {"label": "DeepSeek（低价按量）",
                 "api_base": "https://api.deepseek.com/v1", "model": "deepseek-chat",
                 "help": "不免费但极便宜（翻译一份 40 页课件约几分钱）。注册 https://platform.deepseek.com → 充值少量额度 → 创建 API Key。"},
    "openai": {"label": "OpenAI",
               "api_base": "https://api.openai.com/v1", "model": "gpt-4o-mini",
               "help": "按量付费，质量稳定。注册 https://platform.openai.com 创建 Key。国内访问需自行解决网络与支付问题。"},
    "moonshot": {"label": "Moonshot Kimi",
                 "api_base": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k",
                 "help": "注册 https://platform.moonshot.cn → API Key 管理 → 新建。新用户有赠送额度。"},
    "mock": {"label": "离线演示（无需 Key）",
             "api_base": "http://127.0.0.1:9999/v1", "model": "mock-llm",
             "help": "本机演示模型（先运行 demo.bat 启动），翻译会标注「演示译文」，用于无 Key 时体验完整流程。"},
}

if os.environ.get('COURSEMATE_DESKTOP') == '1':
    PRESETS['mock']['api_base'] = os.environ['COURSEMATE_DEMO_BASE']
    PRESETS['mock']['help'] = '内置离线演示，无需运行其他程序、安装 Python 或填写真实 Key。内容为标注的占位示例，不是真实 AI 翻译。选择此预设后保存配置即可体验。'


def now_str() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def _save_uploaded_pdf(course_id: int, filename: str, data: bytes) -> int:
    with db() as c:
        cur = c.execute("INSERT INTO documents(course_id, filename) VALUES(?, ?)",
                        (course_id, filename))
        doc_id = cur.lastrowid
    folder = FILES_DIR / str(doc_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "original.pdf"
    path.write_bytes(data)
    with db() as c:
        c.execute("UPDATE documents SET original_path=? WHERE id=?", (str(path), doc_id))
    return doc_id


def _maybe_auto_translate(doc_id: int) -> bool:
    if llm_config_ready(get_settings()):
        return start_translation(doc_id)
    return False


# ================= 健康检查 =================
@app.get("/api/health")
def health():
    return {"ok": True, "app": "XJTLU CourseMate"}


# ================= 课程 =================
@app.get("/api/courses")
def list_courses():
    with db() as c:
        rows = c.execute("""
            SELECT co.*,
                   (SELECT COUNT(*) FROM documents d WHERE d.course_id = co.id) AS doc_count,
                   (SELECT COUNT(*) FROM documents d WHERE d.course_id = co.id AND d.status='done') AS done_count
            FROM courses co ORDER BY co.id DESC""").fetchall()
    return [dict(r) for r in rows]


@app.post("/api/courses")
def create_course(body: dict):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "课程名称不能为空")
    with db() as c:
        cur = c.execute("INSERT INTO courses(name, code, teacher) VALUES(?, ?, ?)",
                        (name, (body.get("code") or "").strip(), (body.get("teacher") or "").strip()))
        cid = cur.lastrowid
    return {"id": cid}


@app.put("/api/courses/{course_id}")
def rename_course(course_id: int, body: dict):
    """编辑课程信息（名称 / 课程代码 / 教师）。"""
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "课程名称不能为空")
    with db() as c:
        if not c.execute("SELECT id FROM courses WHERE id=?", (course_id,)).fetchone():
            raise HTTPException(404, "课程不存在")
        c.execute("UPDATE courses SET name=?, code=?, teacher=? WHERE id=?",
                  (name, (body.get("code") or "").strip(),
                   (body.get("teacher") or "").strip(), course_id))
    return {"ok": True}


@app.delete("/api/courses/{course_id}")
def delete_course(course_id: int):
    with db() as c:ids=[r[0] for r in c.execute('SELECT id FROM documents WHERE course_id=?',(course_id,))]
    study_ai.cleanup_overviews(ids)
    with db() as c:
        doc_rows = c.execute("SELECT id FROM documents WHERE course_id=?", (course_id,)).fetchall()
        c.execute("DELETE FROM courses WHERE id=?", (course_id,))
    for r in doc_rows:
        shutil.rmtree(FILES_DIR / str(r["id"]), ignore_errors=True)
    (SUMMARY_DIR / f"course_{course_id}.pdf").unlink(missing_ok=True)
    return {"ok": True}


# ================= 课件与翻译 =================
@app.get("/api/courses/{course_id}/documents")
def list_documents(course_id: int):
    with db() as c:
        rows = c.execute(
            """SELECT id, filename, page_count, char_count, status, progress, error,
                      created_at, translated_at, analysis_status, status_message, retry_at
               FROM documents WHERE course_id=? ORDER BY id DESC""", (course_id,)).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/courses/{course_id}/documents")
async def upload_document(course_id: int, file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "仅支持 PDF 文件")
    data = await file.read()
    if len(data) > MAX_SIZE:
        raise HTTPException(400, "文件超过 80MB 限制")
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "文件不是有效的 PDF")
    doc_id = _save_uploaded_pdf(course_id, file.filename, data)
    return {"id": doc_id, "auto_started": _maybe_auto_translate(doc_id)}


@app.post("/api/sample/{course_id}")
def upload_sample(course_id: int):
    """载入内置示例课件（两份模拟英文讲义），便于无课件时快速体验。"""
    samples = sorted(SAMPLE_DIR.glob("*.pdf")) if SAMPLE_DIR.exists() else []
    if not samples:
        raise HTTPException(404, "示例文件缺失")
    out = []
    for p in samples:
        doc_id = _save_uploaded_pdf(course_id, p.name, p.read_bytes())
        _maybe_auto_translate(doc_id)
        out.append({"id": doc_id, "filename": p.name})
    return out


@app.get("/api/documents/{doc_id}")
def document_status(doc_id: int):
    with db() as c:
        r = c.execute("""SELECT id, course_id, filename, page_count, char_count,
                                status, progress, error, translated_path, analysis_status, status_message, retry_at
                         FROM documents WHERE id=?""", (doc_id,)).fetchone()
    if not r:
        raise HTTPException(404, "文档不存在")
    return dict(r)


@app.get("/api/documents/{doc_id}/analysis")
def get_analysis(doc_id: int):
    """IMIS 课程辅导分析（imis-course-tutor skill 自动生成）。"""
    with db() as c:
        r = c.execute("SELECT filename, analysis_status, analyzed_at FROM documents WHERE id=?",
                      (doc_id,)).fetchone()
    if not r:
        raise HTTPException(404, "文档不存在")
    path = FILES_DIR / str(doc_id) / "analysis.md"
    md = path.read_text(encoding="utf-8") if (r["analysis_status"] == "done" and path.exists()) else ""
    return {"status": r["analysis_status"] or "", "markdown": md,
            "analyzed_at": r["analyzed_at"], "filename": r["filename"]}


@app.post("/api/documents/{doc_id}/analyze")
def analyze_document(doc_id: int):
    """手动触发 / 重新生成辅导分析。"""
    with db() as c:
        r = c.execute("SELECT status, analysis_status FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not r:
        raise HTTPException(404, "文档不存在")
    if r["analysis_status"] == "running":
        raise HTTPException(409, "分析正在进行中，请稍候")
    if r["status"] != "done":
        raise HTTPException(400, "请先完成课件翻译，再生成辅导分析")
    if not llm_config_ready(get_settings()):
        raise HTTPException(400, "尚未配置 API Key，请先到「设置」页配置模型服务")
    study_ai.queue_overview(study_ai._document(doc_id)['course_id'],[doc_id],force=True)
    return {"ok": True}


@app.post("/api/documents/{doc_id}/translate")
def translate_document(doc_id: int):
    with db() as c:
        r = c.execute("SELECT status FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not r:
        raise HTTPException(404, "文档不存在")
    if r["status"] in ("extracting", "translating"):
        raise HTTPException(409, "该文档正在翻译中，请稍候")
    if not llm_config_ready(get_settings()):
        raise HTTPException(400, "尚未配置 API Key，请先到「设置」页配置模型服务")
    if not start_translation(doc_id):
        raise HTTPException(409, "该文档正在翻译中，请稍候")
    return {"ok": True}


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: int):
    study_ai.cleanup_overviews([doc_id])
    with db() as c:
        c.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    shutil.rmtree(FILES_DIR / str(doc_id), ignore_errors=True)
    return {"ok": True}


@app.get("/api/documents/{doc_id}/files/{kind}")
def document_file(doc_id: int, kind: str):
    if kind not in ("original", "translated"):
        raise HTTPException(404, "not found")
    with db() as c:
        r = c.execute("SELECT original_path, translated_path FROM documents WHERE id=?",
                      (doc_id,)).fetchone()
    if not r:
        raise HTTPException(404, "文档不存在")
    path = r["original_path"] if kind == "original" else r["translated_path"]
    if not path or not os.path.exists(path):
        raise HTTPException(404, "文件尚未生成")
    return FileResponse(path, media_type="application/pdf",
                        headers={"Cache-Control":"no-store"} if kind == "translated" else None)


def _load_saved_keys(cfg: dict) -> dict:
    """各服务商记住的 Key（api_base → api_key），存 settings 表 saved_keys（JSON）。"""
    try:
        saved = json.loads(cfg.get("saved_keys", "") or "{}")
    except Exception:
        saved = {}
    if cfg.get("api_base") and cfg.get("api_key"):
        saved = {**saved, cfg["api_base"]: cfg["api_key"]}
    return saved


# ================= 设置（BYOK） =================
@app.get("/api/settings")
def get_settings_api():
    cfg = get_settings()
    key = cfg.get("api_key", "")
    return {
        "api_base": cfg.get("api_base", ""),
        "model": cfg.get("model", ""),
        "translation_mode": cfg.get("translation_mode", "standard"),
        "translation_model": translation_model(cfg),
        "has_key": bool(key),
        "key_hint": ("••••••••" + key[-4:]) if len(key) > 4 else "",
        "ready": llm_config_ready(cfg),
        "presets": PRESETS,
        "saved_keys": _load_saved_keys(cfg),
    }


@app.post("/api/settings")
def save_settings_api(body: dict):
    if 'translation_mode' in body and body['translation_mode'] not in ('fast', 'standard'):
        raise HTTPException(400, "翻译模式无效")
    data = {k: str(v).strip() for k, v in body.items()
            if k in ("api_base", "api_key", "model", "translation_mode") and str(v).strip()}
    if not data:
        raise HTTPException(400, "没有可保存的配置")
    # 记住该服务商的 Key，切换预设时自动带出
    saved = _load_saved_keys(get_settings())
    if data.get("api_base") and data.get("api_key"):
        saved[data["api_base"]] = data["api_key"]
    data["saved_keys"] = json.dumps(saved, ensure_ascii=False)
    set_settings(data)
    return {"ok": True, "ready": llm_config_ready(get_settings())}


@app.post("/api/settings/test")
def test_settings_api(body: dict):
    base = (body.get("api_base") or "").strip()
    key = (body.get("api_key") or "").strip()
    model = (body.get("model") or "").strip()
    if not (base and key and model):
        raise HTTPException(400, "请先填写完整：接口地址 / API Key / 模型名称")
    try:
        return llm.test_connection(base, key, model)
    except llm.LLMError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})


# ================= AI 助教（流式） =================
def _build_context(course_id: int, document_id: int) -> str:
    with db() as c:
        if document_id:
            rows = c.execute(
                "SELECT filename, text_path FROM documents WHERE id=? AND course_id=?",
                (document_id, course_id)).fetchall()
        else:
            rows = c.execute(
                "SELECT filename, text_path FROM documents WHERE course_id=? AND status='done' "
                "ORDER BY id DESC LIMIT 3", (course_id,)).fetchall()
    parts = []
    for r in rows:
        if r["text_path"] and os.path.exists(r["text_path"]):
            txt = open(r["text_path"], encoding="utf-8").read()
            parts.append(f"《{r['filename']}》\n{txt[:6000]}")
    return ("\n\n———\n\n".join(parts))[:9000] if parts else ""


@app.post("/api/chat")
async def chat_api(body: dict):
    cfg = get_settings()
    if not llm_config_ready(cfg):
        raise HTTPException(400, "尚未配置 API Key，请先到「设置」页配置模型服务")
    course_id = int(body.get("course_id") or 0)
    document_id = int(body.get("document_id") or 0)
    history = body.get("messages") or []
    if not history:
        raise HTTPException(400, "消息不能为空")
    try:
        page_number=max(0,int(body.get('page_number') or 0))
    except (ValueError,TypeError):
        raise HTTPException(400,'页码无效')
    scope_ids=body.get('document_ids') or []
    scope_key=''
    if scope_ids:
        scope_ids,_=study_ai._validate_scope(course_id,scope_ids)
        scope_key=','.join(map(str,scope_ids))
    if document_id:
        doc=study_ai._document(document_id)
        if doc['course_id']!=course_id:raise HTTPException(400,'课件不属于当前课程')
        if page_number>doc['page_count']:raise HTTPException(400,'页码超过课件范围')
    elif page_number:
        raise HTTPException(400,'请先选择对应课件')

    course_name = ""
    with db() as c:
        row = c.execute("SELECT name, code FROM courses WHERE id=?", (course_id,)).fetchone()
        if row:
            course_name = row["name"] + (f"（{row['code']}）" if row["code"] else "")

    context = _build_context(course_id, document_id)
    if document_id and page_number:
        with db() as c:
            row=c.execute('SELECT source,markdown FROM study_pages WHERE document_id=? AND page_number=?',(document_id,page_number)).fetchone()
        if row:
            context=f'课件《{doc["filename"]}》第 {page_number} 页完整原文：\n{row["source"]}\n\n本页已有讲解：\n{row["markdown"]}'
    elif scope_ids:
        parts=[]
        for selected in scope_ids:
            entry=study_ai._document(selected)
            path=FILES_DIR/str(selected)/'analysis.md'
            text=path.read_text(encoding='utf-8') if path.is_file() else '\n'.join(study_ai._sources(entry))
            parts.append(f'课件《{entry["filename"]}》：\n{text[:12000]}')
        context='\n\n'.join(parts)[:60000]
    sys_prompt = (
        "你是西交利物浦大学（XJTLU）的智能课程助教。请用简体中文回答学生问题，"
        "专业术语首次出现时保留英文原文；回答结构清晰，适合复习。"
        "如果提供了课件上下文，请优先基于课件内容回答；如果上下文不足以回答，请如实说明。"
    )
    if course_name:
        sys_prompt += f"\n当前课程：{course_name}。"
    if context:
        sys_prompt += f"\n\n以下是课件内容摘录，供你参考：\n{context}"

    history=[{'role':m.get('role'),'content':str(m.get('content',''))[:20000]} for m in history[-16:] if isinstance(m,dict) and m.get('role') in ('user','assistant')]
    messages = [{"role": "system", "content": sys_prompt}] + history
    last_user = next((m.get("content", "") for m in reversed(history) if m.get("role") == "user"), "")

    def gen():
        full = ""
        try:
            for chunk in llm.chat_stream(cfg["api_base"], cfg["api_key"], cfg["model"], messages,
                                         extra=study_ai.model_extras(cfg),max_tokens=5000):
                full += chunk
                yield chunk
        except llm.LLMError as e:
            yield f"\n\n⚠️ 调用失败：{e}"
        except Exception as e:
            yield f"\n\n⚠️ 服务异常：{e}"
        finally:
            if full.strip():
                with db() as c:
                    if last_user:
                        c.execute("INSERT INTO chat_messages(course_id, document_id, role, content,page_number,scope_key) "
                                  "VALUES(?, ?, 'user', ?,?,?)", (course_id, document_id, last_user,page_number,scope_key))
                    c.execute("INSERT INTO chat_messages(course_id, document_id, role, content,page_number,scope_key) "
                              "VALUES(?, ?, 'assistant', ?,?,?)", (course_id, document_id, full,page_number,scope_key))

    return StreamingResponse(gen(), media_type="text/plain; charset=utf-8")


@app.get("/api/chat/history")
def chat_history(course_id: int,document_id:int=-1,page_number:int=-1,scope_key:str=''):
    with db() as c:
        query='SELECT id,role,content,created_at,document_id,page_number,scope_key FROM chat_messages WHERE course_id=?'
        params=[course_id]
        if document_id>=0:query+=' AND document_id=?';params.append(document_id)
        if page_number>=0:query+=' AND page_number=?';params.append(page_number)
        if scope_key:query+=' AND scope_key=?';params.append(scope_key)
        rows=c.execute('SELECT * FROM ('+query+' ORDER BY id DESC LIMIT 100) ORDER BY id',params).fetchall()
    return [dict(r) for r in rows]


@app.delete("/api/chat/history")
def chat_clear(course_id: int):
    with db() as c:
        c.execute("DELETE FROM chat_messages WHERE course_id=?", (course_id,))
    return {"ok": True}


# ================= 课程总结 =================
@app.get("/api/courses/{course_id}/summary")
def get_summary(course_id: int):
    with db() as c:
        s = c.execute("SELECT * FROM summaries WHERE course_id=?", (course_id,)).fetchone()
        docs = c.execute("SELECT id, filename, status FROM documents WHERE course_id=? "
                         "ORDER BY id ASC", (course_id,)).fetchall()
    included = json.loads(s["included_doc_ids"]) if s and s["included_doc_ids"] else []
    done_ids = [d["id"] for d in docs if d["status"] == "done"]
    pending = [i for i in done_ids if i not in included]
    pdf_ok = bool(s and s["pdf_path"] and os.path.exists(s["pdf_path"]))
    return {
        "markdown": s["markdown"] if s else "",
        "updated_at": s["updated_at"] if s else None,
        "pdf_ready": pdf_ok,
        "pdf_url": f"/api/courses/{course_id}/summary.pdf" if pdf_ok else None,
        "included": included,
        "pending_count": len(pending),
        "doc_count": len(done_ids),
        "docs": [dict(d) for d in docs],
    }


@app.post("/api/courses/{course_id}/summary/update")
def update_summary(course_id: int):
    cfg = get_settings()
    if not llm_config_ready(cfg):
        raise HTTPException(400, "尚未配置 API Key，请先到「设置」页配置模型服务")
    with db() as c:
        course = c.execute("SELECT name, code FROM courses WHERE id=?", (course_id,)).fetchone()
        if not course:
            raise HTTPException(404, "课程不存在")
        s = c.execute("SELECT markdown, included_doc_ids FROM summaries WHERE course_id=?",
                      (course_id,)).fetchone()
        docs = c.execute("""SELECT id, filename, text_path FROM documents
                            WHERE course_id=? AND status='done' ORDER BY id ASC""",
                         (course_id,)).fetchall()
    if not docs:
        raise HTTPException(400, "该课程还没有处理完成的课件（请先上传并完成翻译）")

    old_md = s["markdown"] if s else ""
    old_ids = json.loads(s["included_doc_ids"]) if s else []
    new_docs = [d for d in docs if d["id"] not in old_ids]

    # 增量更新策略：已有总结时只送入"已有总结 + 新增课件"，显著节省 token 与等待时间
    if old_md and new_docs:
        source_docs = new_docs
        mode_hint = ("已有课程总结如下，请在原有结构基础上融入新增课件内容，"
                     "输出完整更新后的总结（保留原有仍有效的要点，可重组结构）：\n\n"
                     f"【已有总结】\n{old_md[:6000]}\n\n【新增课件】\n\n")
        incremental = True
    else:
        source_docs = docs
        mode_hint = "请根据以下全部课件内容生成课程总结：\n\n"
        incremental = False

    sections, total = [], 0
    for d in source_docs:
        txt = ""
        if d["text_path"] and os.path.exists(d["text_path"]):
            txt = open(d["text_path"], encoding="utf-8").read()
        txt = txt[:4500]
        total += len(txt)
        sections.append(f"—— 课件《{d['filename']}》 ——\n{txt}")
    if total < 40:
        raise HTTPException(400, "课件没有可提取的文本（可能是扫描版/图片型 PDF），无法生成总结")

    prompt = (mode_hint + "\n\n".join(sections) +
              f"\n\n请输出 Markdown 格式的中文课程总结，结构如下：\n"
              f"# 课程总结：{course['name']}\n"
              f"## 一、课程概览（课程主线与逻辑）\n"
              f"## 二、核心知识点（按主题分小节；要点列出关键概念/模型/方法，术语保留英文）\n"
              f"## 三、重点与考点提示（易考内容、易混淆概念对比）\n"
              f"## 四、已纳入的课件清单（列出文件名）\n"
              f"内容务必基于课件本身，不要编造课件中没有的内容。")
    try:
        md = llm.chat_once(cfg["api_base"], cfg["api_key"], cfg["model"],
                           [{"role": "system",
                             "content": "你是教务助理，擅长把课件内容整理成结构化中文复习总结。只输出 Markdown。"},
                            {"role": "user", "content": prompt}],
                           temperature=0.3, max_tokens=4000, timeout=(15, 300))
    except llm.LLMError as e:
        raise HTTPException(502, f"生成总结失败：{e}")

    md = md.strip()
    ids = [d["id"] for d in docs]
    pdf_path = str(SUMMARY_DIR / f"course_{course_id}.pdf")
    subtitle = (f"{course['code'] or 'Course'} · 共纳入 {len(ids)} 份课件 · "
                f"{'增量更新' if incremental else '全量生成'} · {now_str()}")
    summary_markdown_to_pdf(md, f"课程总结：{course['name']}", subtitle, pdf_path)
    note = (f"{'增量更新' if incremental else '全量生成'}：共纳入 {len(ids)} 份课件"
            + (f"（新增 {len(new_docs)} 份）" if incremental else ""))

    with db() as c:
        c.execute("""INSERT INTO summaries(course_id, markdown, pdf_path, included_doc_ids, updated_at)
                     VALUES(?, ?, ?, ?, ?)
                     ON CONFLICT(course_id) DO UPDATE SET markdown=excluded.markdown,
                       pdf_path=excluded.pdf_path, included_doc_ids=excluded.included_doc_ids,
                       updated_at=excluded.updated_at""",
                  (course_id, md, pdf_path, json.dumps(ids), now_str()))
        c.execute("INSERT INTO summary_history(course_id, markdown, pdf_path, included_doc_ids, note) "
                  "VALUES(?, ?, ?, ?, ?)",
                  (course_id, md, pdf_path, json.dumps(ids), note))
    return {"ok": True}


@app.get("/api/courses/{course_id}/summary/history")
def summary_history(course_id: int):
    with db() as c:
        rows = c.execute("""SELECT id, note, created_at FROM summary_history
                            WHERE course_id=? ORDER BY id DESC LIMIT 30""",
                         (course_id,)).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/courses/{course_id}/summary.pdf")
def summary_pdf(course_id: int):
    with db() as c:
        r = c.execute("SELECT pdf_path FROM summaries WHERE course_id=?", (course_id,)).fetchone()
    if not r or not r["pdf_path"] or not os.path.exists(r["pdf_path"]):
        raise HTTPException(404, "总结 PDF 尚未生成，请先点击「更新总结」")
    return FileResponse(r["pdf_path"], media_type="application/pdf")


# ================= 静态前端（放在最后挂载） =================
@app.post('/api/demo/v1/chat/completions')
def desktop_demo(body: dict):
    if os.environ.get('COURSEMATE_DESKTOP') != '1':
        raise HTTPException(404, '仅桌面版提供内置演示')
    text=demo_model.reply(body.get('messages',[]))
    if body.get('stream'):
        return StreamingResponse(demo_model.chunks(text),media_type='text/event-stream')
    return {'choices':[{'message':{'role':'assistant','content':text}}]}


@app.get('/api/desktop/status')
def desktop_status():
    if os.environ.get('COURSEMATE_DESKTOP') != '1':
        raise HTTPException(404, '仅桌面版提供此功能')
    with db() as c:
        active=c.execute("SELECT COUNT(*) FROM documents WHERE status IN ('extracting','translating') OR analysis_status='running'").fetchone()[0]
        study=c.execute("SELECT COUNT(*) FROM study_pages WHERE status IN ('pending','running')").fetchone()[0]
        study+=c.execute("SELECT COUNT(*) FROM study_overviews WHERE status IN ('pending','running')").fetchone()[0]
    return {'active_jobs':active+study,'study_jobs':study}


app.include_router(study_ai.router)
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
