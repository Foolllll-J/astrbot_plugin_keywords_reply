const bridge = window.AstrBotPluginPage;

const TEXT = {
  keywordTab: "关键词",
  detectTab: "检测词",
  unnamedRule: "未命名规则",
  emptyEntry: "(空回复)",
  disabledScope: "全局禁用",
  whitelist: "白名单",
  blacklist: "黑名单",
  entryLabel: "回复",
  saveSuccess: "规则已保存",
  saveLoading: "正在保存规则...",
  refreshLoading: "正在刷新...",
  refreshSuccess: "已刷新",
  createDraft: "已创建规则草稿",
  deleteDraft: "已删除当前规则草稿，记得保存",
  uploadFailed: "上传失败",
  saveFailed: "保存失败",
  keepOneEntry: "至少保留一条回复",
  atAllHint: "@全体成员",
  existingFaceHint: "已有 QQ 官方表情组件",
  unknownComponent: "未知组件类型",
  boolOn: "开启",
  boolOff: "关闭",
  defaultPrefix: "默认: ",
};

const BOOLEAN_OVERRIDE_FIELDS = [
  ["quote_reply", "引用回复"],
  ["qq_forward_all_replies", "合并转发全部回复"],
  ["case_sensitive", "大小写敏感"],
];

const INT_OVERRIDE_FIELDS = [["recall_delay", "自动撤回延迟(秒)", "int"]];

const DETECT_EXTRA_OVERRIDE_FIELDS = [
  ["cooldown", "冷却时间(秒)", "int"],
  ["ignore_cooldown_on_exact_match", "完全匹配忽略冷却", "bool"],
];

const state = {
  loaded: null,
  draft: null,
  currentKind: "command_triggered",
  currentRuleIndex: -1,
  currentEntryIndex: 0,
  search: "",
  uploadType: "image",
  statusTimer: null,
};

const els = {
  refreshBtn: document.getElementById("refreshBtn"),
  searchInput: document.getElementById("searchInput"),
  newRuleBtn: document.getElementById("newRuleBtn"),
  listMeta: document.getElementById("listMeta"),
  ruleList: document.getElementById("ruleList"),
  emptyState: document.getElementById("emptyState"),
  editor: document.getElementById("editor"),
  editorEyebrow: document.getElementById("editorEyebrow"),
  editorTitle: document.getElementById("editorTitle"),
  statusBanner: document.getElementById("statusBanner"),
  saveBtn: document.getElementById("saveBtn"),
  deleteRuleBtn: document.getElementById("deleteRuleBtn"),
  keywordInput: document.getElementById("keywordInput"),
  regexInput: document.getElementById("regexInput"),
  scopeModeInput: document.getElementById("scopeModeInput"),
  groupsInput: document.getElementById("groupsInput"),
  overrideGrid: document.getElementById("overrideGrid"),
  entryList: document.getElementById("entryList"),
  newEntryBtn: document.getElementById("newEntryBtn"),
  componentList: document.getElementById("componentList"),
  hiddenUploadInput: document.getElementById("hiddenUploadInput"),
};

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function clearStatusTimer() {
  if (state.statusTimer) {
    window.clearTimeout(state.statusTimer);
    state.statusTimer = null;
  }
}

function setStatus(message, tone = "info", autoHide = tone === "success") {
  clearStatusTimer();
  if (!message) {
    els.statusBanner.textContent = "";
    els.statusBanner.dataset.tone = "";
    els.statusBanner.classList.add("hidden");
    return;
  }
  els.statusBanner.textContent = message;
  els.statusBanner.dataset.tone = tone;
  els.statusBanner.classList.remove("hidden");
  if (autoHide) {
    state.statusTimer = window.setTimeout(() => setStatus(""), 2600);
  }
}

function getRules(kind = state.currentKind) {
  return state.draft?.[kind] || [];
}

function boolLabel(value) {
  return value ? TEXT.boolOn : TEXT.boolOff;
}

