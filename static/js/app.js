/* 西浦课件通 · XJTLU CourseMate —— 前端逻辑 */
"use strict";

const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

const state = {
  courses: [],
  courseId: null,
  docs: [],
  doc: null,          // 当前打开的文档记录
  pollTimer: null,
  settings: null,
  sending: false,
  editingId: null,    // 正在编辑的课程 ID（null = 新建模式）
};

pdfjsLib.GlobalWorkerOptions.workerSrc = "/vendor/pdf.worker.min.js";

/* ---------------- 基础工具 ---------------- */
async function api(path, opts = {}) {
  const init = { ...opts };
  if (init.body && !(init.body instanceof FormData)) {
    init.headers = { "Content-Type": "application/json", ...(init.headers || {}) };
  }
  const r = await fetch("/api" + path, init);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    throw new Error(msg);
  }
  return r.json();
}

function toast(msg, type = "") {
  const el = document.createElement("div");
  el.className = "toast " + type;
  el.textContent = msg;
  $("#toast-wrap").appendChild(el);
  setTimeout(() => { el.style.opacity = "0"; el.style.transition = ".4s"; }, 2600);
  setTimeout(() => el.remove(), 3100);
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* 内联 Markdown 片段渲染（输入已转义） */
const inlineMd = (s) => s
  .replace(/`([^`]+)`/g, "<code>$1</code>")
  .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
  .replace(/\*([^*]+)\*/g, "<i>$1</i>");

/* 代码块内容若是纯嵌套列表 → 渲染为树形列表 */
function listBlockHtml(block) {
  const lines = block.split("\n").filter((l) => l.trim());
  if (!lines.length) return null;
  let html = "";
  const lists = [];
  for (const raw of lines) {
    const li = raw.match(/^(\s*)([-*+]|\d+[.、)])\s+(.*)/);
    if (!li) return null;
    const level = Math.min(4, Math.floor(li[1].replace(/\t/g, "  ").length / 2));
    const want = /^\d/.test(li[2]) ? "ol" : "ul";
    while (lists.length > level + 1) html += lists.pop() === "ol" ? "</ol>" : "</ul>";
    if (lists[lists.length - 1] !== want) {
      if (lists.length) html += lists.pop() === "ol" ? "</ol>" : "</ul>";
      html += want === "ol" ? "<ol>" : "<ul>";
      lists.push(want);
    }
    while (lists.length < level + 1) { html += want === "ol" ? "<ol>" : "<ul>"; lists.push(want); }
    html += `<li>${inlineMd(li[3])}</li>`;
  }
  while (lists.length) html += lists.pop() === "ol" ? "</ol>" : "</ul>";
  return html || null;
}

/* 代码块内容若是 ASCII 树（├ └ │）→ 解析渲染为树形列表 */
function asciiTreeHtml(block) {
  const lines = block.split("\n").filter((l) => l.trim());
  const branchLines = lines.filter((l) => /[├└]/.test(l));
  if (branchLines.length < 2 || branchLines.length < lines.length * 0.5) return null;
  const root = { label: null, children: [] };
  const stack = [{ lv: -1, n: root }];
  for (const line of lines) {
    const idx = line.search(/[├└]/);
    if (idx < 0) {
      // 无分支符的首行通常是树的根标题
      if (!root.label && !/^[─\-]+$/.test(line.trim())) root.label = line.trim();
      continue;
    }
    const prefix = line.slice(0, idx);
    // 层级 = │ 计数 与 缩进宽度/4 取大者（兼容 2/4 空格缩进与 └ 纯空格子树）
    const lv = Math.min(5, Math.max((prefix.match(/[│|]/g) || []).length,
                                    Math.floor(prefix.replace(/[│|]/g, "    ").length / 4)));
    const label = line.slice(idx + 1).replace(/^[─\-]+\s*/, "").trim();
    if (!label) continue;
    const node = { label, children: [] };
    while (stack.length && stack[stack.length - 1].lv >= lv) stack.pop();
    stack[stack.length - 1].n.children.push(node);
    stack.push({ lv, n: node });
  }
  if (!root.children.length) return null;
  const renderChildren = (n) => n.children.map((c) =>
    `<li>${inlineMd(c.label)}${c.children.length ? "<ul>" + renderChildren(c) + "</ul>" : ""}</li>`).join("");
  return root.label
    ? `<ul><li>${inlineMd(root.label)}<ul>${renderChildren(root)}</ul></li></ul>`
    : "<ul>" + renderChildren(root) + "</ul>";
}

/* 轻量 Markdown 渲染（先转义再解析，安全；支持嵌套列表树形展示） */
function mdRender(md) {
  const lines = esc(md).split("\n");
  let html = "", inCode = false, inTable = false, codeBuf = "";
  const lists = [];   // 打开的列表类型栈：'ul' | 'ol'
  const closeAll = () => {
    while (lists.length) html += lists.pop() === "ol" ? "</ol>" : "</ul>";
    if (inTable) { html += "</table>"; inTable = false; }
  };
  for (const raw of lines) {
    const s = raw.trim();
    if (s.startsWith("```")) {
      if (inCode) {
        html += "</code></pre>";   // 必须先闭合 pre，否则后续内容全部掉进代码块渲染规则（不折行、横向溢出）
        const tree = asciiTreeHtml(codeBuf);
        if (tree) html += tree;
        else {
          const listHtml = listBlockHtml(codeBuf);
          if (listHtml) html += listHtml;
        }
        codeBuf = "";
      } else {
        html += "<pre><code>";
      }
      inCode = !inCode;
      continue;
    }
    if (inCode) { codeBuf += raw + "\n"; continue; }
    if (!s) { closeAll(); html += "<div style='height:6px'></div>"; continue; }
    const h = s.match(/^(#{1,4})\s+(.*)/);
    if (h) {
      closeAll();
      html += `<h${h[1].length}>${inlineMd(h[2])}</h${h[1].length}>`;
      continue;
    }
    const li = raw.match(/^(\s*)([-*+]|\d+[.、)])\s+(.*)/);
    if (li) {
      const level = Math.min(4, Math.floor(li[1].replace(/\t/g, "  ").length / 2));
      const want = /^\d/.test(li[2]) ? "ol" : "ul";
      while (lists.length > level + 1) html += lists.pop() === "ol" ? "</ol>" : "</ul>";
      if (lists[lists.length - 1] !== want) {
        if (lists.length) html += lists.pop() === "ol" ? "</ol>" : "</ul>";
        html += want === "ol" ? "<ol>" : "<ul>";
        lists.push(want);
      }
      while (lists.length < level + 1) { html += want === "ol" ? "<ol>" : "<ul>"; lists.push(want); }
      html += `<li>${inlineMd(li[3])}</li>`;
      continue;
    }
    if (s.startsWith("|")) {
      const cells = s.replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      if (cells.every((c) => /^:?-{2,}:?$/.test(c))) continue;
      closeAll();
      if (!inTable) { html += "<table>"; inTable = true; }
      html += `<tr>${cells.map((c) => `<td>${inlineMd(c)}</td>`).join("")}</tr>`;
      continue;
    }
    if (/^(---|\*\*\*|___)$/.test(s)) { closeAll(); html += "<hr>"; continue; }
    if (s.startsWith(">")) {
      closeAll();
      html += `<blockquote>${inlineMd(s.replace(/^>\s?/, ""))}</blockquote>`;
      continue;
    }
    closeAll();
    html += `<p style="margin:4px 0">${inlineMd(s)}</p>`;
  }
  closeAll();
  if (inCode) html += "</code></pre>";
  return html;
}

