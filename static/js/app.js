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
        const tree = asciiTreeHtml(codeBuf);
        if (tree) html += tree;
        else if (listBlockHtml(codeBuf)) html += listBlockHtml(codeBuf);
        else html += "</code></pre>";
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
    this.generation = 0;
    this.loadingTask = null;
  }
  async load(url) {
    this.destroy();
    const generation=this.generation;
    const task=pdfjsLib.getDocument({url});this.loadingTask=task;
    try {
    const doc=await task.promise;
    if(generation!==this.generation){doc.destroy().catch(()=>{});return}
    this.doc=doc;
    const first = await doc.getPage(1);
    if(generation!==this.generation)return;
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
      es.forEach((e) => { if (e.isIntersecting) this.render(e.target).catch(error=>console.warn('PDF page could not render',error)); });
    }, { root: this.el, rootMargin: "500px" });
    this.items.forEach((p) => this.io.observe(p));
    } catch(error) {
      if(generation!==this.generation)return;
      throw error;
    }
  }
  async render(ph) {
    if (ph.dataset.done) return;
    const generation=this.generation,doc=this.doc;
    if(!doc)return;
    ph.dataset.done = "1";
    try {
    const n = +ph.dataset.page;
    const page = await doc.getPage(n);
    if(generation!==this.generation||!ph.isConnected)return;
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
    if(generation!==this.generation||!ph.isConnected)return;
    ph.appendChild(canvas);
    } catch(error) {
      if(generation!==this.generation||error.name==='RenderingCancelledException')return;
      delete ph.dataset.done;throw error;
    }
  }
  destroy() {
    this.generation++;
    if (this.io) this.io.disconnect();
    if (this.loadingTask) try { this.loadingTask.destroy().catch(()=>{}); } catch (_) {}
    else if (this.doc) try { this.doc.destroy().catch(()=>{}); } catch (_) {}
    this.el.innerHTML = "";
    this.doc = null;
    this.loadingTask=null;this.items=[];
  }
}

const viewerL = new Viewer($("#viewer-left"));
const viewerR = new Viewer($("#viewer-right"));


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
  const n = state.doc?.page_count || viewerL.doc?.numPages || 1;
  const top=viewerL.el.getBoundingClientRect().top+40;
  const actual=viewerL.items.find(item=>item.isConnected && item.getBoundingClientRect().bottom>top);
  const page=actual ? +actual.dataset.page : Math.min(n,Math.max(1,Math.round(ratio*(n-1))+1));
  $("#page-ind-left").textContent = `第 ${page} / ${n} 页`;
  $("#page-ind-right").textContent = `第 ${page} / ${n} 页`;
  window.StudyAI?.readerPageChanged(page);
}
window.courseMateGoToPage = number => {
  syncing=true;
  for(const viewer of [viewerL,viewerR]){
    const item=viewer.items[number-1];
    if(item?.isConnected)viewer.el.scrollTop+=item.getBoundingClientRect().top-viewer.el.getBoundingClientRect().top-8;
  }
  updatePageInd(0);requestAnimationFrame(()=>syncing=false);
};

bindSync($("#viewer-left"), $("#viewer-right"));
bindSync($("#viewer-right"), $("#viewer-left"));

/* ---------------- 顶部导航 ---------------- */
$$("#tabs .tab[data-tab]").forEach((btn) => {
  btn.addEventListener("click", () => {
    $$("#tabs .tab").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    $$(".tab-page").forEach((p) => p.classList.remove("active"));
    $("#tab-" + btn.dataset.tab).classList.add("active");

  });
});

$("#api-chip").addEventListener("click", () => {
  document.querySelector('[data-tab="settings"]').click();
});

