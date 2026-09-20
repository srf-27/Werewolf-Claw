"use strict";

const ROLE_LABELS = {
  system: "系统",
  user: "用户",
  assistant: "助手",
  tool: "工具",
};

// 头像文件放在 src/werewolf_claw/app/static/avatars/ 目录下，
// 浏览器通过 /static/avatars/<文件>.svg 访问；换头像就替换同名文件，或者改这里的路径。
const AVATARS = {
  user: "/static/avatars/user.svg",
  assistant: "/static/avatars/assistant.svg",
  system: "/static/avatars/system.svg",
  tool: "/static/avatars/tool.svg",
};

const ICONS = {
  copy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2.5"/><path d="M6 15h-.5A2.5 2.5 0 0 1 3 12.5v-7A2.5 2.5 0 0 1 5.5 3h7A2.5 2.5 0 0 1 15 5.5V6"/></svg>',
  quote: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6H6.5A2.5 2.5 0 0 0 4 8.5v2A2.5 2.5 0 0 0 6.5 13H8v2.5A2.5 2.5 0 0 1 5.5 18"/><path d="M20 6h-2.5A2.5 2.5 0 0 0 15 8.5v2A2.5 2.5 0 0 0 17.5 13H19v2.5A2.5 2.5 0 0 1 16.5 18"/></svg>',
  edit: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h4L19.5 8.5a2.1 2.1 0 0 0-3-3L5 17v3z"/><path d="M14.5 6.5 17.5 9.5"/></svg>',
  regenerate: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M20.5 12a8.5 8.5 0 1 1-2.6-6.1"/><path d="M20.5 4.5V10h-5.5"/></svg>',
  send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5"/><path d="m5 12 7-7 7 7"/></svg>',
  sliders: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M4 8h9M17 8h3M4 16h3M11 16h9"/><circle cx="15" cy="8" r="2"/><circle cx="9" cy="16" r="2"/></svg>',
  download: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v10"/><path d="m7 11 5 5 5-5"/><path d="M5 20h14"/></svg>',
  upload: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20V10"/><path d="m7 13 5-5 5 5"/><path d="M5 4h14"/></svg>',
  plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12.5 4.5 4.5L19 7"/></svg>',
  close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16"/><path d="M9.5 7V4.8h5V7"/><path d="m6.5 7 1 13h9l1-13"/></svg>',
  grip: '<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="9" cy="6" r="1.3"/><circle cx="15" cy="6" r="1.3"/><circle cx="9" cy="12" r="1.3"/><circle cx="15" cy="12" r="1.3"/><circle cx="9" cy="18" r="1.3"/><circle cx="15" cy="18" r="1.3"/></svg>',
  pin: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 15v5"/><path d="M7.5 4h9l-1.2 5.2 2.7 2.6H6l2.7-2.6z"/></svg>',
  "pin-off": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 15v5"/><path d="M7.5 4h9l-1.2 5.2 2.7 2.6H6l2.7-2.6z"/><path d="M4 4l16 16"/></svg>',
  select: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="4" width="6.5" height="6.5" rx="1.6"/><path d="m5 7.3 1.5 1.5L9.4 5.9"/><path d="M13.5 7.2h7"/><rect x="3.5" y="13.5" width="6.5" height="6.5" rx="1.6"/><path d="M13.5 16.7h7"/></svg>',
  "check-circle": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12.5 4.5 4.5L19 7"/></svg>',
  image: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="14" rx="2.5"/><circle cx="8.5" cy="10" r="1.6"/><path d="m4 17 5-4.5 4 3.5 3-2.5 4 3.5"/></svg>',
  link: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13.5a3.5 3.5 0 0 0 5 0l3-3a3.5 3.5 0 0 0-5-5l-1 1"/><path d="M14 10.5a3.5 3.5 0 0 0-5 0l-3 3a3.5 3.5 0 0 0 5 5l1-1"/></svg>',
  share: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 15V4"/><path d="m8 7.5 4-3.5 4 3.5"/><path d="M5 14v5a1.5 1.5 0 0 0 1.5 1.5h11A1.5 1.5 0 0 0 19 19v-5"/></svg>',
  gear: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3.2"/><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1A1.6 1.6 0 0 0 9 19.4a1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.6 1.6 0 0 0 4.6 9a1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z"/></svg>',
  help: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.2 2.4c-.7.3-1.2.9-1.2 1.6v.5"/><path d="M12 17.2h.01"/></svg>',
  moon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z"/></svg>',
  sun: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6 7 7M17 17l1.4 1.4M18.4 5.6 17 7M7 17l-1.4 1.4"/></svg>',
  info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5.5"/><path d="M12 7.8h.01"/></svg>',
};

const MIN_PAGE_SIZE = 20;
const THEME_KEY = "werewolf-claw-theme";
const FONT_KEY = "werewolf-claw-font";
const FONT_SIZE_KEY = "werewolf-claw-font-size";
const FONT_DB = "werewolf-claw-fonts";
const DEFAULT_FONT = '"Segoe UI", "Microsoft YaHei", system-ui, sans-serif';

const state = {
  sessionId: null,
  sessions: [],
  title: "",
  hasMore: false,
  oldestSeq: null,
  loadingOlder: false,
  sending: false,
  regenerating: false,
  pending: null,
  menuSessionId: null,
  selectMode: false,
  selected: new Set(),
  profiles: [],
  activeProfile: "1",
  maxProfiles: 8,
  dragCard: null,
  newCardSeq: 0,
  quote: null,
  fonts: [],
  isNewSession: false,
  shareMode: false,
  picked: new Set(),
};

const el = {
  chat: document.getElementById("chat"),
  hero: document.getElementById("hero"),
  sessionList: document.getElementById("session-list"),
  toggleSelect: document.getElementById("toggle-select"),
  selectBar: document.getElementById("select-bar"),
  selectCount: document.getElementById("select-count"),
  pinSelected: document.getElementById("pin-selected"),
  unpinSelected: document.getElementById("unpin-selected"),
  deleteSelected: document.getElementById("delete-selected"),
  exitSelect: document.getElementById("exit-select"),
  footerMenuButton: document.getElementById("footer-menu-button"),
  footerProfile: document.getElementById("footer-profile"),
  footerHelp: document.getElementById("footer-help"),
  footerMenu: document.getElementById("footer-menu"),
  footerVersion: document.getElementById("footer-version"),
  newSession: document.getElementById("new-session"),
  currentTitle: document.getElementById("current-title"),
  modelName: document.getElementById("model-name"),
  messages: document.getElementById("messages"),
  toasts: document.getElementById("toasts"),
  composer: document.getElementById("composer"),
  input: document.getElementById("input"),
  send: document.getElementById("send"),
  quotePreview: document.getElementById("quote-preview"),
  quoteText: document.getElementById("quote-text"),
  quoteRemove: document.getElementById("quote-remove"),
  openSettings: document.getElementById("open-settings"),
  shareSession: document.getElementById("share-session"),
  exportSession: document.getElementById("export-session"),
  importSession: document.getElementById("import-session"),
  importFile: document.getElementById("import-file"),
  contextMenu: document.getElementById("context-menu"),
  renameDialog: document.getElementById("rename-dialog"),
  renameInput: document.getElementById("rename-input"),
  renameCancel: document.getElementById("rename-cancel"),
  renameSubmit: document.getElementById("rename-submit"),
  editDialog: document.getElementById("edit-dialog"),
  editInput: document.getElementById("edit-input"),
  editCancel: document.getElementById("edit-cancel"),
  editSubmit: document.getElementById("edit-submit"),
  settingsDialog: document.getElementById("settings-dialog"),
  profileList: document.getElementById("profile-list"),
  addProfile: document.getElementById("add-profile"),
  settingsHint: document.getElementById("settings-hint"),
  settingsCancel: document.getElementById("settings-cancel"),
  settingsSubmit: document.getElementById("settings-submit"),
  fontDialog: document.getElementById("font-dialog"),
  fontFamily: document.getElementById("font-family"),
  fontSize: document.getElementById("font-size"),
  fontSizeValue: document.getElementById("font-size-value"),
  fontImport: document.getElementById("font-import"),
  fontFile: document.getElementById("font-file"),
  fontReset: document.getElementById("font-reset"),
  fontClose: document.getElementById("font-close"),
  fontHint: document.getElementById("font-hint"),
  rail: document.getElementById("rail"),
  railTip: document.getElementById("rail-tip"),
  shareBar: document.getElementById("share-bar"),
  shareCount: document.getElementById("share-count"),
  shareSelectAll: document.getElementById("share-select-all"),
  shareCopyText: document.getElementById("share-copy-text"),
  shareCopyLink: document.getElementById("share-copy-link"),
  shareImage: document.getElementById("share-image"),
  shareCancel: document.getElementById("share-cancel"),
  confirmDialog: document.getElementById("confirm-dialog"),
  confirmTitle: document.getElementById("confirm-title"),
  confirmMessage: document.getElementById("confirm-message"),
  confirmOk: document.getElementById("confirm-ok"),
  confirmCancel: document.getElementById("confirm-cancel"),
};