/* ---------------- PDF 查看器（懒加载渲染 + 双栏同步） ---------------- */
class Viewer {
  constructor(el) {
    this.el = el;
    this.doc = null;
    this.io = null;
    this.items = [];
  }
  async load(url) {
    this.destroy();
    this.doc = await pdfjsLib.getDocument({ url }).promise;
    const first = await this.doc.getPage(1);
    const pw = first.getViewport({ scale: 1 }).width;
    const scale = Math.max(0.35, (this.el.clientWidth - 26) / pw);
    this.el.innerHTML = "";
    this.items = [];
    for (let i = 1; i <= this.doc.numPages; i++) {
      const ph = document.createElement("div");
      ph.className = "page-ph";
      ph.dataset.page = i;
      ph.style.height = Math.round(first.getViewport({ scale: 1 }).height * scale) + "px";
      ph.innerHTML = `<span class="page-label">P.${i}</span>`;
      this.el.appendChild(ph);
      this.items.push(ph);
    }
    this.io = new IntersectionObserver((es) => {
      es.forEach((e) => { if (e.isIntersecting) this.render(e.target); });
    }, { root: this.el, rootMargin: "500px" });
    this.items.forEach((p) => this.io.observe(p));
  }
  async render(ph) {
    if (ph.dataset.done) return;
    ph.dataset.done = "1";
    const n = +ph.dataset.page;
    const page = await this.doc.getPage(n);
    const scale = Math.max(0.35, (this.el.clientWidth - 26) / page.getViewport({ scale: 1 }).width);
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const vp = page.getViewport({ scale });
    const canvas = document.createElement("canvas");
    canvas.width = Math.floor(vp.width * dpr);
    canvas.height = Math.floor(vp.height * dpr);
    canvas.style.height = Math.round(vp.height) + "px";
    ph.style.height = Math.round(vp.height) + "px";
    const ctx = canvas.getContext("2d");
    await page.render({ canvasContext: ctx, viewport: page.getViewport({ scale: scale * dpr }) }).promise;
    ph.appendChild(canvas);
  }
  destroy() {
    if (this.io) this.io.disconnect();
    if (this.doc) try { this.doc.destroy(); } catch (_) {}
    this.el.innerHTML = "";
    this.doc = null;
  }
}