/* ---------------- 课程 ---------------- */
async function loadCourses() {
  state.courses = await api("/courses");
  renderCourses();
  if (!state.courseId && state.courses.length) await selectCourse(state.courses[0].id);
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
  window.StudyAI?.contextChanged();
  renderCourses();
  await loadDocs();
  if(state.courseId!==id)return;
  $("#doc-work").classList.remove("hidden");
  $("#doc-empty").classList.add("hidden");
  $("#doc-title").textContent = "—";
  $("#doc-meta").textContent = "";
  viewerL.destroy();
  viewerR.destroy();
  $("#right-placeholder").classList.add("hidden");
  // 自动打开第一份课件，避免刷新后双栏空白
  if (state.docs.length) await openDoc(state.docs[0].id);
  window.StudyAI?.contextChanged();
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
  const course=state.courseId,documents=await api(`/courses/${course}/documents`);
  if(course!==state.courseId)return;
  state.docs = documents;
  const entry=state.courses.find(item=>item.id===course);
  if(entry){entry.doc_count=documents.length;entry.done_count=documents.filter(doc=>doc.status==='done').length;renderCourses()}
  renderDocStrip();
  if (state.doc) {
    const cur = state.docs.find((d) => d.id === state.doc.id);
    if (cur) { state.doc = { ...state.doc, ...cur }; refreshDocHead(); }
  }
  window.StudyAI?.contextChanged();
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
  window.StudyAI?.contextChanged();
  renderDocStrip();
  refreshDocHead();
  $("#right-placeholder").classList.add("hidden");
  $("#progress-wrap").classList.add("hidden");
  await Promise.all([
    viewerL.load(`/api/documents/${id}/files/original`),
    loadRightViewer(),
  ]);
  if(state.doc?.id!==id)return;
  if (["translating", "extracting"].includes(d.status)) startPolling();
  window.StudyAI?.refresh();
}

function refreshDocHead() {
  const d = state.doc;
  if (!d) return;
  $("#doc-title").textContent = d.filename;
  const waiting = d.status === "translating" && d.status_message;
  const parts = [waiting ? "等待自动继续" : (STATUS_TEXT[d.status] || d.status)];
  if (d.page_count) parts.push(`${d.page_count} 页`);
  if (d.char_count) parts.push(`${d.char_count.toLocaleString()} 字符`);
  if (d.error) parts.push("错误：" + d.error);
  if (waiting) parts.push(translationProgressText(d));
  $("#doc-meta").textContent = parts.join(" · ");
  $("#btn-translate").disabled = ["extracting", "translating"].includes(d.status);
  $("#btn-translate").textContent =
    d.status === "done" ? "⟳ 重新翻译" :
    waiting ? "等待自动继续…" :
    ["extracting", "translating"].includes(d.status) ? "翻译中…" : "开始翻译";
}

function translationProgressText(d) {
  if (d.status_message) {
    const seconds = Math.max(0, Math.ceil((d.retry_at || 0) - Date.now() / 1000));
    return d.status_message + (seconds ? `（约 ${seconds} 秒后重试）` : "");
  }
  return d.status === "extracting" ? "正在解析课件结构与文本…" :
    d.status === "translating" ? (d.progress >= 90 ? "正在生成中文 PDF 并检查排版…" : "AI 正在翻译课件文本…") :
    d.status === "done" ? "翻译完成 ✓" : (d.error || "翻译失败");
}

async function loadRightViewer() {
  const d = state.doc;
  if (d && d.status === "done") {
    $("#right-placeholder").classList.add("hidden");
    try {
      await viewerR.load(`/api/documents/${d.id}/files/translated?v=${encodeURIComponent(d.translated_at || "")}`);
      updatePageInd(0);
    } catch (_) {
      showRightPlaceholder("译制版 PDF 加载失败，请重试翻译");
    }
  } else {
    viewerR.destroy();
    showRightPlaceholder(d?.status === "failed"
      ? (d.error || "翻译失败") + "（已完成译文有缓存，重试会继续使用）"
      : "翻译完成后，这里将显示保留原排版的中文对照 PDF");
  }
}

function showRightPlaceholder(text) {
  $("#right-placeholder").classList.remove("hidden");
  $("#right-placeholder-text").textContent = text;
}

/* ---------------- 上传 / 翻译 / 轮询 ---------------- */
const uploadDialog = $("#upload-dialog"), uploadZone = $("#upload-zone");
let uploadBusy = false, uploadTrigger = null, uploadCourseId = null, dragDepth = 0;

function uploadError(message = "") {
  $("#upload-error").textContent = message;
  $("#upload-error").hidden = !message;
}

function setUploadBusy(busy, name = "") {
  uploadBusy = busy;
  uploadDialog.setAttribute("aria-busy", String(busy));
  ["#upload-choose", "#upload-cancel", "#upload-close"].forEach((id) => { $(id).disabled = busy; });
  $("#upload-prompt").textContent = busy ? "正在上传课件…" : "拖拽 PDF 文件到这里";
  $("#upload-alternative").textContent = busy ? name : "或点击下方按钮选择文件";
}