function applyIcons(root = document) {
  root.querySelectorAll("[data-icon]").forEach((node) => {
    node.innerHTML = ICONS[node.dataset.icon] || "";
  });
}

function iconButton(name, action, label, extraClass = "") {
  const button = document.createElement("button");
  button.type = "button";
  button.dataset.action = action;
  button.className = extraClass;
  button.title = label;
  button.setAttribute("aria-label", label);
  button.innerHTML = ICONS[name] || "";
  return button;
}

function describeDetail(detail) {
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail.map((item) => item.msg || JSON.stringify(item)).join("；");
  }
  return detail ? JSON.stringify(detail) : "";
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(describeDetail(data.detail) || `请求失败（HTTP ${response.status}）`);
  }
  return data;
}

function setStatus(text, kind = "info") {
  if (!text) {
    return;
  }
  const toast = document.createElement("div");
  toast.className = `toast ${kind}`;

  const body = document.createElement("div");
  body.className = "text";
  body.textContent = text;

  const close = document.createElement("button");
  close.type = "button";
  close.className = "close";
  close.title = "关闭这条提示";
  close.setAttribute("aria-label", "关闭提示");
  close.innerHTML = ICONS.close;
  close.addEventListener("click", () => toast.remove());

  toast.append(body, close);
  el.toasts.append(toast);
  setTimeout(() => toast.remove(), kind === "error" ? 8000 : 4000);
}

/** 应用内确认弹窗，替代浏览器原生 confirm。 */
function askConfirm(title, message, okLabel = "确定") {
  return new Promise((resolve) => {
    el.confirmTitle.textContent = title;
    el.confirmMessage.textContent = message;
    el.confirmOk.textContent = okLabel;
    const finish = (value) => {
      el.confirmDialog.close();
      resolve(value);
    };
    el.confirmOk.onclick = () => finish(true);
    el.confirmCancel.onclick = () => finish(false);
    el.confirmDialog.showModal();
  });
}

function positionToasts() {
  // 提示卡片始终从顶栏下面开始，字号变化导致顶栏变高时也不会压上去
  const topbar = document.querySelector(".topbar");
  const offset = topbar ? Math.round(topbar.getBoundingClientRect().height) + 12 : 78;
  el.toasts.style.top = `${offset}px`;
}