const viewerL = new Viewer($("#viewer-left"));
const viewerR = new Viewer($("#viewer-right"));
const viewerS = new Viewer($("#viewer-summary"));

let syncing = false;
function bindSync(a, b) {
  a.addEventListener("scroll", () => {
    if (syncing || !b.scrollHeight) return;
    syncing = true;
    const ratio = a.scrollTop / Math.max(1, a.scrollHeight - a.clientHeight);
    b.scrollTop = ratio * (b.scrollHeight - b.clientHeight);
    updatePageInd(ratio);
    requestAnimationFrame(() => { syncing = false; });
  });
}
function updatePageInd(ratio) {
  const n = state.doc?.page_count || 1;
  const page = Math.min(n, Math.max(1, Math.round(ratio * (n - 1)) + 1));
  $("#page-ind-left").textContent = `第 ${page} / ${n} 页`;
  $("#page-ind-right").textContent = `第 ${page} / ${n} 页`;
}
bindSync($("#viewer-left"), $("#viewer-right"));
bindSync($("#viewer-right"), $("#viewer-left"));

/* ---------------- 顶部导航 ---------------- */
$$("#tabs .tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    $$("#tabs .tab").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    $$(".tab-page").forEach((p) => p.classList.remove("active"));
    $("#tab-" + btn.dataset.tab).classList.add("active");
    if (btn.dataset.tab === "chat") refreshChatContext();
    if (btn.dataset.tab === "summary") loadSummary();
  });
});

$("#api-chip").addEventListener("click", () => {
  $$('#tabs .tab')[3].click();
});

/* ---------------- 课程 ---------------- */
async function loadCourses() {
  state.courses = await api("/courses");
  renderCourses();
  if (!state.courseId && state.courses.length) selectCourse(state.courses[0].id);
  if (!state.courses.length) $("#doc-empty").classList.remove("hidden");
}

function renderCourses() {
  const ul = $("#course-list");
  ul.innerHTML = "";
  state.courses.forEach((c) => {
    const li = document.createElement("li");
    li.className = c.id === state.courseId ? "active" : "";
    li.innerHTML = `
      <div class="c-name">${esc(c.name)}</div>
      <div class="c-meta"><span>${c.code ? esc(c.code) + " · " : ""}${c.doc_count} 份课件</span></div>
      <button class="c-edit" title="重命名课程">✏</button>
      <button class="c-del" title="删除课程">×</button>`;
    li.addEventListener("click", (e) => {
      if (e.target.classList.contains("c-del") || e.target.classList.contains("c-edit")) return;
      selectCourse(c.id);
    });
    li.querySelector(".c-edit").addEventListener("click", () => openCourseModal(c));
    li.querySelector(".c-del").addEventListener("click", async () => {
      if (!confirm(`确定删除课程「${c.name}」及其全部课件与总结？`)) return;
      await api(`/courses/${c.id}`, { method: "DELETE" });
      toast("课程已删除", "ok");
      state.courseId = null;
      state.doc = null;
      await loadCourses();
    });
    ul.appendChild(li);
  });
}

async function selectCourse(id) {
  state.courseId = id;
  state.doc = null;
  renderCourses();
  await loadDocs();
  $("#doc-work").classList.remove("hidden");
  $("#doc-empty").classList.add("hidden");
  $("#doc-title").textContent = "—";
  $("#doc-meta").textContent = "";
  viewerL.destroy();
  viewerR.destroy();
  $("#right-placeholder").classList.add("hidden");
  // 自动打开第一份课件，避免刷新后双栏空白
  if (state.docs.length) await openDoc(state.docs[0].id);
  if (["chat", "summary"].includes(currentTab())) {
    refreshChatContext();
    if (currentTab() === "summary") loadSummary();
  }
}

