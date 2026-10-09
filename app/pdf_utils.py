"""PDF 引擎：文本块抽取、译制版 PDF 排版、课程总结 PDF 生成。

核心思路（"保留原始排版的对照翻译"）：
1. 用 PyMuPDF 按文本块（block）抽取原文及其位置、字号、颜色；
2. 把文本块交给 LLM 翻译（在 translate_service 中完成，带缓存）；
3. 用 redaction 移除原文字但保留图片/图形（images=PDF_REDACT_IMAGE_NONE），
   再在原始位置写回中文，字号自动收缩以适配原文本框 —— 版式、图表得以保留。

中文排版统一使用 PyMuPDF 内置 CJK 字体 china-s（无需系统字体文件），
并实现逐字断行（wrap_text），解决 CJK 无空格导致的溢出问题。
"""
import datetime
import re

import fitz  # PyMuPDF

PRIMARY = (36 / 255, 51 / 255, 126 / 255)
ACCENT = (124 / 255, 92 / 255, 232 / 255)
MUTED = (0.42, 0.44, 0.55)
BODY = (0.16, 0.18, 0.28)

try:
    _CJK = fitz.Font("china-s")

    def _text_len(s: str, size: float) -> float:
        return _CJK.text_length(s, fontsize=size)
except Exception:  # 极端环境下的宽度估算兜底
    def _text_len(s: str, size: float) -> float:
        return sum(size * (1.0 if ord(ch) > 0x2E80 else 0.55) for ch in s)


def _rgb(color_int) -> tuple:
    c = int(color_int or 0)
    return ((c >> 16 & 255) / 255, (c >> 8 & 255) / 255, (c & 255) / 255)


# ---------------- 抽取 ----------------
def extract_blocks(doc) -> list:
    """返回每页的文本块列表：[{bbox, text, size, color}, ...]"""
    pages = []
    for page in doc:
        data = page.get_text("dict")
        blocks = []
        for b in data.get("blocks", []):
            if b.get("type") != 0:
                continue
            lines, sizes, color = [], [], 0
            for line in b.get("lines", []):
                lt = "".join(s.get("text", "") for s in line.get("spans", []))
                if not lt.strip():
                    continue
                lines.append(lt)
                for s in line.get("spans", []):
                    sizes.append(s.get("size", 11))
                    if s.get("text", "").strip() and not color:
                        color = s.get("color", 0)
            text = "\n".join(lines).strip()
            if not text:
                continue
            avg = sum(sizes) / len(sizes) if sizes else 11
            blocks.append({
                "bbox": list(b["bbox"]),
                "text": text,
                "size": max(4.5, min(30, avg)),
                "color": color,
            })
        pages.append(blocks)
    return pages


def extract_doc_text(path) -> str:
    """整份课件的纯文本（带页码标记），供 AI 助教上下文与课程总结使用。"""
    doc = fitz.open(path)
    chunks = []
    for i, page in enumerate(doc, 1):
        chunks.append(f"【第 {i} 页】\n{page.get_text('text').strip()}")
    doc.close()
    return "\n\n".join(chunks)


# ---------------- 译制版排版 ----------------
def _tokens(line: str):
    """断行最小单元：英文单词保持完整，CJK 逐字断行。"""
    buf, out = "", []
    for ch in line:
        if ord(ch) < 128 and (ch.isalnum() or ch in "-'&/.,:%#()[]+<>="):
            buf += ch
        else:
            if buf:
                out.append(buf)
                buf = ""
            out.append(ch)
    if buf:
        out.append(buf)
    return out


def wrap_text(text: str, size: float, width: float) -> list:
    out_lines = []
    for raw in text.split("\n"):
        if not raw.strip():
            out_lines.append("")
            continue
        cur = ""
        for tk in _tokens(raw):
            cand = cur + tk
            if cur and _text_len(cand, size) > width:
                out_lines.append(cur.rstrip())
                cur = tk.lstrip()
            else:
                cur = cand
        if cur.strip():
            out_lines.append(cur.rstrip())
    return out_lines


def apply_page_translation(page, blocks: list, translations: list):
    """把一页的译文写回：先移除原文字（保留图形），再在原位写中文。

    使用 insert_htmlbox：自动处理 CJK 断行，空间不足时按比例缩放字号，
    保证译文完整落在原文本块区域内。
    """
    pairs = [(b, t) for b, t in zip(blocks, translations)
             if t and t.strip() and b["text"].strip()]
    if not pairs:
        return
    for b, _ in pairs:
        try:
            page.add_redact_annot(fitz.Rect(b["bbox"]), fill=False)
        except TypeError:
            page.add_redact_annot(fitz.Rect(b["bbox"]))
    try:
        page.apply_redactions(images=getattr(fitz, "PDF_REDACT_IMAGE_NONE", 0))
    except TypeError:
        page.apply_redactions()
    for b, zh in pairs:
        rect = fitz.Rect(b["bbox"])
        # 轻微外扩，避免贴边裁切；标题块向下多留一点行高余量
        rect = fitz.Rect(max(0, rect.x0 - 1.5), max(0, rect.y0 - 1.5),
                         min(page.rect.x1, rect.x1 + 2),
                         min(page.rect.y1, rect.y1 + max(3, b["size"] * 0.45)))
        r, g, b_ch = _rgb(b["color"])
        hex_color = f"#{int(r*255):02x}{int(g*255):02x}{int(b_ch*255):02x}"
        html = (f'<div style="font-family:sans-serif;'
                f'font-size:{b["size"]:.1f}px;color:{hex_color};'
                f'line-height:1.25">'
                + esc_html(zh).replace("\n", "<br>") + "</div>")
        try:
            page.insert_htmlbox(rect, html, scale_low=0)
        except Exception:
            pass  # 单块失败不影响整页