function formatTime(value) {
  if (!value) {
    return "";
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function pageSize() {
  const height = el.messages.clientHeight || 600;
  return Math.max(MIN_PAGE_SIZE, Math.ceil(height / 80));
}

function scrollToBottom() {
  el.messages.scrollTop = el.messages.scrollHeight;
}

function updateEmptyState() {
  const hasMessages = el.messages.querySelector(".msg-row") !== null;
  el.chat.classList.toggle("empty", !hasMessages);
}

function clearMessages() {
  el.messages.replaceChildren();
  state.hasMore = false;
  state.oldestSeq = null;
  renderRail([]);
  hideRailTip();
  updateEmptyState();
}

/* ------------------------------------------------------------ 主题与设置菜单 */

function applyTheme(theme) {
  document.body.classList.toggle("dark", theme === "dark");
  localStorage.setItem(THEME_KEY, theme);
}

function toggleTheme() {
  const next = document.body.classList.contains("dark") ? "light" : "dark";
  applyTheme(next);
  setStatus(next === "dark" ? "已切换到夜间模式" : "已切换到日间模式");
}

function openFooterMenu() {
  const dark = document.body.classList.contains("dark");
  el.footerMenu.querySelector('[data-action="theme"]').textContent = dark ? "日间模式" : "夜间模式";
  el.footerMenu.hidden = false;
  const rect = el.footerMenuButton.getBoundingClientRect();
  el.footerMenu.style.left = `${rect.left}px`;
  el.footerMenu.style.right = "auto";
  el.footerMenu.style.top = "auto";
  el.footerMenu.style.bottom = `${window.innerHeight - rect.top + 6}px`;
}

function hideFooterMenu() {
  el.footerMenu.hidden = true;
}

/* ---------------------------------------------------------------- 消息渲染 */

function buildMessageRow(row) {
  const wrapper = document.createElement("div");
  wrapper.className = `msg-row ${row.role}`;
  if (row.seq) {
    wrapper.dataset.seq = String(row.seq);
  }
  if (row.compacted) {
    wrapper.classList.add("compacted");
  }

  if (row.role !== "user") {
    const avatar = document.createElement("img");
    avatar.className = "avatar";
    avatar.src = AVATARS[row.role] || AVATARS.system;
    avatar.alt = `${ROLE_LABELS[row.role] || row.role}头像`;
    wrapper.append(avatar);
  }

  const stack = document.createElement("div");
  stack.className = "msg-stack";

  // 时间放在整块消息的最上面，先于引用条，二者不会重叠
  const time = document.createElement("div");
  time.className = "time";
  time.textContent = formatTime(row.created_at);
  stack.append(time);

  if (row.quote && row.quote.excerpt) {
    const quote = document.createElement("button");
    quote.type = "button";
    quote.className = "msg-quote";
    quote.dataset.action = "jump";
    quote.dataset.jumpSeq = String(row.quote.seq);
    quote.title = "点击跳到被引用的消息";
    const text = document.createElement("span");
    text.className = "text";
    text.textContent = row.quote.excerpt;
    quote.append(text);
    stack.append(quote);
  }

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  const content = document.createElement("div");
  content.className = "content";
  content.textContent = row.content;
  bubble.append(content);

  const actions = document.createElement("div");
  actions.className = "msg-actions";
  if (row.role === "user") {
    actions.append(
      iconButton("copy", "copy", "复制"),
      iconButton("quote", "quote", "引用"),
      iconButton("share", "share", "分享这条对话"),
      iconButton("edit", "edit", "编辑这条消息", "act-edit"),
    );
  } else {
    actions.append(
      iconButton("copy", "copy", "复制"),
      iconButton("quote", "quote", "引用"),
      iconButton("share", "share", "分享这条对话"),
      iconButton("regenerate", "regenerate", "重新生成回复", "act-regenerate"),
    );
    const counter = document.createElement("span");
    counter.className = "regen-count";
    counter.textContent = row.regenerate_count ? `重新生成 ${row.regenerate_count}/5` : "";
    actions.append(counter);
  }

  stack.append(bubble, actions);
  wrapper.append(stack);
  return wrapper;
}

function buildThinkingRow() {
  const row = buildMessageRow({ role: "assistant", content: "正在思考…", created_at: "" });
  row.classList.add("thinking");
  row.querySelector(".msg-actions").remove();
  return row;
}

function refreshActionTargets() {
  const rows = Array.from(el.messages.querySelectorAll(".msg-row:not(.thinking)"));
  rows.forEach((row) => row.classList.remove("last"));
  const userRows = rows.filter((row) => row.classList.contains("user"));
  const assistantRows = rows.filter((row) => row.classList.contains("assistant"));
  if (userRows.length > 0) {
    userRows[userRows.length - 1].classList.add("last");
  }
  if (assistantRows.length > 0) {
    assistantRows[assistantRows.length - 1].classList.add("last");
  }
  refreshSharePicks();
  updateEmptyState();
}

/* ------------------------------------------------------------ 分享选择模式 */

function rowSequence(row) {
  return Number(row.dataset.seq || 0);
}

function refreshSharePicks() {
  el.chat.classList.toggle("sharing", state.shareMode);
  el.shareBar.hidden = !state.shareMode;
  if (!state.shareMode) {
    el.messages.querySelectorAll(".pick").forEach((node) => node.remove());
    return;
  }
  for (const row of el.messages.querySelectorAll(".msg-row")) {
    const seq = rowSequence(row);
    let pick = row.querySelector(".pick");
    if (!pick) {
      pick = document.createElement("button");
      pick.type = "button";
      pick.className = "pick";
      pick.dataset.action = "pick";
      pick.setAttribute("role", "checkbox");
      row.prepend(pick);
    }
    const picked = state.picked.has(seq);
    pick.setAttribute("aria-checked", picked ? "true" : "false");
    pick.title = picked ? "取消勾选这条" : "勾选这条";
    pick.innerHTML = picked ? ICONS.check : "";
    row.classList.toggle("picked", picked);
  }
  el.shareCount.textContent = `已选 ${state.picked.size} 条`;
}

function enterShareMode(seq) {
  state.shareMode = true;
  state.picked = new Set();
  const rows = Array.from(el.messages.querySelectorAll(".msg-row")).map(rowSequence);
  if (seq) {
    if (rows.includes(seq)) {
      state.picked.add(seq);
    }
    const target = el.messages.querySelector(`.msg-row[data-seq="${seq}"]`);
    if (target) {
      target.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  } else {
    rows.forEach((value) => state.picked.add(value));
  }
  refreshSharePicks();
  setStatus("勾选要分享的内容，再选择下面的操作");
}

function exitShareMode() {
  state.shareMode = false;
  state.picked.clear();
  refreshSharePicks();
}

function pickedRows() {
  return Array.from(el.messages.querySelectorAll(".msg-row"))
    .filter((row) => state.picked.has(rowSequence(row)))
    .map((row) => ({
      seq: rowSequence(row),
      role: row.classList.contains("user") ? "user" : "assistant",
      content: row.querySelector(".content").textContent,
      created_at: row.querySelector(".time").textContent,
      quote: row.querySelector(".msg-quote") ? { excerpt: row.querySelector(".msg-quote").textContent } : null,
    }));
}

async function copyPickedText() {
  const rows = pickedRows();
  if (rows.length === 0) {
    setStatus("先勾选要复制的消息", "error");
    return;
  }
  const text = rows
    .map((row) => `${ROLE_LABELS[row.role] || row.role}：${row.content}`)
    .join("\n\n");
  try {
    await navigator.clipboard.writeText(text);
    setStatus(`已复制 ${rows.length} 条消息`);
  } catch {
    setStatus("复制失败，浏览器拒绝了剪贴板权限", "error");
  }
}

async function copyShareLink() {
  const url = `${location.origin}${location.pathname}?session=${encodeURIComponent(state.sessionId)}`;
  try {
    await navigator.clipboard.writeText(url);
    setStatus("链接已复制，在本机浏览器打开可以直接进入这个会话");
  } catch {
    setStatus("复制失败，浏览器拒绝了剪贴板权限", "error");
  }
}

function renderMoreButton() {
  const existing = el.messages.querySelector(".load-more");
  if (existing) {
    existing.remove();
  }
  if (!state.hasMore) {
    return;
  }
  const button = document.createElement("button");
  button.type = "button";
  button.className = "load-more";
  button.textContent = "更多历史";
  button.addEventListener("click", () => loadOlder());
  el.messages.prepend(button);
}

function appendMessages(rows) {
  for (const row of rows) {
    el.messages.append(buildMessageRow(row));
  }
  if (rows.length > 0) {
    state.oldestSeq = rows[0].seq;
  }
  refreshActionTargets();
}

/* ------------------------------------------------------------ 引用与输入框 */

function renderQuotePreview() {
  const quote = state.quote;
  el.quotePreview.hidden = !quote;
  el.quoteText.textContent = quote ? `引用 ${quote.preview}` : "";
}

function setQuote(row) {
  const seq = Number(row.dataset.seq || 0);
  if (!seq) {
    setStatus("这条消息还没存进会话，不能引用", "error");
    return;
  }
  const text = row.querySelector(".content").textContent.trim().replace(/\s+/g, " ");
  // 引用里带上会话 id，服务端会校验，避免把别的会话的消息引用过来
  state.quote = {
    sessionId: state.sessionId,
    seq,
    preview: text.length > 40 ? `${text.slice(0, 40)}…` : text,
  };
  renderQuotePreview();
  el.input.focus();
}

function clearQuote() {
  state.quote = null;
  renderQuotePreview();
}

/* ---------------------------------------------------------------- 会话列表 */

function updateSelectBar() {
  el.selectBar.hidden = !state.selectMode;
  el.selectCount.textContent = `已选 ${state.selected.size} 项`;
  el.toggleSelect.classList.toggle("on", state.selectMode);
  el.toggleSelect.title = state.selectMode ? "退出多选" : "多选会话";
}

function groupLabel(updatedAt) {
  const date = new Date(updatedAt);
  if (Number.isNaN(date.getTime())) {
    return "更早";
  }
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const that = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const days = Math.round((today - that) / 86400000);
  if (days <= 0) {
    return "今天";
  }
  if (days === 1) {
    return "昨天";
  }
  if (days <= 7) {
    return "7 天内";
  }
  if (days <= 30) {
    return "30 天内";
  }
  return `${date.getFullYear()} 年 ${date.getMonth() + 1} 月`;
}

function sessionRow(session) {
  const item = document.createElement("li");
  item.className = "row";
  item.dataset.id = session.id;
  if (session.id === state.sessionId) {
    item.classList.add("active");
  }
  if (state.selected.has(session.id)) {
    item.classList.add("selected");
  }
  if (state.selectMode) {
    const box = document.createElement("span");
    box.className = "checkbox";
    box.innerHTML = state.selected.has(session.id) ? ICONS.check : "";
    item.append(box);
  }

  const title = document.createElement("span");
  title.className = "title";
  title.textContent = session.title || "（无标题）";
  item.append(title);

  if (session.pinned) {
    const pin = document.createElement("span");
    pin.className = "pin";
    pin.title = "已置顶";
    pin.innerHTML = ICONS.pin;
    item.append(pin);
  }

  item.addEventListener("click", () => {
    if (state.selectMode) {
      if (state.selected.has(session.id)) {
        state.selected.delete(session.id);
      } else {
        state.selected.add(session.id);
      }
      renderSessions();
    } else {
      enterSession(session.id);
    }
  });
  item.addEventListener("contextmenu", (event) => openContextMenu(event, session));
  return item;
}

function renderSessions() {
  el.sessionList.replaceChildren();

  const pinned = state.sessions.filter((session) => session.pinned);
  if (pinned.length > 0) {
    const label = document.createElement("li");
    label.className = "group";
    label.textContent = "置顶";
    el.sessionList.append(label);
    pinned.forEach((session) => el.sessionList.append(sessionRow(session)));
  }

  const buckets = new Map();
  for (const session of state.sessions.filter((item) => !item.pinned)) {
    const label = groupLabel(session.updated_at);
    if (!buckets.has(label)) {
      buckets.set(label, []);
    }
    buckets.get(label).push(session);
  }
  for (const [label, items] of buckets) {
    const heading = document.createElement("li");
    heading.className = "group";
    heading.textContent = label;
    el.sessionList.append(heading);
    items.forEach((session) => el.sessionList.append(sessionRow(session)));
  }

  updateSelectBar();
}

async function loadSessions() {
  const data = await api("/api/sessions");
  state.sessions = data.sessions;
  renderSessions();
}

function toggleSelectMode() {
  state.selectMode = !state.selectMode;
  if (!state.selectMode) {
    state.selected.clear();
  }
  renderSessions();
}

async function pinSelected(pinned) {
  const ids = Array.from(state.selected);
  if (ids.length === 0) {
    setStatus("先选中要操作的会话", "error");
    return;
  }
  try {
    await api("/api/sessions/pin", { method: "POST", body: JSON.stringify({ ids, pinned }) });
    await loadSessions();
    setStatus(`${pinned ? "已置顶" : "已取消置顶"} ${ids.length} 个会话`);
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function deleteSelected() {
  const ids = Array.from(state.selected);
  if (ids.length === 0) {
    setStatus("先选中要删除的会话", "error");
    return;
  }
  const confirmed = await askConfirm(
    "删除会话",
    `将删除选中的 ${ids.length} 个会话，消息、摘要和长期记忆都会一起删掉，且无法恢复。`,
    "删除",
  );
  if (!confirmed) {
    return;
  }
  try {
    const data = await api("/api/sessions/delete", {
      method: "POST",
      body: JSON.stringify({ ids }),
    });
    state.selected.clear();
    await loadSessions();
    if (ids.includes(state.sessionId)) {
      state.sessionId = null;
      state.title = "";
      clearMessages();
      el.currentTitle.textContent = "未选择会话";
      if (state.sessions.length > 0) {
        await enterSession(state.sessions[0].id);
      } else {
        await createSession();
      }
    }
    setStatus(`已删除 ${data.requested ?? ids.length} 个会话`);
  } catch (error) {
    setStatus(error.message, "error");
  }
}

/* ---------------------------------------------------------------- 会话内容 */

async function enterSession(sessionId) {
  setStatus("");
  hideContextMenu();
  // 换会话时清掉输入框、引用和分享选择，避免把上一个会话的内容带过来
  exitShareMode();
  clearQuote();
  el.input.value = "";
  el.input.style.height = "auto";

  const [meta, page] = await Promise.all([
    api(`/api/sessions/${encodeURIComponent(sessionId)}`),
    api(`/api/sessions/${encodeURIComponent(sessionId)}/messages?limit=${pageSize()}`),
  ]);

  state.sessionId = meta.session_id;
  state.title = meta.title;
  state.isNewSession = meta.message_count === 0;
  el.currentTitle.textContent = state.title || "未选择会话";
  clearMessages();
  appendMessages(page.messages);
  state.hasMore = page.has_more;
  renderMoreButton();
  scrollToBottom();
  renderSessions();
  loadRail();
  el.input.focus();
}

async function loadOlder() {
  if (!state.hasMore || state.loadingOlder || state.oldestSeq === null) {
    return;
  }
  state.loadingOlder = true;
  const previousHeight = el.messages.scrollHeight;
  try {
    const page = await api(
      `/api/sessions/${encodeURIComponent(state.sessionId)}/messages?limit=${pageSize()}&before_seq=${state.oldestSeq}`,
    );
    const fragment = document.createDocumentFragment();
    for (const row of page.messages) {
      fragment.append(buildMessageRow(row));
    }
    const more = el.messages.querySelector(".load-more");
    if (more) {
      more.after(fragment);
    } else {
      el.messages.prepend(fragment);
    }
    state.hasMore = page.has_more;
    if (page.messages.length > 0) {
      state.oldestSeq = page.messages[0].seq;
    }
    renderMoreButton();
    refreshActionTargets();
    el.messages.scrollTop += el.messages.scrollHeight - previousHeight;
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    state.loadingOlder = false;
  }
}

async function createSession(reload = true) {
  setStatus("");
  const data = await api("/api/sessions", { method: "POST", body: "{}" });
  if (reload) {
    await loadSessions();
  }
  await enterSession(data.session_id);
}

function abortPending() {
  if (state.pending) {
    state.pending.abort();
    state.pending = null;
  }
}

async function sendMessage(text) {
  if (!state.sessionId) {
    setStatus("请先选择或新建一个会话", "error");
    return;
  }
  if (state.sending) {
    return;
  }
  state.sending = true;
  el.send.disabled = true;
  setStatus("");

  const quote = state.quote
    ? { session_id: state.quote.sessionId, seq: state.quote.seq }
    : null;
  const placeholder = buildMessageRow({
    role: "user",
    content: text,
    created_at: new Date().toISOString(),
    // 引用信息跟着消息一起先画出来，点了发送就能看到引用了哪条
    quote: state.quote ? { seq: state.quote.seq, excerpt: state.quote.preview } : null,
  });
  el.messages.append(placeholder);
  // 新会话在用户发出第一条消息时就提示，不等模型回复
  if (state.isNewSession) {
    setStatus("已开启新会话");
    state.isNewSession = false;
  }
  const thinking = buildThinkingRow();
  el.messages.append(thinking);
  refreshActionTargets();
  scrollToBottom();
  clearQuote();

  const controller = new AbortController();
  state.pending = controller;
  try {
    const data = await api(`/api/sessions/${encodeURIComponent(state.sessionId)}/messages`, {
      method: "POST",
      body: JSON.stringify({ text, quote }),
      signal: controller.signal,
    });
    thinking.remove();
    placeholder.replaceWith(buildMessageRow(data.messages[0]));
    el.messages.append(buildMessageRow(data.messages[1]));
    refreshActionTargets();
    scrollToBottom();

    state.title = data.title;
    el.currentTitle.textContent = state.title || "未选择会话";
    const notices = [];
    if (data.remembered) {
      notices.push("已记入长期记忆");
    }
    if (data.compressed) {
      notices.push("上下文已压缩，更早的内容转入摘要");
    }
    setStatus(notices.join("；"));
    await loadSessions();
    loadRail();
  } catch (error) {
    thinking.remove();
    if (error.name !== "AbortError") {
      setStatus(error.message, "error");
    }
  } finally {
    state.pending = null;
    state.sending = false;
    el.send.disabled = false;
    updateEmptyState();
  }
}

async function copyContent(row) {
  const text = row.querySelector(".content").textContent;
  try {
    await navigator.clipboard.writeText(text);
    setStatus("已复制");
  } catch {
    setStatus("复制失败，浏览器拒绝了剪贴板权限", "error");
  }
}

async function jumpToMessage(seq) {
  const find = () => el.messages.querySelector(`.msg-row[data-seq="${seq}"]`);
  let target = find();
  // 目标可能在更早的页里，往上翻直到它出现；上限只是防止极端情况下无限翻
  let attempt = 0;
  while (!target && state.hasMore && attempt < 40) {
    setStatus(`正在定位到第 ${seq} 条…`);
    await loadOlder();
    target = find();
    attempt += 1;
  }
  if (!target) {
    setStatus("这条消息在更早的历史里，点「更多历史」继续往上翻", "error");
    return;
  }
  setStatus("");
  target.scrollIntoView({ behavior: "smooth", block: "center" });
  target.classList.add("highlight");
  setTimeout(() => target.classList.remove("highlight"), 1500);
}

/* ------------------------------------------------------------ 右侧问答戳 */

function showRailTip(entry, target) {
  el.railTip.replaceChildren();
  const question = document.createElement("div");
  question.className = "tip-question";
  question.textContent = entry.user.replace(/\s+/g, " ").trim();
  const answer = document.createElement("div");
  answer.className = "tip-answer";
  answer.textContent = (entry.assistant || "（还没有回复）").replace(/\s+/g, " ").trim();
  el.railTip.append(question, answer);
  el.railTip.hidden = false;

  const rect = target.getBoundingClientRect();
  const tipRect = el.railTip.getBoundingClientRect();
  el.railTip.style.left = `${Math.max(8, rect.left - tipRect.width - 10)}px`;
  el.railTip.style.top = `${Math.min(
    Math.max(8, rect.top - tipRect.height / 2),
    window.innerHeight - tipRect.height - 8,
  )}px`;
}

function hideRailTip() {
  el.railTip.hidden = true;
}

function renderRail(entries) {
  el.rail.replaceChildren();
  el.rail.hidden = entries.length === 0;
  for (const entry of entries) {
    const mark = document.createElement("button");
    mark.type = "button";
    mark.title = `第 ${entry.index} 轮：${entry.user.slice(0, 24)}`;
    mark.addEventListener("click", () => jumpToMessage(entry.seq));
    mark.addEventListener("mouseenter", () => showRailTip(entry, mark));
    mark.addEventListener("mouseleave", () => hideRailTip());
    el.rail.append(mark);
  }
}

async function loadRail() {
  if (!state.sessionId) {
    renderRail([]);
    return;
  }
  try {
    // 走轻量接口，整段会话的每一轮都在导航里，不受分页影响
    const data = await api(`/api/sessions/${encodeURIComponent(state.sessionId)}/outline`);
    renderRail(data.rounds.map((entry, index) => ({ ...entry, index: index + 1 })));
  } catch {
    renderRail([]);
  }
}

function openEditDialog(row) {
  if (!row.classList.contains("last")) {
    setStatus("只有最近一条消息能编辑", "error");
    return;
  }
  el.editInput.value = row.querySelector(".content").textContent;
  el.editDialog.showModal();
  el.editInput.focus();
}

async function submitEdit() {
  const text = el.editInput.value.trim();
  if (!text) {
    el.editDialog.close();
    return;
  }
  abortPending();
  clearQuote();
  setStatus("正在撤回上一轮并重新提问…");
  try {
    await api(`/api/sessions/${encodeURIComponent(state.sessionId)}/messages/edit`, {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    el.editDialog.close();
    await enterSession(state.sessionId);
    setStatus("已用编辑后的内容重新提问");
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function regenerate(row) {
  if (!state.sessionId || state.regenerating) {
    return;
  }
  const seq = Number(row.dataset.seq || 0);
  if (!seq) {
    setStatus("这条回复还没存进会话，稍后再试", "error");
    return;
  }

  state.regenerating = true;
  const content = row.querySelector(".content");
  const counter = row.querySelector(".regen-count");
  const original = content.textContent;
  content.textContent = "正在重新生成…";
  row.classList.add("thinking");
  try {
    const data = await api(`/api/sessions/${encodeURIComponent(state.sessionId)}/messages/regenerate`, {
      method: "POST",
      body: "{}",
    });
    content.textContent = data.reply;
    row.dataset.seq = String(data.message.seq);
    counter.textContent = `重新生成 ${data.regenerate_count}/${data.max_regenerate}`;
    loadRail();
    setStatus("已重新生成");
  } catch (error) {
    content.textContent = original;
    setStatus(error.message, "error");
  } finally {
    row.classList.remove("thinking");
    state.regenerating = false;
  }
}

/* ------------------------------------------------------------ 会话右键菜单 */

function openContextMenu(event, session) {
  event.preventDefault();
  state.menuSessionId = session.id;
  el.contextMenu.hidden = false;
  el.contextMenu.style.left = `${Math.min(event.clientX, window.innerWidth - 170)}px`;
  el.contextMenu.style.top = `${event.clientY}px`;
}

function hideContextMenu() {
  el.contextMenu.hidden = true;
}

function openRenameDialog() {
  const session = state.sessions.find((item) => item.id === state.menuSessionId);
  el.renameInput.value = session ? session.title : "";
  el.renameDialog.showModal();
  el.renameInput.focus();
  el.renameInput.select();
}

async function submitRename() {
  const title = el.renameInput.value.trim();
  const sessionId = state.menuSessionId;
  if (!title || !sessionId) {
    el.renameDialog.close();
    return;
  }
  try {
    const data = await api(`/api/sessions/${encodeURIComponent(sessionId)}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    });
    el.renameDialog.close();
    if (sessionId === state.sessionId) {
      state.title = data.title;
      el.currentTitle.textContent = data.title;
    }
    await loadSessions();
    setStatus(`已重命名为「${data.title}」，之后不会再自动改名`);
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function deleteSession(sessionId) {
  if (!sessionId) {
    return;
  }
  const confirmed = await askConfirm(
    "删除会话",
    "这个会话的消息、摘要和长期记忆都会被删除，且无法恢复。",
    "删除",
  );
  if (!confirmed) {
    return;
  }
  try {
    await api(`/api/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
    await loadSessions();
    if (sessionId === state.sessionId) {
      state.sessionId = null;
      state.title = "";
      clearMessages();
      el.currentTitle.textContent = "未选择会话";
      if (state.sessions.length > 0) {
        await enterSession(state.sessions[0].id);
      } else {
        await createSession();
      }
    }
    setStatus("会话已删除");
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function pinSession(sessionId, pinned) {
  try {
    await api("/api/sessions/pin", {
      method: "POST",
      body: JSON.stringify({ ids: [sessionId], pinned }),
    });
    await loadSessions();
    setStatus(pinned ? "已置顶" : "已取消置顶");
  } catch (error) {
    setStatus(error.message, "error");
  }
}

/* ------------------------------------------------------------ 导出 / 导入 */

async function exportSession() {
  if (!state.sessionId) {
    setStatus("请先选择或新建一个会话", "error");
    return;
  }
  const confirmed = await askConfirm(
    "导出前请确认",
    "导出会把这段对话的完整内容（你的提问、助手的回答、长期记忆）保存成文件。" +
      "把文件发给别人，或上传到网盘、聊天工具里，都可能泄露你的隐私信息。",
    "仍要导出",
  );
  if (!confirmed) {
    setStatus("已取消导出");
    return;
  }
  const link = document.createElement("a");
  link.href = `/api/sessions/${encodeURIComponent(state.sessionId)}/export`;
  link.download = "werewolf-claw-session.json";
  document.body.append(link);
  link.click();
  link.remove();
  setStatus("已开始下载这个会话的导出文件");
}

async function importSession(file) {
  try {
    const payload = JSON.parse(await file.text());
    const data = await api("/api/sessions/import", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    await loadSessions();
    await enterSession(data.session_id);
    setStatus(`已导入会话「${data.title}」`);
  } catch (error) {
    setStatus(error instanceof SyntaxError ? "导入失败：文件不是合法的 JSON" : error.message, "error");
  }
}

/* ------------------------------------------------------------ 分享成图片 */

function wrapCanvasText(ctx, text, maxWidth) {
  const lines = [];
  for (const paragraph of String(text).split("\n")) {
    if (paragraph === "") {
      lines.push("");
      continue;
    }
    let line = "";
    for (const char of paragraph) {
      const next = line + char;
      if (ctx.measureText(next).width > maxWidth && line !== "") {
        lines.push(line);
        line = char;
      } else {
        line = next;
      }
    }
    lines.push(line);
  }
  return lines;
}

/** 把勾选的消息画成一张分享卡片：顶部应用名、中间问答、底部说明。 */
async function renderShareCard(rows) {
  const scale = 2;
  const width = 720;
  const padding = 36;
  const innerPad = 14;
  const blockGap = 18;
  const headerHeight = 126;
  const footerHeight = 76;
  const fontFamily = getComputedStyle(document.body).fontFamily;
  const fontSize = Math.round(parseFloat(getComputedStyle(document.body).fontSize)) || 14;
  const lineHeight = Math.round(fontSize * 1.75) || 25;
  // 对话块最宽不超过图片宽度的 80%
  const maxBlockWidth = Math.round(width * 0.8);

  const styles = getComputedStyle(document.body);
  const panel = styles.getPropertyValue("--panel").trim() || "#ffffff";
  const border = styles.getPropertyValue("--border").trim() || "#e5e7eb";
  const textColor = styles.getPropertyValue("--text").trim() || "#1f2430";
  const muted = styles.getPropertyValue("--muted").trim() || "#8b93a1";
  const highlight = styles.getPropertyValue("--accent-soft").trim() || "#eef2fb";

  const measure = document.createElement("canvas").getContext("2d");
  measure.font = `${fontSize}px ${fontFamily}`;

  const blocks = [];
  let height = headerHeight;
  for (const row of rows) {
    const isUser = row.role === "user";
    const wrapWidth = maxBlockWidth - innerPad * 2;
    const lines = wrapCanvasText(measure, row.content, wrapWidth);
    const textWidth = Math.max(...lines.map((line) => measure.measureText(line).width), 0);
    const blockWidth = Math.min(maxBlockWidth, Math.ceil(textWidth) + innerPad * 2);
    const blockHeight = lines.length * lineHeight + innerPad * 2;
    blocks.push({ row, lines, isUser, blockWidth, blockHeight });
    height += blockHeight + blockGap;
  }
  height += footerHeight;

  const canvas = document.createElement("canvas");
  canvas.width = width * scale;
  canvas.height = height * scale;
  const ctx = canvas.getContext("2d");
  ctx.scale(scale, scale);
  // 用 middle 基线，文字块才能在大框里上下居中
  ctx.textBaseline = "middle";
  ctx.fillStyle = panel;
  ctx.fillRect(0, 0, width, height);

  // 最顶上是居中的应用名，下面一条分割线
  ctx.textAlign = "center";
  ctx.fillStyle = textColor;
  ctx.font = `600 20px ${fontFamily}`;
  ctx.fillText("Werewolf-Claw", width / 2, 30);
  ctx.strokeStyle = border;
  ctx.beginPath();
  ctx.moveTo(padding, 58);
  ctx.lineTo(width - padding, 58);
  ctx.stroke();

  // 分割线下面：会话标题粗体、大一点、靠左，时间小字跟在下面
  ctx.textAlign = "left";
  ctx.fillStyle = textColor;
  ctx.font = `700 17px ${fontFamily}`;
  ctx.fillText(state.title || "对话记录", padding, 82);
  ctx.fillStyle = muted;
  ctx.font = `12px ${fontFamily}`;
  ctx.fillText(`生成时间 ${new Date().toLocaleString()}`, padding, 108);

  let y = headerHeight;
  for (const block of blocks) {
    const { lines, isUser, blockWidth, blockHeight } = block;
    // 用户的靠右、助手的靠左，都是一条不超过 80% 宽的块
    const boxX = isUser ? width - padding - blockWidth : padding;
    ctx.fillStyle = isUser ? highlight : panel;
    ctx.strokeStyle = isUser ? highlight : border;
    ctx.beginPath();
    ctx.roundRect(boxX, y, blockWidth, blockHeight, 12);
    ctx.fill();
    if (!isUser) {
      ctx.stroke();
    }
    ctx.fillStyle = textColor;
    ctx.font = `${fontSize}px ${fontFamily}`;
    const centerY = y + blockHeight / 2;
    lines.forEach((line, index) => {
      const lineY = centerY + (index - (lines.length - 1) / 2) * lineHeight;
      ctx.fillText(line, boxX + innerPad, lineY);
    });
    y += blockHeight + blockGap;
  }

  ctx.strokeStyle = border;
  ctx.beginPath();
  ctx.moveTo(padding, y);
  ctx.lineTo(width - padding, y);
  ctx.stroke();
  ctx.fillStyle = muted;
  ctx.font = `12px ${fontFamily}`;
  ctx.textAlign = "center";
  ctx.fillText("由 AI 生成，请仔细甄别", width / 2, y + 26);
  ctx.textAlign = "left";

  return canvas;
}

function fileStamp() {
  const now = new Date();
  const pad = (value) => String(value).padStart(2, "0");
  return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}`;
}

function safeFileName(text) {
  return (text || "对话记录").replace(/[\\/:*?"<>|\s]+/g, "-").slice(0, 40) || "对话记录";
}

async function shareConversation() {
  if (!state.sessionId) {
    setStatus("请先选择或新建一个会话", "error");
    return;
  }
  enterShareMode();
}

/** 把勾选的消息画成一张分享卡片：顶部标题、中间对话、底部说明。 */
async function generateShareImage() {
  const rows = pickedRows();
  if (rows.length === 0) {
    setStatus("先勾选要生成图片的消息", "error");
    return;
  }
  setStatus("正在生成图片…");
  try {
    const canvas = await renderShareCard(rows);
    const name = `werewolf_claw-${safeFileName(state.title)}-${fileStamp()}.png`;
    const link = document.createElement("a");
    link.href = canvas.toDataURL("image/png");
    link.download = name;
    document.body.append(link);
    link.click();
    link.remove();
    setStatus(`已生成 ${name}`);
  } catch (error) {
    setStatus(`生成图片失败：${error.message}`, "error");
  }
}

/* ---------------------------------------------------------------- 模型配置 */

/* ---------------------------------------------------------------- 字体设置 */

function fontDatabase() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(FONT_DB, 1);
    request.onupgradeneeded = () => request.result.createObjectStore("fonts", { keyPath: "name" });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function fontStore(mode, action) {
  const database = await fontDatabase();
  return new Promise((resolve, reject) => {
    const request = action(database.transaction("fonts", mode).objectStore("fonts"));
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function registerFont(name, buffer) {
  const face = new FontFace(name, buffer);
  await face.load();
  document.fonts.add(face);
}

function renderFontOptions() {
  const current = localStorage.getItem(FONT_KEY) || "";
  el.fontFamily.replaceChildren();
  const options = [{ value: "", label: "系统默认" }, ...state.fonts.map((name) => ({ value: name, label: name }))];
  for (const option of options) {
    const node = document.createElement("option");
    node.value = option.value;
    node.textContent = option.label;
    el.fontFamily.append(node);
  }
  el.fontFamily.value = current;
}

function applyFontSettings() {
  const family = localStorage.getItem(FONT_KEY) || "";
  const size = localStorage.getItem(FONT_SIZE_KEY) || "14";
  document.documentElement.style.setProperty(
    "--chat-font",
    family ? `"${family}", ${DEFAULT_FONT}` : DEFAULT_FONT,
  );
  document.documentElement.style.setProperty("--chat-font-size", `${size}px`);
  el.fontSize.value = size;
  el.fontSizeValue.textContent = `${size} px`;
  positionToasts();
}

async function loadStoredFonts() {
  try {
    const records = (await fontStore("readonly", (store) => store.getAll())) || [];
    for (const record of records) {
      await registerFont(record.name, record.data);
    }
    state.fonts = records.map((record) => record.name);
  } catch {
    state.fonts = [];
  }
  renderFontOptions();
}

async function importFontFile(file) {
  try {
    const buffer = await file.arrayBuffer();
    const name = file.name.replace(/\.[^.]+$/, "");
    await registerFont(name, buffer.slice(0));
    await fontStore("readwrite", (store) => store.put({ name, data: buffer }));
    if (!state.fonts.includes(name)) {
      state.fonts.push(name);
    }
    localStorage.setItem(FONT_KEY, name);
    renderFontOptions();
    applyFontSettings();
    el.fontHint.textContent = `已导入「${name}」，字体会存在浏览器本地，下次打开还在。`;
  } catch (error) {
    el.fontHint.textContent = "导入失败，请确认文件是 ttf / otf / woff 字体。";
    setStatus(`导入字体失败：${error.message || error}`, "error");
  }
}

function openFontDialog() {
  renderFontOptions();
  applyFontSettings();
  el.fontHint.textContent = `当前可用字体：系统默认${state.fonts.length ? `、${state.fonts.join("、")}` : ""}。导入的字体只保存在你自己的浏览器里。`;
  el.fontDialog.showModal();
}

function cardValues(card) {
  return {
    id: card.dataset.id || null,
    name: card.querySelector(".p-name").value.trim(),
    api_key: card.querySelector(".p-key").value.trim(),
    base_url: card.querySelector(".p-base").value.trim(),
    model: card.querySelector(".p-model").value.trim(),
  };
}

function refreshCard(card) {
  const values = cardValues(card);
  const isActive = Boolean(card.dataset.id) && card.dataset.id === state.activeProfile;
  card.classList.toggle("active", isActive);
  card.querySelector(".monogram").textContent = (values.name || "?").trim().charAt(0).toUpperCase();
  card.querySelector(".profile-name").textContent = values.name || "未命名配置";
  card.querySelector(".profile-url").textContent = values.base_url || "OpenAI 官方地址";
  card.querySelector(".profile-meta").textContent = `模型 ${values.model || "未指定"}`;

  const badge = card.querySelector(".badge");
  badge.textContent = isActive ? "使用中" : "";
  badge.hidden = !isActive;

  const use = card.querySelector(".use");
  use.disabled = isActive;
  use.classList.toggle("active", isActive);
  use.innerHTML = isActive ? `<span class="icon">${ICONS.check}</span>使用中` : "使用";
}

function refreshCards() {
  el.profileList.querySelectorAll(".profile-card").forEach(refreshCard);
}

function profileCard(profile) {
  const card = document.createElement("div");
  card.className = "profile-card";
  card.dataset.id = profile.id || `new-${++state.newCardSeq}`;

  const grip = document.createElement("div");
  grip.className = "grip";
  grip.innerHTML = ICONS.grip;
  grip.title = "拖动排序";
  grip.draggable = true;
  grip.addEventListener("dragstart", () => {
    state.dragCard = card;
    card.classList.add("dragging");
  });
  grip.addEventListener("dragend", () => {
    card.classList.remove("dragging");
    state.dragCard = null;
  });
  card.addEventListener("dragover", (event) => event.preventDefault());
  card.addEventListener("drop", (event) => {
    event.preventDefault();
    if (state.dragCard && state.dragCard !== card) {
      const cards = Array.from(el.profileList.children);
      if (cards.indexOf(state.dragCard) < cards.indexOf(card)) {
        card.after(state.dragCard);
      } else {
        card.before(state.dragCard);
      }
    }
  });

  const monogram = document.createElement("div");
  monogram.className = "monogram";

  const main = document.createElement("div");
  main.className = "profile-main";
  const titleRow = document.createElement("div");
  titleRow.className = "profile-title";
  const name = document.createElement("span");
  name.className = "profile-name";
  const badge = document.createElement("span");
  badge.className = "badge";
  titleRow.append(name, badge);
  const url = document.createElement("div");
  url.className = "profile-url";
  const meta = document.createElement("div");
  meta.className = "profile-meta";
  main.append(titleRow, url, meta);

  const actions = document.createElement("div");
  actions.className = "profile-actions";
  const use = document.createElement("button");
  use.type = "button";
  use.className = "use";
  use.addEventListener("click", () => {
    state.activeProfile = card.dataset.id;
    refreshCards();
  });

  const edit = iconButton("edit", "toggle-edit", "编辑配置");
  edit.addEventListener("click", () => {
    card.classList.toggle("editing");
    const editing = card.classList.contains("editing");
    edit.innerHTML = editing ? ICONS.check : ICONS.edit;
    edit.title = editing ? "完成编辑" : "编辑配置";
    if (!editing) {
      refreshCard(card);
    }
  });

  const duplicate = iconButton("copy", "duplicate", "复制这套配置");
  duplicate.addEventListener("click", () => {
    const values = cardValues(card);
    addProfileCard({
      name: `${values.name || "配置"} 副本`,
      base_url: values.base_url,
      model: values.model,
    });
  });

  const remove = iconButton("trash", "remove", "删除这套配置");
  remove.addEventListener("click", () => {
    if (el.profileList.children.length <= 1) {
      setStatus("至少要留一套配置", "error");
      return;
    }
    if (card.dataset.id === state.activeProfile) {
      const next = Array.from(el.profileList.children).find((item) => item !== card);
      state.activeProfile = next ? next.dataset.id : "";
    }
    card.remove();
    refreshCards();
  });

  actions.append(use, edit, duplicate, remove);

  const editPanel = document.createElement("div");
  editPanel.className = "profile-edit";
  const fields = [
    ["name", "配置名称", profile.name || ""],
    ["key", "API Key", "", profile.has_api_key ? `已保存（${profile.api_key}），留空表示不改` : "还没有配置密钥"],
    ["base", "Base URL", profile.base_url || ""],
    ["model", "模型名", profile.model || ""],
  ];
  for (const [key, label, value, placeholder] of fields) {
    const wrapper = document.createElement("label");
    wrapper.className = "field";
    wrapper.textContent = label;
    const input = document.createElement("input");
    input.className = `p-${key}`;
    input.value = value;
    if (placeholder) {
      input.placeholder = placeholder;
    }
    input.addEventListener("input", () => refreshCard(card));
    wrapper.append(input);
    editPanel.append(wrapper);
  }

  card.append(grip, monogram, main, actions, editPanel);
  refreshCard(card);
  return card;
}

function addProfileCard(profile = {}) {
  if (el.profileList.children.length >= state.maxProfiles) {
    setStatus(`最多只能配置 ${state.maxProfiles} 套`, "error");
    return;
  }
  const index = el.profileList.children.length + 1;
  el.profileList.append(
    profileCard({
      id: null,
      name: profile.name || `模型配置${index}`,
      api_key: "",
      has_api_key: false,
      base_url: profile.base_url || "",
      model: profile.model || "",
    }),
  );
}

async function openSettings() {
  try {
    const data = await api("/api/settings");
    state.profiles = data.profiles;
    state.activeProfile = data.active;
    state.maxProfiles = data.max_profiles;
    el.profileList.replaceChildren();
    data.profiles.forEach((profile) => el.profileList.append(profileCard(profile)));
    el.settingsHint.textContent = `保存位置：${data.env_file}`;
    el.settingsDialog.showModal();
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function submitSettings() {
  const cards = Array.from(el.profileList.querySelectorAll(".profile-card"));
  if (cards.length === 0) {
    setStatus("至少要留一套配置", "error");
    return;
  }
  const profiles = cards.map(cardValues);
  try {
    const data = await api("/api/settings", {
      method: "PUT",
      body: JSON.stringify({ active: state.activeProfile, profiles }),
    });
    state.activeProfile = data.active;
    state.profiles = data.profiles;
    el.profileList.replaceChildren();
    data.profiles.forEach((profile) => el.profileList.append(profileCard(profile)));
    el.settingsDialog.close();
    const used = data.profiles.find((profile) => profile.id === data.active) || data.profiles[0];
    el.modelName.textContent = used.model ? `模型 ${used.model}（${used.name}）` : used.name;
    el.footerProfile.textContent = used.name;
    el.input.placeholder = "给 Werewolf-Claw 发送消息";
    setStatus(`已保存 ${data.profiles.length} 套配置，当前使用「${used.name}」`);
  } catch (error) {
    setStatus(error.message, "error");
  }
}

/* ---------------------------------------------------------------- 事件绑定 */

el.messages.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-action]");
  const pick = event.target.closest(".pick");
  if (state.shareMode && (pick || !button)) {
    // 分享模式下点整行就是勾选/取消勾选
    const row = event.target.closest(".msg-row");
    if (row) {
      const seq = rowSequence(row);
      if (state.picked.has(seq)) {
        state.picked.delete(seq);
      } else {
        state.picked.add(seq);
      }
      refreshSharePicks();
    }
    return;
  }
  if (!button) {
    return;
  }
  const row = button.closest(".msg-row");
  const action = button.dataset.action;
  if (action === "jump") {
    jumpToMessage(Number(button.dataset.jumpSeq || 0));
  } else if (action === "share") {
    enterShareMode(rowSequence(row));
  } else if (action === "copy") {
    copyContent(row);
  } else if (action === "quote") {
    setQuote(row);
  } else if (action === "edit") {
    openEditDialog(row);
  } else if (action === "regenerate") {
    regenerate(row);
  }
});

el.sessionList.addEventListener("contextmenu", (event) => event.preventDefault());

el.contextMenu.addEventListener("click", (event) => {
  const action = event.target.dataset ? event.target.dataset.action : null;
  const sessionId = state.menuSessionId;
  if (action === "rename") {
    openRenameDialog();
  } else if (action === "delete") {
    deleteSession(sessionId);
  } else if (action === "pin") {
    pinSession(sessionId, true);
  } else if (action === "unpin") {
    pinSession(sessionId, false);
  }
  hideContextMenu();
});

el.footerMenu.addEventListener("click", (event) => {
  const action = event.target.closest("li") ? event.target.closest("li").dataset.action : null;
  if (action === "settings") {
    openSettings();
  } else if (action === "font") {
    openFontDialog();
  } else if (action === "theme") {
    toggleTheme();
  } else if (action === "help") {
    window.open("/help", "_blank");
  } else if (action === "about") {
    window.open("/about", "_blank");
  }
  hideFooterMenu();
});

document.addEventListener("click", (event) => {
  if (!el.contextMenu.hidden && !el.contextMenu.contains(event.target)) {
    hideContextMenu();
  }
  if (
    !el.footerMenu.hidden &&
    !el.footerMenu.contains(event.target) &&
    !el.footerMenuButton.contains(event.target)
  ) {
    hideFooterMenu();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    hideContextMenu();
    hideFooterMenu();
  }
});

el.newSession.addEventListener("click", () => createSession());
el.shareSelectAll.addEventListener("click", () => {
  const rows = Array.from(el.messages.querySelectorAll(".msg-row")).map(rowSequence);
  if (state.picked.size === rows.length) {
    state.picked.clear();
  } else {
    rows.forEach((value) => state.picked.add(value));
  }
  refreshSharePicks();
});
el.shareCopyText.addEventListener("click", () => copyPickedText());
el.shareCopyLink.addEventListener("click", () => copyShareLink());
el.shareImage.addEventListener("click", () => generateShareImage());
el.shareCancel.addEventListener("click", () => exitShareMode());
el.toggleSelect.addEventListener("click", () => toggleSelectMode());
el.pinSelected.addEventListener("click", () => pinSelected(true));
el.unpinSelected.addEventListener("click", () => pinSelected(false));
el.deleteSelected.addEventListener("click", () => deleteSelected());
el.exitSelect.addEventListener("click", () => toggleSelectMode());
el.footerMenuButton.addEventListener("click", (event) => {
  event.stopPropagation();
  if (el.footerMenu.hidden) {
    openFooterMenu();
  } else {
    hideFooterMenu();
  }
});
el.footerHelp.addEventListener("click", () => window.open("/help", "_blank"));
el.quoteRemove.addEventListener("click", () => clearQuote());
el.renameCancel.addEventListener("click", () => el.renameDialog.close());
el.renameSubmit.addEventListener("click", () => submitRename());
el.renameInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    submitRename();
  }
});
el.editCancel.addEventListener("click", () => el.editDialog.close());
el.editSubmit.addEventListener("click", () => submitEdit());
el.openSettings.addEventListener("click", () => openSettings());
el.shareSession.addEventListener("click", () => shareConversation());
el.fontImport.addEventListener("click", () => el.fontFile.click());
el.fontFile.addEventListener("change", () => {
  const file = el.fontFile.files[0];
  if (file) {
    importFontFile(file);
  }
  el.fontFile.value = "";
});
el.fontFamily.addEventListener("change", () => {
  if (el.fontFamily.value) {
    localStorage.setItem(FONT_KEY, el.fontFamily.value);
  } else {
    localStorage.removeItem(FONT_KEY);
  }
  applyFontSettings();
});
el.fontSize.addEventListener("input", () => {
  localStorage.setItem(FONT_SIZE_KEY, el.fontSize.value);
  applyFontSettings();
});
el.fontReset.addEventListener("click", () => {
  localStorage.removeItem(FONT_KEY);
  localStorage.removeItem(FONT_SIZE_KEY);
  applyFontSettings();
  renderFontOptions();
  el.fontHint.textContent = "已恢复默认字体和字号。";
});
el.fontClose.addEventListener("click", () => el.fontDialog.close());
el.addProfile.addEventListener("click", () => addProfileCard());
el.settingsCancel.addEventListener("click", () => el.settingsDialog.close());
el.settingsSubmit.addEventListener("click", () => submitSettings());
el.exportSession.addEventListener("click", () => exportSession());
el.importSession.addEventListener("click", () => el.importFile.click());
el.importFile.addEventListener("change", () => {
  const file = el.importFile.files[0];
  if (file) {
    importSession(file);
  }
  el.importFile.value = "";
});

el.composer.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = el.input.value.trim();
  if (!text) {
    return;
  }
  el.input.value = "";
  el.input.style.height = "auto";
  sendMessage(text);
});

el.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    el.composer.requestSubmit();
  }
});

el.input.addEventListener("input", () => {
  el.input.style.height = "auto";
  el.input.style.height = `${Math.min(el.input.scrollHeight, 180)}px`;
});

async function init() {
  applyIcons();
  applyTheme(localStorage.getItem(THEME_KEY) || "light");
  applyFontSettings();
  positionToasts();
  window.addEventListener("resize", () => positionToasts());
  el.hero.hidden = false;
  renderQuotePreview();
  try {
    await loadStoredFonts();
    const health = await api("/api/health");
    el.modelName.textContent = health.model ? `模型 ${health.model}（${health.profile_name}）` : "";
    el.footerProfile.textContent = health.profile_name || "模型配置";
    el.footerVersion.textContent = `v${health.version || "0.1.0"}`;
    el.input.placeholder = "给 Werewolf-Claw 发送消息";
    await loadSessions();
    // 带 ?session= 时直接进那个会话（复制链接分享用），否则从新对话开始
    const wanted = new URLSearchParams(location.search).get("session");
    if (wanted && state.sessions.some((item) => item.id === wanted)) {
      try {
        await enterSession(wanted);
        setStatus("已通过链接进入会话");
        return;
      } catch (error) {
        setStatus(`链接里的会话打不开（${error.message}），已新建会话`, "error");
      }
    }
    // 会话列表上面已经拉过一次，这里不用再拉
    await createSession(false);
  } catch (error) {
    setStatus(error.message, "error");
  }
}

init();