function currentTab() {
  return $("#tabs .tab.active").dataset.tab;
}

/* 新建 / 编辑课程弹窗 */
function openCourseModal(course = null) {
  state.editingId = course ? course.id : null;
  $("#modal-title").textContent = course ? "编辑课程" : "新建课程";
  $("#modal-en").textContent = course ? "Edit Course" : "New Course";
  $("#mc-ok").textContent = course ? "保存" : "创建";
  $("#mc-name").value = course ? course.name : "";
  $("#mc-code").value = course ? (course.code || "") : "";
  $("#mc-teacher").value = course ? (course.teacher || "") : "";
  $("#modal-mask").classList.remove("hidden");
  $("#mc-name").focus();
}

$("#btn-add-course").addEventListener("click", () => openCourseModal());
$("#mc-cancel").addEventListener("click", () => $("#modal-mask").classList.add("hidden"));
$("#modal-mask").addEventListener("click", (e) => {
  if (e.target.id === "modal-mask") $("#modal-mask").classList.add("hidden");
});
$("#mc-ok").addEventListener("click", async () => {
  const name = $("#mc-name").value.trim();
  if (!name) return toast("请输入课程名称", "err");
  const body = JSON.stringify({ name, code: $("#mc-code").value, teacher: $("#mc-teacher").value });
  if (state.editingId) {
    await api(`/courses/${state.editingId}`, { method: "PUT", body });
    $("#modal-mask").classList.add("hidden");
    toast("课程已更新", "ok");
    await loadCourses();
    if (state.courseId === state.editingId) selectCourse(state.editingId);
  } else {
    const r = await api("/courses", { method: "POST", body });
    $("#modal-mask").classList.add("hidden");
    toast("课程已创建", "ok");
    await loadCourses();
    selectCourse(r.id);
  }
  state.editingId = null;
  $("#mc-name").value = ""; $("#mc-code").value = ""; $("#mc-teacher").value = "";
});

/* ---------------- 课件列表与打开 ---------------- */
const STATUS_TEXT = {
  uploaded: "待翻译", extracting: "解析中", translating: "翻译中",
  done: "已完成", failed: "失败",
};

async function loadDocs() {
  if (!state.courseId) return;
  state.docs = await api(`/courses/${state.courseId}/documents`);
  renderDocStrip();
  if (state.doc) {
    const cur = state.docs.find((d) => d.id === state.doc.id);
    if (cur) { state.doc = { ...state.doc, ...cur }; refreshDocHead(); }
  }
  stopPollIfIdle();
}

function renderDocStrip() {
  const strip = $("#doc-strip");
  strip.innerHTML = "";
  state.docs.forEach((d) => {
    const chip = document.createElement("div");
    chip.className = "doc-chip" + (state.doc?.id === d.id ? " active" : "");
    chip.innerHTML = `
      <span class="dot ${d.status}"></span>
      <span class="nm">${esc(d.filename)}</span>
      <span class="st">${STATUS_TEXT[d.status] || d.status}</span>`;
    chip.addEventListener("click", () => openDoc(d.id));
    strip.appendChild(chip);
  });
}

async function openDoc(id) {
  const d = state.docs.find((x) => x.id === id);
  if (!d) return;
  state.doc = { ...d };
  renderDocStrip();
  refreshDocHead();
  $("#right-placeholder").classList.add("hidden");
  $("#progress-wrap").classList.add("hidden");
  await Promise.all([
    viewerL.load(`/api/documents/${id}/files/original`),
    loadRightViewer(),
  ]);
  if (["translating", "extracting"].includes(d.status)) startPolling();
  loadTutor().catch(() => {});
}

function refreshDocHead() {
  const d = state.doc;
  if (!d) return;
  $("#doc-title").textContent = d.filename;
  const parts = [STATUS_TEXT[d.status] || d.status];
  if (d.page_count) parts.push(`${d.page_count} 页`);
  if (d.char_count) parts.push(`${d.char_count.toLocaleString()} 字符`);
  if (d.error) parts.push("错误：" + d.error);
  $("#doc-meta").textContent = parts.join(" · ");
  $("#btn-translate").disabled = ["extracting", "translating"].includes(d.status);
  $("#btn-translate").textContent =
    d.status === "done" ? "⟳ 重新翻译" :
    ["extracting", "translating"].includes(d.status) ? "翻译中…" : "开始翻译";
}

