"""离线演示 LLM 服务（OpenAI Chat Completions 协议模拟器）。

用途：没有 API Key 时也能完整体验「上传 → 翻译 → 总结 → AI 助教」全流程。
设置页选择「离线演示」预设（http://127.0.0.1:9999/v1，Key 任意，模型 mock-llm）。

启动：python tests/mock_llm.py
"""
import json
import re
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

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

> 本总结由离线演示模式生成，真实模型效果需另行评估；此处仅演示应用流程。
"""

MOCK_CHAT = """你好！我是**离线演示模式**的 AI 助教 😊

当前请求未接入真实模型。配置你的 API Key 后（设置页 → 选择 DeepSeek / 智谱 GLM / OpenAI / Kimi），我可以：

1. **基于课件内容答疑** —— 引用具体页码和原文术语
2. **生成复习题与考点预测** —— 结合整门课的课件
3. **解释专业概念** —— 中英双语对照讲解

> 演示模式下，翻译与总结功能同样可用（会标注"演示译文"），用于体验完整流程。
"""


# 只为仓库内自生成示例提供预设译文；不模拟通用翻译能力。
DEMO_TRANSLATIONS = {
    "Agenda": "课程提纲",
    "Relational Model Essentials": "关系模型基础",
    "Normalization": "数据库规范化",
    "Transactions & ACID": "事务与 ACID 原则",
    "DEMO · Information Management": "DEMO · 信息管理（模拟课程）",
    "Project-generated study material · Not official courseware": "自生成学习示例 · 非官方课件",
    "What is a Database Management System (DBMS)?": "什么是数据库管理系统（DBMS）？",
    "The Three-Schema Architecture: External, Conceptual, Internal": "三级模式架构：外模式、概念模式、内模式",
    "Entity-Relationship (ER) Model: entities, attributes, relationships": "实体关系（ER）模型：实体、属性、联系",
    "From ER diagram to relational schema": "从 ER 图转换为关系模式",
    "Why data modelling matters for e-business applications": "数据建模为何对电子商务应用重要",
    "A relation is a table; a tuple is a row; an attribute is a column": "关系是一张表；元组是一行；属性是一列",
    "Candidate key vs. primary key vs. foreign key": "候选键、主键与外键的区别",
    "Referential integrity protects relationships between tables": "参照完整性维护表之间的关系",
    "SQL families: DDL (CREATE), DML (SELECT/INSERT/UPDATE), DCL (GRANT)": "SQL 分类：DDL 定义、DML 操作、DCL 权限控制",
    "Indexes trade storage for faster query response time": "索引用额外存储空间换取更快的查询响应",
    "1NF: atomic values, no repeating groups": "第一范式：值保持原子性，不出现重复组",
    "2NF: remove partial dependency on part of a composite key": "第二范式：消除对复合键一部分的部分依赖",
    "3NF: remove transitive dependency (non-key depends on non-key)": "第三范式：消除非键属性之间的传递依赖",
    "BCNF: every determinant must be a candidate key": "BCNF：每个决定因素都必须是候选键",
    "Goal: eliminate insertion, update and deletion anomalies": "目标：消除插入、更新和删除异常",
    "A transaction is a logical unit of work": "事务是一个逻辑工作单元",
    "Atomicity: all or nothing": "原子性：全部完成，或全部不执行",
    "Consistency: constraints hold before and after": "一致性：事务执行前后均满足约束",
    "Isolation: concurrent transactions do not interfere": "隔离性：并发事务之间互不干扰",
    "Durability: committed changes survive system failure": "持久性：已提交修改在系统故障后仍保留",
    "From E-Commerce to E-Business": "从电子商务交易到数字化业务",
    "Business Models on the Web": "互联网商业模式",
    "Digital Sustainability & Green IT": "数字化可持续发展与绿色 IT",
    "Seminar Preparation": "研讨课准备",
    "E-commerce covers online transactions; e-business covers the whole digital value chain": "电子商务涵盖线上交易；数字化业务涵盖整个数字价值链",
    "Key models: B2B, B2C, C2C, O2O and platform business": "主要模式：B2B、B2C、C2C、O2O 与平台业务",
    "Network effects: value grows with the number of users": "网络效应：价值随用户数量增加而提高",
    "Long-tail economics enabled by digital shelves": "数字货架支持长尾经济",
    "Case: platform companies and two-sided markets": "案例：平台企业与双边市场",
    "Portal, e-tailer, content provider, transaction broker": "门户、网络零售商、内容提供商、交易中介",
    "Market creator, service provider, community provider": "市场创建者、服务提供商、社区提供商",
    "Revenue models: advertising, subscription, transaction fee, affiliate": "收入模式：广告、订阅、交易佣金、联盟营销",
    "Crowdsourcing and the sharing economy": "众包与共享经济",
    "Metrics: conversion rate, churn, customer lifetime value (CLV)": "指标：转化率、流失率、客户终身价值（CLV）",
    "ICT accounts for a growing share of global energy use": "信息通信技术占全球能源使用的比例持续增加",
    "Green IT: efficient hardware, virtualization, cloud consolidation": "绿色 IT：高效硬件、虚拟化、云资源整合",
    "Green IS: using information systems to enable sustainable business": "绿色信息系统：用信息系统支持可持续业务",
    "Caching and incremental processing reduce redundant computation": "缓存与增量处理减少重复计算",
    "Sustainable software engineering: measure, then optimize": "可持续软件工程：先测量，再优化",
    "Pick one e-business model and one database concept from Lecture 01": "选择一个数字商业模式与第一讲的一个数据库概念",
    "Explain how the database supports the business model": "解释数据库如何支持这个商业模式",
    "Identify one sustainability risk and one mitigation strategy": "识别一个可持续发展风险与一种缓解策略",
    "Submit a one-page outline before the seminar": "研讨课前提交一页提纲",
}

MOCK_ANALYSIS = """# 数据库系统 · 课件解读（模拟演示）

