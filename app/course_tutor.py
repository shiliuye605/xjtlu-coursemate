"""IMIS 课程辅导分析：翻译完成后自动按 imis-course-tutor skill 深度解读课件。

技能说明与课程知识库内置在 app/skill/（来源：skill-package，XJTLU IMIS 课程辅导技能）。
分析流程遵循 SKILL.md：识别课程 → 结构总览 → 核心概念详解 → 考点提醒 → 现实应用 → 自测题。
结果以 Markdown 存到 files/{doc_id}/analysis.md，前端「AI 辅导分析」面板展示。
"""
import datetime
import os
import threading
import traceback

from .database import FILES_DIR, db, get_settings, llm_config_ready
from . import llm

SKILL_DIR = os.path.join(os.path.dirname(__file__), "skill")
MAX_COURSEWARE_CHARS = 30000  # 送入模型的课件全文上限（GLM-4.5-flash 128K 上下文足够）

_lock = threading.Lock()
_running: set = set()
_skill_cache = None  # (skill 正文, 课程知识库)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _load_skill():
    global _skill_cache
    with _lock:
        if _skill_cache is None:
            skill_md = _read(os.path.join(SKILL_DIR, "SKILL.md"))
            if skill_md.startswith("---"):  # 剥离 frontmatter
                skill_md = skill_md.split("---", 2)[2]
            curriculum = _read(os.path.join(SKILL_DIR, "xjtlu-imis-curriculum.md"))
            _skill_cache = (skill_md, curriculum)
    return _skill_cache


def _set_status(doc_id: int, **fields):
    with db() as c:
        cols = ", ".join(f"{k}=?" for k in fields)
        c.execute(f"UPDATE documents SET {cols} WHERE id=?", (*fields.values(), doc_id))


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def start_analysis(doc_id: int) -> bool:
    """Compatibility entry point; the persistent worker owns all new analysis."""
    from .study_ai import _document, _sources, register_pages
    doc=_document(doc_id)
    register_pages(doc_id,_sources(doc))
    return True


def _run(doc_id: int):
    out_path = str(FILES_DIR / str(doc_id) / "analysis.md")
    try:
        cfg = get_settings()
        if not llm_config_ready(cfg):
            _set_status(doc_id, analysis_status="failed", analyzed_at="")
            return
        with db() as c:
            doc = c.execute("SELECT filename, text_path FROM documents WHERE id=?",
                            (doc_id,)).fetchone()
        if not doc or not doc["text_path"] or not os.path.exists(doc["text_path"]):
            _set_status(doc_id, analysis_status="failed", analyzed_at="")
            return
        _set_status(doc_id, analysis_status="running", analyzed_at="")

        skill_md, curriculum = _load_skill()
        text = _read(doc["text_path"])[:MAX_COURSEWARE_CHARS]
        system = (
            "你是西交利物浦大学（XJTLU）IMIS 专业的课程辅导老师。"
            "请严格按下面的技能说明处理学生提供的课件，输出一份完整的课件辅导分析。\n\n"
            "===== 技能说明（imis-course-tutor）=====\n" + skill_md +
            "\n\n===== 课程知识库（xjtlu-imis-curriculum.md）=====\n" + curriculum +
            "\n\n===== 输出要求 =====\n"
            "1. 只输出 Markdown 正文，不要任何额外解释或开场白；\n"
            "2. 按技能说明的输出格式组织：课程定位 → 课件结构总览 → 核心概念详解"
            "（说人话→详细讲→术语对照→重点标记）→ 考点提醒 → 现实工作应用 → 自测题；\n"
            "3. 【重要】所有大纲、结构图、图解一律直接用嵌套 Markdown 无序列表表达层级"
            "（一级用 \"- \"，子级缩进两个空格，最多四级），网页前端会自动渲染成带连接线的树形图。"
            "不要用 ``` 代码块包裹列表；严禁输出 ├── └── │ 等 ASCII 字符画"
            "（技能说明中的 ASCII 图规范仅适用于终端环境，本网页场景不适用）；\n"
            "4. 内容必须基于课件原文，不要编造课件中没有的公式、数字或考点；"
            "考点提示需注明是推断、以老师 PPT 为准；\n"
            "5. 这是自动生成的单份课件分析（不是对话），跳过「主动询问」环节；"
            "自测题只出题不给答案。"
        )
        user = f"课件文件名：{doc['filename']}\n\n课件全文如下：\n\n{text}"
        # 关闭 GLM-4.5 系列的思维链：否则思考过程会耗尽输出预算，正文 content 为空
        md = llm.chat_once(cfg["api_base"], cfg["api_key"], cfg["model"],
                           [{"role": "system", "content": system},
                            {"role": "user", "content": user}],
                           temperature=0.3, max_tokens=8000, timeout=(15, 600),
                           extra={"thinking": {"type": "disabled"}})
        md = md.strip()
        if not md:
            raise llm.LLMError("模型返回空内容")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(md)
        _set_status(doc_id, analysis_status="done", analyzed_at=_now())
        print(f"[tutor] 文档 {doc_id} 辅导分析完成（{len(md)} 字符）")
    except Exception:
        traceback.print_exc()
        _set_status(doc_id, analysis_status="failed", analyzed_at="")
    finally:
        with _lock:
            _running.discard(doc_id)