async function loadRightViewer() {
  const d = state.doc;
  if (d && d.status === "done") {
    $("#right-placeholder").classList.add("hidden");
    try {
      await viewerR.load(`/api/documents/${d.id}/files/translated`);
      updatePageInd(0);
    } catch (_) {
      showRightPlaceholder("译制版 PDF 加载失败，请重试翻译");
    }
  } else {
    viewerR.destroy();
    showRightPlaceholder(d?.status === "failed"
      ? (d.error || "翻译失败") + "（可配置好 API 后重新点击「开始翻译」）"
      : "翻译完成后，这里将显示保留原排版的中文对照 PDF");
  }
}

function showRightPlaceholder(text) {
  $("#right-placeholder").classList.remove("hidden");
  $("#right-placeholder-text").textContent = text;
}

/* ---------------- 上传 / 翻译 / 轮询 ---------------- */
$("#file-input").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file || !state.courseId) return;
  const fd = new FormData();
  fd.append("file", file);
  toast("正在上传 " + file.name + " …");
  try {
    const r = await api(`/courses/${state.courseId}/documents`, { method: "POST", body: fd });
    await loadDocs();
    await openDoc(r.id);
    toast(r.auto_started ? "上传成功，已自动开始翻译" : "上传成功（配置 API Key 后可开始翻译）", "ok");
    if (!r.auto_started && !state.settings?.ready) switchToSettings();
  } catch (err) {
    toast("上传失败：" + err.message, "err");
  }
});

function switchToSettings() {
  $$("#tabs .tab")[3].click();
}

$("#btn-translate").addEventListener("click", async () => {
  if (!state.doc) return;
  try {
    await api(`/documents/${state.doc.id}/translate`, { method: "POST" });
    state.doc.status = "extracting";
    refreshDocHead();
    renderDocStrip();
    startPolling();
    toast("已开始翻译，请稍候…", "ok");
  } catch (err) {
    toast(err.message, "err");
    if (String(err.message).includes("设置")) switchToSettings();
  }
});

$("#btn-del-doc").addEventListener("click", async () => {
  if (!state.doc || !confirm(`确定删除课件「${state.doc.filename}」？`)) return;
  await api(`/documents/${state.doc.id}`, { method: "DELETE" });
  state.doc = null;
  viewerL.destroy();
  viewerR.destroy();
  stopTutorPoll();
  $("#tutor-panel").classList.add("hidden");
  $("#doc-title").textContent = "—";
  $("#doc-meta").textContent = "";
  $("#right-placeholder").classList.add("hidden");
  await loadDocs();
  toast("课件已删除", "ok");
});

$("#btn-load-sample").addEventListener("click", async () => {
  if (!state.courseId) return toast("请先创建或选择一个课程", "err");
  try {
    const list = await api(`/sample/${state.courseId}`, { method: "POST" });
    toast(`已载入 ${list.length} 份示例课件`, "ok");
    await loadDocs();
    if (list.length) openDoc(list[0].id);
  } catch (err) {
    toast(err.message, "err");
  }
});

function startPolling() {
  clearInterval(state.pollTimer);
  const id = state.doc.id;
  $("#progress-wrap").classList.remove("hidden");
  state.pollTimer = setInterval(async () => {
    try {
      const d = await api(`/documents/${id}`);
      if (!state.doc || state.doc.id !== id) return clearInterval(state.pollTimer);
      state.doc = { ...state.doc, ...d };
      $("#progress-bar").style.width = d.progress + "%";
      $("#progress-pct").textContent = d.progress + "%";
      $("#progress-text").textContent =
        d.status === "extracting" ? "正在解析课件结构与文本…" :
        d.status === "translating" ? "AI 正在逐页翻译并回写排版…" :
        d.status === "done" ? "翻译完成 ✓" : (d.error || "翻译失败");
      if (d.status === "translating" || d.status === "extracting") {
        loadDocs().catch(() => {});
        return;
      }
      clearInterval(state.pollTimer);
      await loadDocs();
      refreshDocHead();
      if (d.status === "done") {
        $("#progress-wrap").classList.add("hidden");
        await loadRightViewer();
        toast("翻译完成，右栏已生成对照 PDF", "ok");
        loadTutor().catch(() => {});   // 翻译完成 → 展示自动开始的辅导分析
      } else {
        $("#progress-bar").style.width = "0%";
        refreshDocHead();
      }
    } catch (_) {}
  }, 1600);
}

