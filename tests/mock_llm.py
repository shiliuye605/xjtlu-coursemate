"""离线演示 LLM 服务（OpenAI Chat Completions 协议模拟器）。

用途：没有 API Key 时也能完整体验「上传 → 翻译 → 总结 → AI 助教」全流程。
设置页选择「离线演示」预设（http://127.0.0.1:9999/v1，Key 任意，模型 mock-llm）。

启动：python tests/mock_llm.py
"""
import json
import re
import time
import sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from app.demo_model import reply as study_demo_reply

MOCK_SUMMARY = """# 课程总结：示例课程

## 一、课程概览

本课程围绕**数据库系统与电子商务**两条主线展开：先介绍关系数据库的核心概念（DBMS、ER Model、SQL、范式），再延伸到电子商务模式（B2B / B2C / C2C）与数字化可持续发展（Digital Sustainability）。

## 二、核心知识点

### 2.1 数据库系统
- DBMS 三层架构：External / Conceptual / Internal Schema
- ER 模型三要素：实体、属性、联系（1:1、1:N、M:N）
- SQL 三大类语句：DDL、DML、DCL
- 规范化：1NF → 2NF → 3NF → BCNF，消除插入/更新/删除异常
- 事务 ACID：原子性、一致性、隔离性、持久性

### 2.2 电子商务与可持续发展
- E-Business 模式：B2B、B2C、C2C、O2O 及平台经济
- 数字化可持续发展：绿色 IT、系统能效、缓存复用降低算力消耗

## 三、重点与考点提示

| 易考知识点 | 复习建议 |
| --- | --- |
| ER 图转关系模式 | 注意 M:N 联系需要中间表 |
| 3NF 判定 | 先找候选键，再看部分/传递依赖 |
| ACID 区分 | 结合转账例子记忆 |

## 四、已纳入的课件清单

- Lecture_01_Database_Systems.pdf
- Lecture_02_EBusiness_Sustainability.pdf

> 本总结由离线演示模式生成，配置真实 API Key 后可获得基于课件原文的高质量总结。
"""

MOCK_CHAT = """你好！我是**离线演示模式**的 AI 助教 😊

当前请求未接入真实模型。配置你的 API Key 后（设置页 → 选择 DeepSeek / 智谱 GLM / OpenAI / Kimi），我可以：

1. **基于课件内容答疑** —— 引用具体页码和原文术语
2. **生成复习题与考点预测** —— 结合整门课的课件
3. **解释专业概念** —— 中英双语对照讲解

> 演示模式下，翻译与总结功能同样可用（会标注"演示译文"），用于体验完整流程。
"""


def _build_reply(messages):
    system = " ".join(m.get("content", "") for m in messages if m.get("role") == "system")
    user = " ".join(m.get("content", "") for m in messages if m.get("role") == "user")
    if 'KXT_PAGE_EXPLANATIONS_V1' in system or 'KXT_COURSE_OVERVIEW_V1' in system:
        return study_demo_reply(messages)
    if "翻译引擎" in system:
        if user.strip().startswith('{'):
            entries = json.loads(user)
            return json.dumps({key: "演示译文：" + text for key, text in entries.items()}, ensure_ascii=False)
        m = re.search(r"\[.*\]", user, re.S)
        arr = json.loads(m.group(0)) if m else []
        return json.dumps(["演示译文：" + t for t in arr], ensure_ascii=False)
    if "教务助理" in system or "课程总结" in user:
        return MOCK_SUMMARY
    return MOCK_CHAT


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _sse(self, obj):
        return ("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode("utf-8")

    def do_POST(self):
        if not self.path.rstrip().endswith("/chat/completions"):
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        messages = body.get("messages", [])
        reply = _build_reply(messages)
        model = body.get("model", "mock-llm")

        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.end_headers()
            # 把回复切成若干段模拟流式输出
            step = max(6, len(reply) // 14)
            for i in range(0, len(reply), step):
                chunk = reply[i:i + step]
                self.wfile.write(self._sse({
                    "choices": [{"delta": {"content": chunk}}]}))
                self.wfile.flush()
                time.sleep(0.05)
            self.wfile.write(b"data: [DONE]\n\n")
            return

        out = json.dumps({
            "id": "mock", "object": "chat.completion", "model": model,
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": reply},
                         "finish_reason": "stop"}],
        }, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


if __name__ == "__main__":
    print("Mock LLM（离线演示）运行于 http://127.0.0.1:9999/v1 — Ctrl+C 停止")
    HTTPServer(("127.0.0.1", 9999), Handler).serve_forever()
