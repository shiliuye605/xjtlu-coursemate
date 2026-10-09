"""数据库层：SQLite。

设计要点（对应课程《数据库系统》知识点）：
- courses 1:N documents（外键 + ON DELETE CASCADE）
- translation_cache：翻译结果缓存（内容哈希为主键），避免重复调用 LLM，省钱省能源
- summaries / summary_history：课程总结的"当前版"与"历史版本"分离，支持审计
- settings：用户本地配置（API Key 明文存入本地数据库，调用时发送至模型端点）
"""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("COURSEMATE_DATA_DIR", str(BASE_DIR / "data"))).resolve()
FILES_DIR = DATA_DIR / "files"
SUMMARY_DIR = DATA_DIR / "summaries"
DB_PATH = DATA_DIR / "app.db"

for _d in (DATA_DIR, FILES_DIR, SUMMARY_DIR):
    _d.mkdir(parents=True, exist_ok=True)

SCHEMA = """
CREATE TABLE IF NOT EXISTS courses(
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    code        TEXT DEFAULT '',
    teacher     TEXT DEFAULT '',
    created_at  TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS documents(
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id       INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    filename        TEXT NOT NULL,
    page_count      INTEGER DEFAULT 0,
    char_count      INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'uploaded',      -- uploaded|extracting|translating|done|failed
    progress        INTEGER DEFAULT 0,
    error           TEXT DEFAULT '',
    original_path   TEXT DEFAULT '',
    translated_path TEXT DEFAULT '',
    text_path       TEXT DEFAULT '',
    created_at      TEXT DEFAULT (datetime('now','localtime')),
    translated_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_documents_course ON documents(course_id);

CREATE TABLE IF NOT EXISTS translation_cache(
    hash        TEXT PRIMARY KEY,                  -- sha256(model + 原文)
    translated  TEXT NOT NULL,
    created_at  TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS summaries(
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id        INTEGER NOT NULL UNIQUE REFERENCES courses(id) ON DELETE CASCADE,
    markdown         TEXT DEFAULT '',
    pdf_path         TEXT DEFAULT '',
    included_doc_ids TEXT DEFAULT '[]',
    updated_at       TEXT
);

CREATE TABLE IF NOT EXISTS summary_history(
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id        INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    markdown         TEXT DEFAULT '',
    pdf_path         TEXT DEFAULT '',
    included_doc_ids TEXT DEFAULT '[]',
    note             TEXT DEFAULT '',
    created_at       TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS chat_messages(
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id   INTEGER,
    document_id INTEGER,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_chat_course ON chat_messages(course_id);

CREATE TABLE IF NOT EXISTS settings(
    key   TEXT PRIMARY KEY,
    value TEXT DEFAULT ''
);
"""


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with db() as c:
        c.executescript(SCHEMA)
        # 轻量迁移：旧库补列（IMIS 课程辅导分析状态）
        cols = {r[1] for r in c.execute("PRAGMA table_info(documents)")}
        if "analysis_status" not in cols:
            c.execute("ALTER TABLE documents ADD COLUMN analysis_status TEXT DEFAULT ''")
        if "analyzed_at" not in cols:
            c.execute("ALTER TABLE documents ADD COLUMN analyzed_at TEXT")


# ---------------- settings ----------------
def get_settings() -> dict:
    with db() as c:
        rows = c.execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: r["value"] for r in rows}


def set_settings(d: dict):
    with db() as c:
        for k, v in d.items():
            c.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (k, str(v)),
            )


def llm_config_ready(cfg: dict) -> bool:
    return bool(cfg.get("api_base") and cfg.get("api_key") and cfg.get("model"))