function stopPollIfIdle() {
  if (state.doc && ["done", "failed", "uploaded"].includes(state.doc.status)) {
    clearInterval(state.pollTimer);
    $("#progress-wrap").classList.add("hidden");
  }
}

/* ---------------- AI 辅导分析（imis-course-tutor skill） ---------------- */
let tutorTimer = null;

function stopTutorPoll() {
  if (tutorTimer) { clearInterval(tutorTimer); tutorTimer = null; }
}

async function loadTutor() {
  stopTutorPoll();
  const id = state.doc?.id;
  if (!id) return;
  const a = await api(`/documents/${id}/analysis`);
  if (state.doc?.id !== id) return;          // 期间用户切换了课件
  $("#tutor-panel").classList.remove("hidden");
  const badge = $("#tutor-badge"), retry = $("#btn-tutor-retry");
  badge.classList.add("hidden");
  retry.classList.add("hidden");
  const status = $("#tutor-status"), md = $("#tutor-md");
  if (a.status === "done") {
    status.textContent = a.analyzed_at ? `分析生成于 ${a.analyzed_at} · 基于 imis-course-tutor 技能` : "";
    md.innerHTML = mdRender(a.markdown || "");
    retry.classList.remove("hidden");
    $("#tutor-panel").classList.add("collapsed");   // 分析完成默认收起，把空间留给课件双栏
  } else if (a.status === "running") {
    md.innerHTML = "";
    status.textContent =
      "📘 AI 辅导老师正在分析这份课件（课程定位 → 结构总览 → 核心概念详解 → 考点提醒 → 现实应用 → 自测题），约需 1~3 分钟…";
    tutorTimer = setInterval(() => loadTutor().catch(() => {}), 6000);
  } else if (a.status === "failed") {
    md.innerHTML = "";
    status.textContent = "分析生成失败（模型调用异常），可点击「重新生成」再试。";
    retry.classList.remove("hidden");
  } else {
    md.innerHTML = "";
    if (state.doc?.status === "done") {
      status.textContent = "这份课件还没有辅导分析，点击「重新生成」立即生成。";
      retry.classList.remove("hidden");
    } else {
      status.textContent = "翻译完成后，AI 辅导老师将自动分析这份课件：课程定位 / 结构总览 / 核心概念 / 考点 / 现实应用 / 自测题。";
    }
  }
}

$("#btn-tutor-retry").addEventListener("click", async () => {
  if (!state.doc) return;
  try {
    await api(`/documents/${state.doc.id}/analyze`, { method: "POST" });
    loadTutor().catch(() => {});
    toast("已开始生成辅导分析…", "ok");
  } catch (err) {
    toast(err.message, "err");
  }
});

// 点击面板头部展开 / 收起辅导分析
$("#tutor-head").addEventListener("click", (e) => {
  if (e.target.closest("button")) return;
  $("#tutor-panel").classList.toggle("collapsed");
});

/* ---------------- AI 助教 ---------------- */
function refreshChatContext() {
  const sel = $("#chat-context");
  sel.innerHTML = "";
  if (!state.courseId) {
    sel.innerHTML = `<option value="">（请先在左侧选择/创建课程）</option>`;
    return;
  }
  const opt0 = document.createElement("option");
  opt0.value = "0";
  opt0.textContent = "整门课程（最近 3 份课件）";
  sel.appendChild(opt0);
  state.docs.filter((d) => d.status === "done").forEach((d) => {
    const o = document.createElement("option");
    o.value = d.id;
    o.textContent = "📄 " + d.filename;
    sel.appendChild(o);
  });
}

function addMsg(role, text = "") {
  const wrap = document.createElement("div");
  wrap.className = "msg " + (role === "user" ? "user" : "ai");
  wrap.innerHTML = `
    <div class="avatar">${role === "user" ? "我" : "AI"}</div>
    <div class="bubble">${mdRender(text)}</div>`;
  $("#chat-messages").appendChild(wrap);
  $("#chat-messages").scrollTop = $("#chat-messages").scrollHeight;
  return wrap.querySelector(".bubble");
}