$$('[data-upload-open]').forEach((button) => button.addEventListener("click", () => {
  if (!state.courseId) return toast("请先创建或选择一个课程", "err");
  uploadTrigger = button;
  uploadCourseId = state.courseId;
  const course = state.courses.find((c) => c.id === uploadCourseId);
  $("#upload-subtitle").textContent = course ? `添加到「${course.name}」` : "将 PDF 添加到当前课程";
  uploadError();
  setUploadBusy(false);
  uploadDialog.showModal();
  $("#upload-choose").focus();
}));

function closeUpload() { if (!uploadBusy) uploadDialog.close(); }
$("#upload-close").addEventListener("click", closeUpload);
$("#upload-cancel").addEventListener("click", closeUpload);
uploadDialog.addEventListener("cancel", (e) => { if (uploadBusy) e.preventDefault(); });
uploadDialog.addEventListener("click", (e) => {
  if (e.target !== uploadDialog) return;
  const rect = uploadDialog.getBoundingClientRect();
  if (e.clientX < rect.left || e.clientX > rect.right || e.clientY < rect.top || e.clientY > rect.bottom) closeUpload();
});
uploadDialog.addEventListener("close", () => {
  dragDepth = 0;
  uploadZone.classList.remove("drag-over");
  $("#file-input").value = "";
  uploadTrigger?.focus();
});
$("#upload-choose").addEventListener("click", (e) => {
  e.stopPropagation();
  if (!uploadBusy) $("#file-input").click();
});
uploadZone.addEventListener("click", (e) => {
  if (!uploadBusy && !e.target.closest("button,input")) $("#file-input").click();
});
$("#file-input").addEventListener("change", (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (file) uploadFile(file);
});
uploadZone.addEventListener("dragenter", (e) => {
  e.preventDefault();
  if (uploadBusy || !Array.from(e.dataTransfer?.types || []).includes("Files")) return;
  dragDepth++;
  uploadZone.classList.add("drag-over");
});
uploadZone.addEventListener("dragover", (e) => {
  e.preventDefault();
  if (e.dataTransfer) e.dataTransfer.dropEffect = uploadBusy ? "none" : "copy";
});
uploadZone.addEventListener("dragleave", (e) => {
  e.preventDefault();
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) uploadZone.classList.remove("drag-over");
});
uploadZone.addEventListener("drop", (e) => {
  e.preventDefault();
  e.stopPropagation();
  dragDepth = 0;
  uploadZone.classList.remove("drag-over");
  if (uploadBusy) return;
  const files = Array.from(e.dataTransfer?.files || []);
  if (files.length !== 1) return uploadError("请每次上传一个 PDF 文件。");
  uploadFile(files[0]);
});
["dragover", "drop"].forEach((type) => document.addEventListener(type, (e) => {
  if (uploadDialog.open && Array.from(e.dataTransfer?.types || []).includes("Files")) e.preventDefault();
}));

async function uploadFile(file) {
  if (uploadBusy || !uploadCourseId) return;
  uploadError();
  if (!file.name.toLowerCase().endsWith(".pdf")) return uploadError("仅支持 PDF 文件，请重新选择。");
  if (file.size > 80 * 1024 * 1024) return uploadError("文件超过 80MB，请选择较小的 PDF。");
  setUploadBusy(true, file.name);
  let uploaded = false;
  try {
    const header = new Uint8Array(await file.slice(0, 5).arrayBuffer());
    if (String.fromCharCode(...header) !== "%PDF-") throw new Error("文件不是有效的 PDF，请检查后重试。");
    const fd = new FormData();
    fd.append("file", file);
    const r = await api(`/courses/${uploadCourseId}/documents`, { method: "POST", body: fd });
    uploaded = true;
    setUploadBusy(false);
    uploadDialog.close();
    await loadDocs();
    $("#doc-empty").classList.add("hidden");
    $("#doc-work").classList.remove("hidden");
    await openDoc(r.id);
    toast(r.auto_started ? "上传成功，已自动开始翻译" : "上传成功（配置 API Key 后可开始翻译）", "ok");
    if (!r.auto_started && !state.settings?.ready) switchToSettings();
  } catch (err) {
    if (uploaded) toast("文件已上传，阅读界面加载失败，请重新打开课件。", "err");
    else uploadError("上传失败：" + err.message);
  } finally {
    setUploadBusy(false);
  }
}

function switchToSettings() {
  document.querySelector('[data-tab="settings"]').click();
}