> 这是根据仓库自生成示例编写的固定回复，不是真实模型生成结果。

## 一、课程定位
数据库系统与信息管理：理解如何把业务需求组织为可靠的数据结构。

## 二、课件结构总览
- 数据库系统
  - 三级模式架构
  - 实体关系 ER 模型
- 关系模型
  - 主键与外键
  - 参照完整性与 SQL
- 数据库规范化
  - 1NF、2NF、3NF、BCNF
  - 插入、更新与删除异常
- 事务管理
  - 原子性、一致性、隔离性、持久性

## 三、核心概念详解
**说人话：** ER 模型先描述业务里有哪些对象，以及它们如何关联；关系模式再把这些对象整理成表。

**术语对照：** Entity 实体；Attribute 属性；Relationship 联系；Primary Key 主键；Foreign Key 外键。

## 四、复习提示
把 ER 图转换为关系表时，要注意多对多联系需要中间表。这是演示复习建议，实际考核范围以授课教师安排为准。

## 五、工作应用
电商订单把客户、商品和订单关联起来；外键维护引用关系，事务保证订单操作的一致性。

## 六、自测题
1. 主键和外键有什么区别？
2. 转账为何需要事务的原子性？
"""


def _demo_translate(text):
    normalized = " ".join(text.split())
    return "【演示】" + DEMO_TRANSLATIONS.get(normalized, "预设词典未收录，保留原文：" + text)


def _build_reply(messages):
    system = " ".join(m.get("content", "") for m in messages if m.get("role") == "system")
    user = " ".join(m.get("content", "") for m in messages if m.get("role") == "user")
    if "翻译引擎" in system:
        m = re.search(r"\[.*\]", user, re.S)
        arr = json.loads(m.group(0)) if m else []
        return json.dumps([_demo_translate(t) for t in arr], ensure_ascii=False)
    if "课件辅导分析" in system:
        return MOCK_ANALYSIS
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
    import os
    HTTPServer(("127.0.0.1", int(os.environ.get("COURSEMATE_MOCK_PORT", "9999"))), Handler).serve_forever()