async function loadChatHistory() {
  const box = $("#chat-messages");
  box.innerHTML = `
    <div class="chat-welcome">
      <div class="empty-icon">🎓</div>
      <h3>AI 课程助教</h3>
      <p>基于你上传的课件内容答疑解惑，支持 DeepSeek / GLM / OpenAI / Kimi 等模型（自带 API Key）</p>
    </div>`;
  if (!state.courseId) return;
  try {
    const hist = await api(`/chat/history?course_id=${state.courseId}`);
    hist.forEach((m) => addMsg(m.role === "user" ? "user" : "ai", m.content));
  } catch (_) {}
}

$("#btn-clear-chat").addEventListener("click", async () => {
  if (!state.courseId) return;
  if (!confirm("确定清空本课程的对话记录？")) return;
  await api(`/chat/history?course_id=${state.courseId}`, { method: "DELETE" });
  loadChatHistory();
  toast("对话记录已清空", "ok");
});

async function sendChat() {
  if (state.sending) return;
  const ta = $("#chat-text");
  const text = ta.value.trim();
  if (!text) return;
  if (!state.courseId) return toast("请先选择课程", "err");
  if (!state.settings?.ready) { switchToSettings(); return toast("请先在设置中配置 API Key", "err"); }
  ta.value = "";
  ta.style.height = "auto";
  addMsg("user", text);
  const bubble = addMsg("ai");
  bubble.innerHTML = '<span class="cursor"></span>';
  state.sending = true;
  $("#btn-send").disabled = true;

  // 收集最近对话（含本条），供服务端拼接上下文
  const msgs = [];
  $$("#chat-messages .msg").forEach((m) => {
    const isUser = m.classList.contains("user");
    const content = m.querySelector(".bubble").innerText.trim();
    if (content && !(isUser && content === text && msgs.length)) {
      msgs.push({ role: isUser ? "user" : "assistant", content });
    }
  });
  if (!msgs.some((m) => m.role === "user" && m.content === text)) msgs.push({ role: "user", content: text });

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        course_id: state.courseId,
        document_id: +($("#chat-context").value || 0),
        messages: msgs.slice(-16),
      }),
    });
    if (!res.ok) {
      let msg = res.statusText;
      try { msg = (await res.json()).detail || msg; } catch (_) {}
      throw new Error(msg);
    }
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let full = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      full += dec.decode(value, { stream: true });
      bubble.innerHTML = mdRender(full) + '<span class="cursor"></span>';
      $("#chat-messages").scrollTop = $("#chat-messages").scrollHeight;
    }
    bubble.innerHTML = mdRender(full || "（模型未返回内容）");
  } catch (err) {
    bubble.innerHTML = mdRender("⚠️ " + err.message);
    if (String(err.message).includes("设置")) switchToSettings();
  }
  state.sending = false;
  $("#btn-send").disabled = false;
}

$("#btn-send").addEventListener("click", sendChat);
$("#chat-text").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); }
});
$("#chat-text").addEventListener("input", function () {
  this.style.height = "auto";
  this.style.height = Math.min(120, this.scrollHeight) + "px";
});

/* ---------------- 课程总结 ---------------- */
async function loadSummary() {
  if (!state.courseId) return;
  const s = await api(`/courses/${state.courseId}/summary`).catch(() => null);
  if (!s) return;
  $("#summary-meta").textContent = s.updated_at
    ? `上次更新：${s.updated_at} · 已纳入 ${s.included.length} / ${s.doc_count} 份课件`
    : "把整门课程的课件沉淀为一份持续更新的复习文档";
  const badge = $("#summary-pending");
  if (s.pending_count > 0) {
    badge.classList.remove("hidden");
    badge.textContent = `⚡ 有 ${s.pending_count} 份新课件未纳入总结，点击「更新总结」`;
  } else {
    badge.classList.add("hidden");
  }
  if (s.markdown) {
    $("#summary-md").innerHTML = mdRender(s.markdown);
  }
  $("#btn-summary-download").classList.toggle("hidden", !s.pdf_ready);
  if (s.pdf_ready) {
    $("#btn-summary-download").href = s.pdf_url;
    $("#summary-pdf-empty").classList.add("hidden");
    viewerS.load(s.pdf_url).catch(() => {});
  } else {
    $("#summary-pdf-empty").classList.remove("hidden");
  }
  const hist = await api(`/courses/${state.courseId}/summary/history`).catch(() => []);
  $("#summary-history").innerHTML = hist.map((h) =>
    `<div class="hist-chip"><b>${esc(h.created_at)}</b> · ${esc(h.note)}</div>`).join("");
}