$("#btn-translate").addEventListener("click", async () => {
  if (!state.doc) return;
  try {
    await api(`/documents/${state.doc.id}/translate`, { method: "POST" });
    state.doc.status = "extracting";
    state.doc.status_message = "";
    state.doc.retry_at = 0;
    state.doc.error = "";
    refreshDocHead();
    renderDocStrip();
    viewerR.destroy();
    showRightPlaceholder("正在翻译课件，完成后自动显示中文对照 PDF；临时限流或断连会自动等待重试。");
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
  window.StudyAI?.contextChanged();
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
      $("#progress-text").textContent = translationProgressText(d);
      refreshDocHead();
      if (d.status === "translating" || d.status === "extracting") {
        showRightPlaceholder(d.status_message ? translationProgressText(d) : "正在翻译课件，完成后自动显示中文对照 PDF。");
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
        window.StudyAI?.refresh();   // 翻译完成 → 展示自动开始的辅导分析
      } else {
        showRightPlaceholder((d.error || "翻译未完成") + "（已完成译文有缓存，重试会继续使用）");
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

/* ---------------- 设置 ---------------- */
const ZHIPU_API_BASE = "https://open.bigmodel.cn/api/paas/v4";
const ZHIPU_DEFAULT_MODEL = "glm-4.5-flash";
function isZhipuSettings(settings) {
  return (settings?.api_base || "").replace(/\/+$/, "") === ZHIPU_API_BASE;
}
function savedZhipuKey() {
  const entries = Object.entries(state.settings?.saved_keys || {});
  return entries.find(([base]) => base.replace(/\/+$/, "") === ZHIPU_API_BASE)?.[1] || "";
}
function zhipuModel() {
  const model = $("#set-model").value.trim();
  if (!/^glm-/i.test(model)) throw new Error("请填写智谱 GLM 模型名称，例如 glm-4.5-flash");
  return model;
}
function updateTranslationModeVisibility() {
  $("#set-base").value = ZHIPU_API_BASE;
  $("#translation-mode-field").hidden = false;
}

function renderSettings() {
  const s = state.settings;
  const ready = isZhipuSettings(s) && s.ready;
  $("#api-chip").className = "chip " + (ready ? "ok" : "warn");
  $("#api-chip-text").textContent = ready
    ? (s.translation_mode === "fast" && s.translation_model !== s.model
      ? `已连接 · 快速翻译 / ${s.model}` : `已连接 · ${s.model}`)
    : "未配置智谱 API Key";
  $("#key-hint").textContent = isZhipuSettings(s) && s.has_key
    ? `已保存：${s.key_hint}（重填可覆盖）`
    : (savedZhipuKey() ? "已填入之前保存的智谱 Key，测试后保存即可" : "尚未保存智谱 Key");
  $("#preset-list").innerHTML = '<span class="preset-chip active">智谱 GLM</span>';
  const helpEl = $("#preset-help");
  if (helpEl) helpEl.innerHTML = '在 <a href="https://open.bigmodel.cn/" rel="noreferrer">智谱开放平台</a> 创建 API Key，粘贴到下方后测试并保存。';
}

async function loadSettings() {
  state.settings = await api("/settings");
  $("#set-base").value = ZHIPU_API_BASE;
  $("#set-model").value = isZhipuSettings(state.settings) && /^glm-/i.test(state.settings.model || "")
    ? state.settings.model : ZHIPU_DEFAULT_MODEL;
  $("#set-key").value = isZhipuSettings(state.settings) ? "" : savedZhipuKey();
  $("#set-translation-mode").value = state.settings.translation_mode || "fast";
  updateTranslationModeVisibility();
  renderSettings();
  window.StudyAI?.settingsChanged();
}

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
    const model = zhipuModel();
    const key = $("#set-key").value.trim() || savedZhipuKey();
    if (!key) throw new Error("请先填写你的智谱 API Key");
    const r = await api("/settings/test", {
      method: "POST",
      body: JSON.stringify({
        api_base: ZHIPU_API_BASE, api_key: key, model,
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
  try {
    const body = {api_base: ZHIPU_API_BASE, model: zhipuModel(), translation_mode: $("#set-translation-mode").value};
    const enteredKey = $("#set-key").value.trim();
    if (enteredKey) body.api_key = enteredKey;
    else if (!isZhipuSettings(state.settings) && savedZhipuKey()) body.api_key = savedZhipuKey();
    else if (!(isZhipuSettings(state.settings) && state.settings.has_key)) throw new Error("请先填写你的智谱 API Key");
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

    if (!state.settings.ready) {
      toast("提示：先到「设置」配置你的智谱 API Key");
    }
  } catch (e) {
    toast("初始化失败：" + e.message, "err");
  }
})();
