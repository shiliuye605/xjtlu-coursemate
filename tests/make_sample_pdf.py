"""生成内置示例英文课件（两份模拟讲义 PDF），存入 sample_data/。

运行：python tests/make_sample_pdf.py
"""
import fitz

PRIMARY = (36/255, 51/255, 126/255)
ACCENT = (124/255, 92/255, 232/255)
GRAY = (0.45, 0.47, 0.58)

LECTURES = [
    {
        "name": "Lecture_01_Database_Systems.pdf",
        "title": "Database Systems & Information Management",
        "course": "DEMO · Information Management",
        "footer": "Project-generated study material · Not official courseware",
        "pages": [
            ("Agenda", [
                "What is a Database Management System (DBMS)?",
                "The Three-Schema Architecture: External, Conceptual, Internal",
                "Entity-Relationship (ER) Model: entities, attributes, relationships",
                "From ER diagram to relational schema",
                "Why data modelling matters for e-business applications",
            ]),
            ("Relational Model Essentials", [
                "A relation is a table; a tuple is a row; an attribute is a column",
                "Candidate key vs. primary key vs. foreign key",
                "Referential integrity protects relationships between tables",
                "SQL families: DDL (CREATE), DML (SELECT/INSERT/UPDATE), DCL (GRANT)",
                "Indexes trade storage for faster query response time",
            ]),
            ("Normalization", [
                "1NF: atomic values, no repeating groups",
                "2NF: remove partial dependency on part of a composite key",
                "3NF: remove transitive dependency (non-key depends on non-key)",
                "BCNF: every determinant must be a candidate key",
                "Goal: eliminate insertion, update and deletion anomalies",
            ]),
            ("Transactions & ACID", [
                "A transaction is a logical unit of work",
                "Atomicity: all or nothing",
                "Consistency: constraints hold before and after",
                "Isolation: concurrent transactions do not interfere",
                "Durability: committed changes survive system failure",
            ]),
        ],
    },
    {
        "name": "Lecture_02_EBusiness_Sustainability.pdf",
        "title": "E-Business Models & Digital Sustainability",
        "course": "DEMO · Information Management",
        "footer": "Project-generated study material · Not official courseware",
        "pages": [
            ("From E-Commerce to E-Business", [
                "E-commerce covers online transactions; e-business covers the whole digital value chain",
                "Key models: B2B, B2C, C2C, O2O and platform business",
                "Network effects: value grows with the number of users",
                "Long-tail economics enabled by digital shelves",
                "Case: platform companies and two-sided markets",
            ]),
            ("Business Models on the Web", [
                "Portal, e-tailer, content provider, transaction broker",
                "Market creator, service provider, community provider",
                "Revenue models: advertising, subscription, transaction fee, affiliate",
                "Crowdsourcing and the sharing economy",
                "Metrics: conversion rate, churn, customer lifetime value (CLV)",
            ]),
            ("Digital Sustainability & Green IT", [
                "ICT accounts for a growing share of global energy use",
                "Green IT: efficient hardware, virtualization, cloud consolidation",
                "Green IS: using information systems to enable sustainable business",
                "Caching and incremental processing reduce redundant computation",
                "Sustainable software engineering: measure, then optimize",
            ]),
            ("Seminar Preparation", [
                "Pick one e-business model and one database concept from Lecture 01",
                "Explain how the database supports the business model",
                "Identify one sustainability risk and one mitigation strategy",
                "Submit a one-page outline before the seminar",
            ]),
        ],
    },
]


def build(lecture, out_path):
    doc = fitz.open()
    for title, bullets in lecture["pages"]:
        page = doc.new_page(width=720, height=405)  # 16:9 幻灯片
        page.draw_rect(fitz.Rect(0, 0, 720, 96), color=None, fill=PRIMARY)
        page.draw_rect(fitz.Rect(0, 96, 720, 100), color=None, fill=ACCENT)
        page.insert_textbox(fitz.Rect(36, 12, 684, 64), title,
                            fontname="helv", fontsize=26, color=(1, 1, 1))
        page.insert_textbox(fitz.Rect(36, 60, 660, 88), lecture["course"],
                            fontname="helv", fontsize=10, color=(0.78, 0.80, 0.95))
        y = 128
        for b in bullets:
            page.draw_circle(fitz.Point(44, y + 8), 3.2, color=None, fill=ACCENT)
            page.insert_textbox(fitz.Rect(58, y, 676, y + 52), b,
                                fontname="helv", fontsize=13.5, color=(0.13, 0.15, 0.25))
            y += 54
        page.insert_textbox(fitz.Rect(36, 378, 684, 398), lecture["footer"],
                            fontname="helv", fontsize=8.5, color=GRAY, align=fitz.TEXT_ALIGN_RIGHT)
    doc.save(out_path, garbage=3, deflate=True)
    doc.close()
    print("生成:", out_path)


if __name__ == "__main__":
    import os
    out_dir = os.path.join(os.path.dirname(__file__), "..", "sample_data")
    os.makedirs(out_dir, exist_ok=True)
    for lec in LECTURES:
        build(lec, os.path.join(out_dir, lec["name"]))