def esc_html(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# ---------------- 课程总结 PDF ----------------
_MD_INLINE = [
    (re.compile(r"\*\*(.+?)\*\*"), r"\1"),
    (re.compile(r"__(.+?)__"), r"\1"),
    (re.compile(r"`(.+?)`"), r"\1"),
    (re.compile(r"\*(.+?)\*"), r"\1"),
]


def _strip_inline(s: str) -> str:
    for rx, rep in _MD_INLINE:
        s = rx.sub(rep, s)
    return s


class _PdfWriter:
    """简易流式排版器：自动分页 + 页眉品牌线 + 页脚页码。"""

    def __init__(self, width=595, height=842, margin=54):
        self.doc = fitz.open()
        self.width, self.height, self.margin = width, height, margin
        self.page = None
        self.y = 0
        self._new_page()

    def _new_page(self):
        self.page = self.doc.new_page(width=self.width, height=self.height)
        self.y = self.margin + 22
        self.page.draw_line(fitz.Point(self.margin, 36),
                            fitz.Point(self.width - self.margin, 36),
                            color=ACCENT, width=0.8)
        try:
            self.page.insert_htmlbox(
                fitz.Rect(self.margin, 16, self.width - self.margin, 34),
                '<div style="text-align:right;font-family:sans-serif;'
                'font-size:7.5px;color:#6B708C">XJTLU CourseMate · 西浦课件通</div>')
        except Exception:
            pass

    def ensure(self, need: float):
        if self.y + need > self.height - self.margin - 10:
            self._new_page()

    def text_block(self, text, size, color=BODY, indent=0,
                   lead=1.5, space_before=0, space_after=4):
        if not text.strip():
            return
        width = self.width - self.margin * 2 - indent
        n_lines = max(1, len(wrap_text(text, size, width)))
        need = n_lines * size * lead + 4
        self.ensure(need + space_before + space_after)
        self.y += space_before
        rect = fitz.Rect(self.margin + indent, self.y,
                         self.margin + indent + width, self.y + need)
        hexc = f"#{int(color[0]*255):02x}{int(color[1]*255):02x}{int(color[2]*255):02x}"
        html = (f'<div style="font-family:sans-serif;font-size:{size}px;'
                f'color:{hexc};line-height:{lead}">'
                + esc_html(text).replace("\n", "<br>") + "</div>")
        try:
            self.page.insert_htmlbox(rect, html, scale_low=0)
        except Exception:
            pass
        self.y += need + space_after

    def rule(self):
        self.ensure(14)
        self.page.draw_line(fitz.Point(self.margin, self.y),
                            fitz.Point(self.width - self.margin, self.y),
                            color=(0.85, 0.86, 0.92), width=0.7)
        self.y += 14


def summary_markdown_to_pdf(md_text: str, title: str, subtitle: str, out_path: str):
    """把 Markdown 课程总结渲染成 A4 PDF（支持标题/列表/引用/表格/代码块/分隔线）。"""
    w = _PdfWriter()
    w.text_block(title, 19, color=PRIMARY, space_after=2)
    w.text_block(subtitle, 9.5, color=MUTED, space_after=6)
    w.rule()

    in_code = False
    for raw in md_text.splitlines():
        line = raw.rstrip()
        s = line.strip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            w.text_block(line if line else " ", 9.3, color=(0.25, 0.30, 0.42), indent=10, space_after=1)
            continue
        if not s:
            w.y += 5
            continue
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if cells and all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue
            w.text_block(" ｜ ".join(_strip_inline(c) for c in cells), 9.8, indent=4, space_after=2)
            continue
        m = re.match(r"^(#{1,4})\s+(.*)", s)
        if m:
            level = len(m.group(1))
            txt = _strip_inline(m.group(2))
            size = {1: 16, 2: 13.5, 3: 11.8, 4: 11}.get(level, 11)
            color = PRIMARY if level <= 2 else ACCENT
            w.text_block(txt, size, color=color, space_before=8, space_after=3)
            if level == 1:
                w.rule()
            continue
        if s in ("---", "***", "___"):
            w.rule()
            continue
        m = re.match(r"^[-*+]\s+(.*)", s)
        if m:
            w.text_block("• " + _strip_inline(m.group(1)), 10.6, indent=10, space_after=2)
            continue
        m = re.match(r"^(\d+)[.、)]\s*(.*)", s)
        if m:
            w.text_block(f"{m.group(1)}. {_strip_inline(m.group(2))}", 10.6, indent=10, space_after=2)
            continue
        m = re.match(r"^>\s?(.*)", s)
        if m:
            w.text_block(_strip_inline(m.group(1)), 10.2, color=MUTED, indent=14, space_after=2)
            continue
        w.text_block(_strip_inline(s), 10.6, space_after=4)

    total = w.doc.page_count
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    for i, page in enumerate(w.doc, 1):
        try:
            page.insert_htmlbox(
                fitz.Rect(0, 812, 595, 832),
                f'<div style="text-align:center;font-family:sans-serif;'
                f'font-size:8px;color:#6B708C">第 {i} / {total} 页 · 生成于 {stamp}</div>')
        except Exception:
            pass
    try:
        w.doc.subset_fonts()
    except Exception:
        pass
    w.doc.save(out_path, garbage=4, deflate=True, deflate_fonts=True)
    w.doc.close()
