"""数据库层：SQLite。

设计要点（对应课程《数据库系统》知识点）：
- courses 1:N documents（外键 + ON DELETE CASCADE）
- translation_cache：翻译结果缓存（内容哈希为主键），避免重复调用 LLM，省钱省能源
- summaries / summary_history：课程总结的"当前版"与"历史版本"分离，支持审计
- settings：用户本地配置（API Key 只存本地库，不出本机）
"""
import sqlite3
import os
from contextlib import contextmanager
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get('COURSEMATE_DATA_DIR', str(BASE_DIR / 'data'))).expanduser().resolve()
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
        if "status_message" not in cols:
            c.execute("ALTER TABLE documents ADD COLUMN status_message TEXT DEFAULT ''")
        if "retry_at" not in cols:
            c.execute("ALTER TABLE documents ADD COLUMN retry_at REAL DEFAULT 0")
        chat_cols = {r[1] for r in c.execute('PRAGMA table_info(chat_messages)')}
        if 'page_number' not in chat_cols:
            c.execute('ALTER TABLE chat_messages ADD COLUMN page_number INTEGER DEFAULT 0')
        if 'scope_key' not in chat_cols:
            c.execute("ALTER TABLE chat_messages ADD COLUMN scope_key TEXT DEFAULT ''")
        c.executescript('''
        CREATE TABLE IF NOT EXISTS study_pages(
            document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            page_number INTEGER NOT NULL,
            source TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            model_signature TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            markdown TEXT NOT NULL DEFAULT '',
            error TEXT NOT NULL DEFAULT '',
            attempts INTEGER NOT NULL DEFAULT 0,
            retry_at REAL NOT NULL DEFAULT 0,
            revision INTEGER NOT NULL,
            PRIMARY KEY(document_id,page_number)
        );
        CREATE INDEX IF NOT EXISTS idx_study_pending ON study_pages(status,retry_at,document_id,page_number);
        CREATE TABLE IF NOT EXISTS study_page_cache(
            cache_key TEXT PRIMARY KEY, markdown TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS study_overviews(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            scope_key TEXT NOT NULL UNIQUE,
            document_ids TEXT NOT NULL,
            model_signature TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            markdown TEXT NOT NULL DEFAULT '',
            error TEXT NOT NULL DEFAULT '',
            pdf_path TEXT NOT NULL DEFAULT '',
            generation INTEGER NOT NULL DEFAULT 1,
            manual INTEGER NOT NULL DEFAULT 0,
            attempts INTEGER NOT NULL DEFAULT 0,
            retry_at REAL NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT '',
            origin TEXT NOT NULL DEFAULT 'api'
        );
        ''')


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