function parseGroupInput(raw) {
  return String(raw ?? "")
    .split(/[\s,，、;；]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .filter((item, index, list) => list.indexOf(item) === index);
}

function makeOverrides(kind, defaults = {}) {
  const overrides = {
    quote_reply: Boolean(defaults.quote_reply),
    qq_forward_all_replies: Boolean(defaults.qq_forward_all_replies),
    recall_delay:
      kind === "command_triggered"
        ? Number(defaults.keyword_recall_delay || 0)
        : Number(defaults.detect_recall_delay || 0),
    case_sensitive: Boolean(defaults.case_sensitive),
  };
  if (kind === "auto_detect") {
    overrides.cooldown = Number(defaults.cooldown || 0);
    overrides.ignore_cooldown_on_exact_match = Boolean(
      defaults.ignore_cooldown_on_exact_match
    );
  }
  return overrides;
}

function makeEmptyEntry() {
  return { components: [{ type: "text", content: "" }], summary: TEXT.emptyEntry };
}

function makeEmptyRule(kind) {
  const defaults = state.loaded?.defaults || {};
  return {
    keyword: "",
    regex: false,
    enabled: true,
    mode: "whitelist",
    groups: [],
    entries: [makeEmptyEntry()],
    overrides: makeOverrides(kind, defaults),
  };
}

function getCurrentRule() {
  const rules = getRules();
  if (state.currentRuleIndex < 0 || state.currentRuleIndex >= rules.length) {
    return null;
  }
  return rules[state.currentRuleIndex];
}

function getCurrentEntry() {
  const rule = getCurrentRule();
  if (!rule) {
    return null;
  }
  if (state.currentEntryIndex < 0 || state.currentEntryIndex >= rule.entries.length) {
    return null;
  }
  return rule.entries[state.currentEntryIndex];
}

function summarizeComponents(components) {
  const text = (components.find((item) => item.type === "text")?.content || "")
    .replace(/\n/g, " ")
    .trim();
  const counts = {
    image: 0,
    record: 0,
    video: 0,
    at: 0,
    face: 0,
    forward: 0,
  };
  for (const item of components) {
    if (item.type === "at" || item.type === "atall") counts.at += 1;
    if (item.type === "face") counts.face += 1;
    if (item.type === "image") counts.image += 1;
    if (item.type === "record") counts.record += 1;
    if (item.type === "video") counts.video += 1;
    if (item.type === "forward") counts.forward += 1;
  }
  const head = text ? `${text.slice(0, 36)}${text.length > 36 ? "..." : ""}` : "";
  const tags = [];
  if (counts.image) tags.push(`[图片 x${counts.image}]`);
  if (counts.record) tags.push(`[语音 x${counts.record}]`);
  if (counts.video) tags.push(`[视频 x${counts.video}]`);
  if (counts.at) tags.push(`[@ x${counts.at}]`);
  if (counts.face) tags.push(`[表情 x${counts.face}]`);
  if (counts.forward) tags.push(`[聊天记录 x${counts.forward}]`);
  return head || tags.join("") || TEXT.emptyEntry;
}

function syncCurrentRule() {
  const rule = getCurrentRule();
  if (!rule) return;
  rule.keyword = els.keywordInput.value.trim();
  rule.regex = Boolean(els.regexInput.checked);
  const scopeMode = els.scopeModeInput.value;
  if (scopeMode === "disabled") {
    rule.enabled = false;
    rule.mode = "whitelist";
  } else {
    rule.enabled = true;
    rule.mode = scopeMode;
  }
  rule.groups = parseGroupInput(els.groupsInput.value);
}

function getScopeLabel(rule) {
  if (!rule.enabled) return TEXT.disabledScope;
  const scope = rule.mode === "blacklist" ? TEXT.blacklist : TEXT.whitelist;
  return `${scope} ${rule.groups.length} 群`;
}

function filterRules(rules) {
  const query = state.search.trim().toLowerCase();
  if (!query) return rules.map((rule, index) => ({ rule, index }));
  return rules
    .map((rule, index) => ({ rule, index }))
    .filter(({ rule }) => {
      const joined = [
        rule.keyword,
        getScopeLabel(rule),
        ...(rule.groups || []),
        ...(rule.entries || []).map((entry) => summarizeComponents(entry.components || [])),
      ]
        .join(" ")
        .toLowerCase();
      return joined.includes(query);
    });
}

function renderRuleList() {
  const rules = getRules();
  const filtered = filterRules(rules);
  const label = state.currentKind === "command_triggered" ? TEXT.keywordTab : TEXT.detectTab;
  els.listMeta.textContent = `${label} ${filtered.length} 条`;
  els.ruleList.innerHTML = filtered
    .map(
      ({ rule, index }) => `
      <article class="rule-card ${state.currentRuleIndex === index ? "active" : ""}" data-rule-index="${index}">
        <div class="rule-card-head">
          <div class="rule-card-title">${escapeHtml(rule.keyword || TEXT.unnamedRule)}</div>
          <div class="button-row">
            ${rule.regex ? '<span class="badge">regex</span>' : ""}
          </div>
        </div>
        <div class="rule-card-meta">${escapeHtml(getScopeLabel(rule))}</div>
        <div class="rule-card-meta">${escapeHtml(`${rule.entries.length} 条回复`)}</div>
      </article>
    `
    )
    .join("");

  for (const node of els.ruleList.querySelectorAll("[data-rule-index]")) {
    node.addEventListener("click", () => {
      syncCurrentRule();
      state.currentRuleIndex = Number(node.dataset.ruleIndex);
      state.currentEntryIndex = 0;
      renderAll();
    });
  }
}

function getDefaultOverrideValue(key, kind, defaults) {
  if (key === "recall_delay") {
    return kind === "command_triggered"
      ? Number(defaults.keyword_recall_delay || 0)
      : Number(defaults.detect_recall_delay || 0);
  }
  if (key === "cooldown") {
    return Number(defaults.cooldown || 0);
  }
  return Boolean(defaults[key]);
}

function formatDefaultValue(value, type) {
  if (type === "bool") {
    return boolLabel(Boolean(value));
  }
  return String(Number(value || 0));
}

function renderOverrideGrid() {
  const rule = getCurrentRule();
  if (!rule) return;
  const defaults = state.loaded?.defaults || {};
  const fields = [
    ...BOOLEAN_OVERRIDE_FIELDS.map(([key, label]) => [key, label, "bool"]),
    ...INT_OVERRIDE_FIELDS,
  ];
  if (state.currentKind === "auto_detect") {
    fields.push(...DETECT_EXTRA_OVERRIDE_FIELDS);
  }

  els.overrideGrid.innerHTML = fields
    .map(([key, label, type]) => {
      const currentValue =
        rule.overrides?.[key] ??
        getDefaultOverrideValue(key, state.currentKind, defaults);
      const defaultValue = getDefaultOverrideValue(key, state.currentKind, defaults);
      const valueInput =
        type === "int"
          ? `<input class="text-input mono" type="number" min="0" value="${Number(currentValue ?? 0)}" data-override-value="${key}" />`
          : "";
      return `
        <div class="field">
          <span>${escapeHtml(label)}<span class="inline-hint"> ${TEXT.defaultPrefix}${escapeHtml(
            formatDefaultValue(defaultValue, type)
          )}</span></span>
          ${
            type === "bool"
              ? `<select class="text-input" data-override-bool="${key}">
                   <option value="true" ${currentValue === true ? "selected" : ""}>${TEXT.boolOn}</option>
                   <option value="false" ${currentValue === false ? "selected" : ""}>${TEXT.boolOff}</option>
                 </select>`
              : valueInput
          }
        </div>
      `;
    })
    .join("");

  for (const node of els.overrideGrid.querySelectorAll("[data-override-bool]")) {
    node.addEventListener("change", () => {
      const key = node.dataset.overrideBool;
      rule.overrides[key] = node.value === "true";
    });
  }

  for (const node of els.overrideGrid.querySelectorAll("[data-override-value]")) {
    node.addEventListener("input", () => {
      const key = node.dataset.overrideValue;
      rule.overrides[key] = Math.max(0, Number(node.value || 0));
    });
  }
}

function renderEntryList() {
  const rule = getCurrentRule();
  if (!rule) return;
  els.entryList.innerHTML = rule.entries
    .map(
      (entry, index) => {
        entry.summary = summarizeComponents(entry.components || []);
        return `
        <article class="entry-card ${state.currentEntryIndex === index ? "active" : ""}" data-entry-index="${index}">
          <div class="entry-card-head">
            <div class="entry-card-title">${TEXT.entryLabel} ${index + 1}</div>
            <div class="button-row">
              <button class="chip-button" type="button" data-entry-up="${index}">上移</button>
              <button class="chip-button" type="button" data-entry-down="${index}">下移</button>
              <button class="danger-button" type="button" data-entry-delete="${index}">删除</button>
            </div>
          </div>
          <div class="entry-card-meta">${escapeHtml(entry.summary)}</div>
        </article>
      `;
      }
    )
    .join("");

  for (const node of els.entryList.querySelectorAll("[data-entry-index]")) {
    node.addEventListener("click", (event) => {
      if (event.target.closest("[data-entry-up],[data-entry-down],[data-entry-delete]")) {
        return;
      }
      state.currentEntryIndex = Number(node.dataset.entryIndex);
      renderEntryList();
      renderComponentList();
    });
  }

  for (const node of els.entryList.querySelectorAll("[data-entry-up]")) {
    node.addEventListener("click", () => moveEntry(Number(node.dataset.entryUp), -1));
  }
  for (const node of els.entryList.querySelectorAll("[data-entry-down]")) {
    node.addEventListener("click", () => moveEntry(Number(node.dataset.entryDown), 1));
  }
  for (const node of els.entryList.querySelectorAll("[data-entry-delete]")) {
    node.addEventListener("click", () => deleteEntry(Number(node.dataset.entryDelete)));
  }
}

function moveEntry(index, offset) {
  const rule = getCurrentRule();
  if (!rule) return;
  const target = index + offset;
  if (target < 0 || target >= rule.entries.length) return;
  [rule.entries[index], rule.entries[target]] = [rule.entries[target], rule.entries[index]];
  state.currentEntryIndex = target;
  renderEntryList();
  renderComponentList();
}

async function deleteEntry(index) {
  const rule = getCurrentRule();
  if (!rule) return;
  if (rule.entries.length === 1) {
    setStatus(TEXT.keepOneEntry, "error", false);
    return;
  }
  rule.entries.splice(index, 1);
  if (state.currentEntryIndex >= rule.entries.length) {
    state.currentEntryIndex = rule.entries.length - 1;
  }
  try {
    await postDraft();
    setStatus("回复已删除", "success");
  } catch {
  }
}

function renderComponentBody(item, index) {
  if (item.type === "text") {
    return `<textarea class="text-area" rows="3" data-component-text="${index}">${escapeHtml(item.content || "")}</textarea>`;
  }
  if (item.type === "at") {
    return `<input class="text-input mono" type="text" value="${escapeHtml(item.qq || "")}" data-component-qq="${index}" />`;
  }
  if (item.type === "atall") {
    return `<div class="inline-hint">${TEXT.atAllHint}</div>`;
  }
  if (item.type === "face") {
    return `
      <div class="inline-hint">${TEXT.existingFaceHint}</div>
      <input class="text-input mono" type="number" min="0" value="${Number(item.id || 0)}" data-component-face="${index}" />
    `;
  }
  if (item.type === "forward") {
    return `<div class="inline-hint">聊天记录回复，仅支持通过引用消息导入</div>`;
  }
  if (["image", "record", "video"].includes(item.type)) {
    return `<div class="component-path">${escapeHtml(item.path || "")}</div>`;
  }
  return `<div class="inline-hint">${TEXT.unknownComponent}: ${escapeHtml(item.type || "unknown")}</div>`;
}

function renderComponentList() {
  const entry = getCurrentEntry();
  if (!entry) {
    els.componentList.innerHTML = "";
    return;
  }
  els.componentList.innerHTML = (entry.components || [])
    .map(
      (item, index) => `
      <div class="component-card">
        <div class="component-head">
          <span class="badge">${escapeHtml(item.type || "unknown")}</span>
          <div class="button-row">
            <button class="chip-button" type="button" data-component-up="${index}">上移</button>
            <button class="chip-button" type="button" data-component-down="${index}">下移</button>
            <button class="danger-button" type="button" data-component-delete="${index}">删除</button>
          </div>
        </div>
        <div class="component-body">${renderComponentBody(item, index)}</div>
      </div>
    `
    )
    .join("");

  for (const node of els.componentList.querySelectorAll("[data-component-text]")) {
    node.addEventListener("input", () => {
      entry.components[Number(node.dataset.componentText)].content = node.value;
      renderEntryList();
    });
  }
  for (const node of els.componentList.querySelectorAll("[data-component-qq]")) {
    node.addEventListener("input", () => {
      entry.components[Number(node.dataset.componentQq)].qq = node.value.trim();
      renderEntryList();
    });
  }
  for (const node of els.componentList.querySelectorAll("[data-component-face]")) {
    node.addEventListener("input", () => {
      entry.components[Number(node.dataset.componentFace)].id = Math.max(0, Number(node.value || 0));
      renderEntryList();
    });
  }
  for (const node of els.componentList.querySelectorAll("[data-component-up]")) {
    node.addEventListener("click", () => moveComponent(Number(node.dataset.componentUp), -1));
  }
  for (const node of els.componentList.querySelectorAll("[data-component-down]")) {
    node.addEventListener("click", () => moveComponent(Number(node.dataset.componentDown), 1));
  }
  for (const node of els.componentList.querySelectorAll("[data-component-delete]")) {
    node.addEventListener("click", () => {
      entry.components.splice(Number(node.dataset.componentDelete), 1);
      renderComponentList();
      renderEntryList();
    });
  }
}

function moveComponent(index, offset) {
  const entry = getCurrentEntry();
  if (!entry) return;
  const target = index + offset;
  if (target < 0 || target >= entry.components.length) return;
  [entry.components[index], entry.components[target]] = [entry.components[target], entry.components[index]];
  renderComponentList();
  renderEntryList();
}

function renderEditor() {
  const rule = getCurrentRule();
  if (!rule) {
    els.emptyState.classList.remove("hidden");
    els.editor.classList.add("hidden");
    return;
  }
  els.emptyState.classList.add("hidden");
  els.editor.classList.remove("hidden");
  els.editorEyebrow.textContent =
    state.currentKind === "command_triggered" ? TEXT.keywordTab : TEXT.detectTab;
  els.editorTitle.textContent = rule.keyword || TEXT.unnamedRule;
  els.keywordInput.value = rule.keyword || "";
  els.regexInput.checked = Boolean(rule.regex);
  els.scopeModeInput.value = !rule.enabled ? "disabled" : rule.mode || "whitelist";
  els.groupsInput.value = (rule.groups || []).join("\n");
  renderOverrideGrid();
  renderEntryList();
  renderComponentList();
}

function renderAll() {
  renderRuleList();
  renderEditor();
}

async function loadState() {
  const data = await bridge.apiGet("state");
  state.loaded = data;
  state.draft = {
    command_triggered: clone(data.command_triggered || []),
    auto_detect: clone(data.auto_detect || []),
  };
  if (state.currentRuleIndex >= getRules().length) {
    state.currentRuleIndex = getRules().length - 1;
  }
  renderAll();
}

async function postDraft() {
  const payload = {
    command_triggered: state.draft.command_triggered,
    auto_detect: state.draft.auto_detect,
  };
  setStatus(TEXT.saveLoading, "info", false);
  try {
    const response = await bridge.apiPost("save-all", payload);
    state.loaded = response;
    state.draft = {
      command_triggered: clone(response.command_triggered || []),
      auto_detect: clone(response.auto_detect || []),
    };
    renderAll();
    return response;
  } catch (error) {
    setStatus(error?.message || TEXT.saveFailed, "error", false);
    throw error;
  }
}

async function saveAll() {
  syncCurrentRule();
  await postDraft();
  setStatus(TEXT.saveSuccess, "success");
}

function createRule() {
  const rules = getRules();
  rules.push(makeEmptyRule(state.currentKind));
  state.currentRuleIndex = rules.length - 1;
  state.currentEntryIndex = 0;
  renderAll();
  setStatus(TEXT.createDraft, "info", true);
}

async function deleteCurrentRule() {
  const rules = getRules();
  if (state.currentRuleIndex < 0) return;
  syncCurrentRule();
  rules.splice(state.currentRuleIndex, 1);
  state.currentRuleIndex = Math.min(state.currentRuleIndex, rules.length - 1);
  state.currentEntryIndex = 0;
  try {
    await postDraft();
    setStatus("规则已删除", "success");
  } catch {
  }
}

function createEntry() {
  const rule = getCurrentRule();
  if (!rule) return;
  rule.entries.push(makeEmptyEntry());
  state.currentEntryIndex = rule.entries.length - 1;
  renderEntryList();
  renderComponentList();
}

function addComponent(type) {
  const entry = getCurrentEntry();
  if (!entry) return;
  if (type === "text") entry.components.push({ type: "text", content: "" });
  if (type === "at") entry.components.push({ type: "at", qq: "" });
  if (type === "atall") entry.components.push({ type: "atall" });
  renderComponentList();
  renderEntryList();
}

async function handleUpload() {
  const file = els.hiddenUploadInput.files?.[0];
  if (!file) return;
  setStatus(`正在上传 ${file.name}...`, "info", false);
  try {
    const response = await bridge.upload(`upload-media/${state.uploadType}`, file);
    const entry = getCurrentEntry();
    if (entry) {
      entry.components.push(response.item);
      renderComponentList();
      renderEntryList();
    }
    setStatus(`已添加媒体：${file.name}`, "success");
  } catch (error) {
    setStatus(error?.message || TEXT.uploadFailed, "error", false);
  } finally {
    els.hiddenUploadInput.value = "";
  }
}

function installEvents() {
  for (const node of document.querySelectorAll(".tab")) {
    node.addEventListener("click", () => {
      syncCurrentRule();
      state.currentKind = node.dataset.kind;
      state.currentRuleIndex = getRules(node.dataset.kind).length ? 0 : -1;
      state.currentEntryIndex = 0;
      for (const other of document.querySelectorAll(".tab")) {
        other.classList.toggle("active", other === node);
      }
      renderAll();
    });
  }

  els.searchInput.addEventListener("input", () => {
    state.search = els.searchInput.value;
    renderRuleList();
  });
  els.newRuleBtn.addEventListener("click", createRule);
  els.saveBtn.addEventListener("click", saveAll);
  els.deleteRuleBtn.addEventListener("click", deleteCurrentRule);
  els.newEntryBtn.addEventListener("click", createEntry);
  els.refreshBtn.addEventListener("click", async () => {
    setStatus(TEXT.refreshLoading, "info", false);
    await loadState();
    setStatus(TEXT.refreshSuccess, "success");
  });

  els.keywordInput.addEventListener("input", () => {
    syncCurrentRule();
    renderRuleList();
    els.editorTitle.textContent = els.keywordInput.value.trim() || TEXT.unnamedRule;
  });
  els.regexInput.addEventListener("change", syncCurrentRule);
  els.scopeModeInput.addEventListener("change", () => {
    syncCurrentRule();
    renderRuleList();
  });
  els.groupsInput.addEventListener("input", () => {
    syncCurrentRule();
    renderRuleList();
  });

  for (const node of document.querySelectorAll("[data-component]")) {
    node.addEventListener("click", () => addComponent(node.dataset.component));
  }
  for (const node of document.querySelectorAll(".upload-button")) {
    node.addEventListener("click", () => {
      state.uploadType = node.dataset.uploadType;
      els.hiddenUploadInput.click();
    });
  }
  els.hiddenUploadInput.addEventListener("change", handleUpload);
}

await bridge.ready();
installEvents();
await loadState();