$("#btn-summary-update").addEventListener("click", async () => {
  if (!state.courseId) return toast("请先选择课程", "err");
  const btn = $("#btn-summary-update");
  btn.disabled = true;
  btn.textContent = "✦ 正在生成（可能需要 1-2 分钟）…";
  try {
    await api(`/courses/${state.courseId}/summary/update`, { method: "POST" });
    toast("课程总结已更新 ✓", "ok");
    await loadSummary();
  } catch (err) {
    toast(err.message, "err");
    if (String(err.message).includes("设置")) switchToSettings();
  }
  btn.disabled = false;
  btn.textContent = "✦ 更新总结";
});

/* ---------------- 设置 ---------------- */
function renderSettings() {
  const s = state.settings;
  $("#api-chip").className = "chip " + (s.ready ? "ok" : "warn");
  $("#api-chip-text").textContent = s.ready ? `已连接 · ${s.model}` : "未配置 API Key";
  $("#key-hint").textContent = s.has_key ? `已保存：${s.key_hint}（重填可覆盖）` : "尚未保存 Key";
  $("#preset-list").innerHTML = "";
  const helpEl = $("#preset-help");
  if (helpEl) helpEl.textContent = "";
  Object.entries(s.presets || {}).forEach(([id, p]) => {
    const chip = document.createElement("button");
    chip.className = "preset-chip" + (p.free ? " free" : "");
    chip.textContent = p.label;
    chip.addEventListener("click", () => {
      $$(".preset-chip").forEach((c) => c.classList.remove("active"));
      chip.classList.add("active");
      $("#set-base").value = p.api_base;
      $("#set-model").value = p.model;
      // 该服务商之前填过 Key 则自动带出，免重复输入
      const saved = state.settings?.saved_keys?.[p.api_base];
      $("#set-key").value = saved || (id === "mock" ? "demo" : "");
      $("#key-hint").textContent = saved
        ? "已自动填入该服务商保存的 Key"
        : "尚未保存该服务商的 Key";
      if (helpEl) helpEl.textContent = p.help || "";
    });
    $("#preset-list").appendChild(chip);
  });
}

async function loadSettings() {
  state.settings = await api("/settings");
  $("#set-base").value = state.settings.api_base || "";
  $("#set-model").value = state.settings.model || "";
  renderSettings();
}

// 手动修改接口地址时，自动带出该服务商保存过的 Key
$("#set-base").addEventListener("input", () => {
  const saved = state.settings?.saved_keys?.[$("#set-base").value.trim()];
  if (saved) {
    $("#set-key").value = saved;
    $("#key-hint").textContent = "已自动填入该服务商保存的 Key";
  }
});

$("#btn-eye").addEventListener("click", () => {
  const k = $("#set-key");
  k.type = k.type === "password" ? "text" : "password";
  $("#btn-eye").textContent = k.type === "password" ? "显示" : "隐藏";
});

$("#btn-test").addEventListener("click", async () => {
  const out = $("#test-result");
  out.className = "hint";
  out.textContent = "测试中…";
  try {
    const r = await api("/settings/test", {
      method: "POST",
      body: JSON.stringify({
        api_base: $("#set-base").value, api_key: $("#set-key").value, model: $("#set-model").value,
      }),
    });
    out.className = "hint ok";
    out.textContent = `✓ 连接成功（${r.latency}s）：${r.reply}`;
  } catch (err) {
    out.className = "hint err";
    out.textContent = "✗ " + err.message;
  }
});

$("#btn-save-settings").addEventListener("click", async () => {
  const body = {};
  if ($("#set-base").value.trim()) body.api_base = $("#set-base").value.trim();
  if ($("#set-key").value.trim()) body.api_key = $("#set-key").value.trim();
  if ($("#set-model").value.trim()) body.model = $("#set-model").value.trim();
  if (!Object.keys(body).length) return toast("请至少填写一项配置", "err");
  try {
    await api("/settings", { method: "POST", body: JSON.stringify(body) });
    toast("配置已保存 ✓", "ok");
    $("#set-key").value = "";
    await loadSettings();
    renderSettings();
  } catch (err) {
    toast(err.message, "err");
  }
});

/* ---------------- 启动 ---------------- */
(async function init() {
  try {
    await loadSettings();
    await loadCourses();
    await loadChatHistory();
    if (!state.settings.ready) {
      toast("提示：先到「设置」配置你的 API Key（可用离线演示模式）");
    }
  } catch (e) {
    toast("初始化失败：" + e.message, "err");
  }
})();
