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
  saveLoading: "正在保存全部规则...",
  refreshLoading: "正在刷新...",
  refreshSuccess: "已刷新",
  createDraft: "已创建规则草稿",
  deleteDraft: "已放弃当前规则草稿",
  uploadFailed: "上传失败",
  saveFailed: "保存失败",
  keepOneEntry: "至少保留一条回复",
  atAllHint: "@全体成员",
  existingFaceHint: "已有 QQ 官方表情组件",
  unknownComponent: "未知组件类型",
  boolOn: "开启",
  boolOff: "关闭",
  unchanged: "保持不变",
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

const MEDIA_UPLOAD_RULES = {
  image: {
    accept: "image/*,.jpg,.jpeg,.png,.gif,.webp,.bmp",
    extensions: new Set([".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"]),
    label: "图片",
  },
  record: {
    accept: "audio/*,.amr,.mp3,.wav,.ogg,.oga,.m4a,.aac,.flac",
    extensions: new Set([".amr", ".mp3", ".wav", ".ogg", ".oga", ".m4a", ".aac", ".flac"]),
    label: "语音",
  },
  video: {
    accept: "video/*,.mp4,.webm,.mov,.m4v,.avi,.mkv",
    extensions: new Set([".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv"]),
    label: "视频",
  },
};

const state = {
  loaded: null,
  draft: null,
  currentKind: "command_triggered",
  currentRuleIndex: -1,
  currentEntryIndex: 0,
  search: "",
  selectionMode: false,
  selectedRuleIndices: new Set(),
  newRuleRefs: new Set(),
  draggedRuleIndex: -1,
  savedSnapshot: "",
  bulkRevert: {
    scope: new Map(),
    groups: new Map(),
    overrides: new Map(),
  },
  uploadType: "image",
  statusTimer: null,
};

const els = {
  refreshBtn: document.getElementById("refreshBtn"),
  searchInput: document.getElementById("searchInput"),
  newRuleBtn: document.getElementById("newRuleBtn"),
  selectionModeBtn: document.getElementById("selectionModeBtn"),
  selectFilteredBtn: document.getElementById("selectFilteredBtn"),
  listMeta: document.getElementById("listMeta"),
  ruleList: document.getElementById("ruleList"),
  emptyState: document.getElementById("emptyState"),
  editor: document.getElementById("editor"),
  normalEditorBody: document.getElementById("normalEditorBody"),
  bulkEditor: document.getElementById("bulkEditor"),
  bulkEditForm: document.getElementById("bulkEditForm"),
  bulkScopeModeInput: document.getElementById("bulkScopeModeInput"),
  bulkGroupsModeInput: document.getElementById("bulkGroupsModeInput"),
  bulkGroupsInput: document.getElementById("bulkGroupsInput"),
  bulkOverrideGrid: document.getElementById("bulkOverrideGrid"),
  editorEyebrow: document.getElementById("editorEyebrow"),
  editorTitle: document.getElementById("editorTitle"),
  dirtyState: document.getElementById("dirtyState"),
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

function hasOwn(target, key) {
  return Object.prototype.hasOwnProperty.call(target, key);
}

function snapshotProperty(target, key) {
  return {
    present: hasOwn(target, key),
    value: target[key] === undefined ? undefined : clone(target[key]),
  };
}

function restoreProperty(target, key, snapshot) {
  if (snapshot.present) {
    target[key] = snapshot.value === undefined ? undefined : clone(snapshot.value);
  } else {
    delete target[key];
  }
}

function clearBulkRevertState() {
  state.bulkRevert.scope.clear();
  state.bulkRevert.groups.clear();
  state.bulkRevert.overrides.clear();
}

function captureBulkScope(selectedRules) {
  for (const rule of selectedRules) {
    if (state.bulkRevert.scope.has(rule)) continue;
    state.bulkRevert.scope.set(rule, {
      enabled: snapshotProperty(rule, "enabled"),
      mode: snapshotProperty(rule, "mode"),
    });
  }
}

function restoreBulkScope(selectedRules) {
  for (const rule of selectedRules) {
    const snapshot = state.bulkRevert.scope.get(rule);
    if (!snapshot) continue;
    restoreProperty(rule, "enabled", snapshot.enabled);
    restoreProperty(rule, "mode", snapshot.mode);
  }
}

function captureBulkGroups(selectedRules) {
  for (const rule of selectedRules) {
    if (!state.bulkRevert.groups.has(rule)) {
      state.bulkRevert.groups.set(rule, snapshotProperty(rule, "groups"));
    }
  }
}

function restoreBulkGroups(selectedRules) {
  for (const rule of selectedRules) {
    const snapshot = state.bulkRevert.groups.get(rule);
    if (snapshot) restoreProperty(rule, "groups", snapshot);
  }
}

function captureBulkOverride(selectedRules, key) {
  if (!state.bulkRevert.overrides.has(key)) {
    state.bulkRevert.overrides.set(key, new Map());
  }
  const snapshots = state.bulkRevert.overrides.get(key);
  for (const rule of selectedRules) {
    if (snapshots.has(rule)) continue;
    const overrides = rule.overrides && typeof rule.overrides === "object" ? rule.overrides : {};
    snapshots.set(rule, {
      containerPresent: hasOwn(rule, "overrides"),
      field: snapshotProperty(overrides, key),
    });
  }
}

function restoreBulkOverride(selectedRules, key) {
  const snapshots = state.bulkRevert.overrides.get(key);
  if (!snapshots) return;
  for (const rule of selectedRules) {
    const snapshot = snapshots.get(rule);
    if (!snapshot) continue;
    if (!rule.overrides || typeof rule.overrides !== "object") {
      if (snapshot.containerPresent) rule.overrides = {};
      else continue;
    }
    restoreProperty(rule.overrides, key, snapshot.field);
    if (!snapshot.containerPresent && Object.keys(rule.overrides).length === 0) {
      delete rule.overrides;
    }
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

const ICON_PATHS = {
  up: '<path d="m6 14 6-6 6 6" />',
  down: '<path d="m6 10 6 6 6-6" />',
  trash:
    '<path d="M4 7h16" /><path d="M9 7V4h6v3" /><path d="M7 7l1 13h8l1-13" /><path d="M10 11v5M14 11v5" />',
  checkbox:
    '<rect x="5" y="5" width="14" height="14" rx="2" />',
  checkboxSome:
    '<rect x="5" y="5" width="14" height="14" rx="2" /><path d="M8 12h8" />',
  checkboxAll:
    '<rect x="5" y="5" width="14" height="14" rx="2" /><path d="m8.5 12 2.5 2.5 4.5-5" />',
};

function iconSvg(name) {
  return `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">${ICON_PATHS[name] || ""}</svg>`;
}

function iconButton(name, label, dataName, index, { danger = false, disabled = false } = {}) {
  return `
    <button
      class="${danger ? "danger-button" : "icon-button"} icon-action compact-icon-action"
      type="button"
      ${dataName}="${index}"
      aria-label="${label}"
      title="${label}"
      ${disabled ? "disabled" : ""}
    >
      ${iconSvg(name)}
      <span class="sr-only">${label}</span>
    </button>
  `;
}

function clearStatusTimer() {
  if (state.statusTimer) {
    window.clearTimeout(state.statusTimer);
    state.statusTimer = null;
  }
}

function withoutDerivedFields(value) {
  if (Array.isArray(value)) {
    return value.map(withoutDerivedFields);
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .filter(([key]) => key !== "summary" && key !== "__webuiNew")
        .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
        .map(([key, item]) => [key, withoutDerivedFields(item)])
    );
  }
  return value;
}

function draftSnapshot(value) {
  return JSON.stringify(
    withoutDerivedFields({
      command_triggered: value?.command_triggered || [],
      auto_detect: value?.auto_detect || [],
    })
  );
}

function hasUnsavedChanges() {
  if (!state.draft || !state.savedSnapshot) return false;
  return draftSnapshot(state.draft) !== state.savedSnapshot;
}

function renderDirtyState() {
  const dirty = hasUnsavedChanges();
  els.dirtyState.classList.toggle("hidden", !dirty);
  els.saveBtn.dataset.dirty = dirty ? "true" : "false";
  els.saveBtn.title = dirty ? "保存全部规则（有未保存修改）" : "保存全部规则";
  els.refreshBtn.title = dirty ? "重新载入（将放弃未保存修改）" : "重新载入";
}

function getTotalRuleCount() {
  return getRules("command_triggered").length + getRules("auto_detect").length;
}

function getSaveStatusMessage() {
  const count = getTotalRuleCount();
  return `已保存 ${count} 条规则`;
}

function getSaveLoadingMessage() {
  const count = getTotalRuleCount();
  return count > 1 ? `正在保存全部规则（共 ${count} 条）...` : "正在保存规则...";
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
  renderDirtyState();
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

function getSelectedRuleIndices() {
  const rules = getRules();
  return [...state.selectedRuleIndices]
    .filter((index) => Number.isInteger(index) && index >= 0 && index < rules.length)
    .sort((left, right) => left - right);
}

function getSelectedRules() {
  const rules = getRules();
  return getSelectedRuleIndices().map((index) => rules[index]);
}

function isRuleReorderable() {
  return !state.selectionMode && !state.search.trim();
}

function renderSelectionActions(filteredRules) {
  const filteredIndices = filteredRules.map(({ index }) => index);
  const allSelected =
    filteredIndices.length > 0 && filteredIndices.every((index) => state.selectedRuleIndices.has(index));
  const someSelected = filteredIndices.some((index) => state.selectedRuleIndices.has(index));
  const actionLabel = allSelected ? "取消选择当前结果" : "全选当前结果";
  els.newRuleBtn.classList.toggle("hidden", state.selectionMode);
  els.selectFilteredBtn.classList.toggle("hidden", !state.selectionMode);
  els.selectFilteredBtn.disabled = filteredIndices.length === 0;
  const iconState = allSelected ? "checkboxAll" : someSelected ? "checkboxSome" : "checkbox";
  els.selectFilteredBtn.innerHTML = `${iconSvg(iconState)}<span class="sr-only">${actionLabel}</span>`;
  els.selectFilteredBtn.setAttribute("aria-label", actionLabel);
  els.selectFilteredBtn.title = actionLabel;
  els.selectionModeBtn.classList.toggle("active", state.selectionMode);
  els.selectionModeBtn.setAttribute("aria-pressed", String(state.selectionMode));
  els.selectionModeBtn.setAttribute("aria-label", state.selectionMode ? "退出选择模式" : "选择规则");
  els.selectionModeBtn.querySelector(".sr-only").textContent = state.selectionMode
    ? "退出选择模式"
    : "选择规则";
  els.selectionModeBtn.title = state.selectionMode ? "退出选择模式" : "选择规则";
}

function refreshSelectionView() {
  renderRuleList();
  renderEditor();
  renderDirtyState();
}

function toggleRuleSelection(index) {
  if (state.selectedRuleIndices.has(index)) {
    state.selectedRuleIndices.delete(index);
  } else {
    state.selectedRuleIndices.add(index);
  }
  refreshSelectionView();
}

function selectFilteredRules() {
  const filteredIndices = filterRules(getRules()).map(({ index }) => index);
  const allSelected =
    filteredIndices.length > 0 && filteredIndices.every((index) => state.selectedRuleIndices.has(index));
  for (const index of filteredIndices) {
    if (allSelected) {
      state.selectedRuleIndices.delete(index);
    } else {
      state.selectedRuleIndices.add(index);
    }
  }
  refreshSelectionView();
}

function setSelectionMode(enabled) {
  if (state.selectionMode === enabled) return;
  if (enabled) {
    syncCurrentRule();
  }
  state.selectionMode = enabled;
  state.selectedRuleIndices.clear();
  clearBulkRevertState();
  refreshSelectionView();
}

function remapRuleState(rule, selectedRules) {
  const rules = getRules();
  state.currentRuleIndex = rule ? rules.indexOf(rule) : -1;
  state.selectedRuleIndices = new Set(
    selectedRules
      .map((selectedRule) => rules.indexOf(selectedRule))
      .filter((index) => index >= 0)
  );
}

function getPersistableRuleOrder(kind = state.currentKind) {
  const draftRules = getRules(kind);
  const savedRules = state.loaded?.[kind] || [];
  if (draftRules.length !== savedRules.length) return null;

  const draftKeywords = draftRules.map((rule) => String(rule.keyword || "").trim());
  const savedKeywords = savedRules.map((rule) => String(rule.keyword || "").trim());
  if (
    draftKeywords.some((keyword) => !keyword) ||
    new Set(draftKeywords).size !== draftKeywords.length ||
    new Set(draftKeywords).size !== new Set(savedKeywords).size ||
    draftKeywords.some((keyword) => !savedKeywords.includes(keyword))
  ) {
    return null;
  }
  return draftKeywords;
}

function updateSavedRuleOrder(kind, keywords) {
  const loadedRules = state.loaded?.[kind] || [];
  const loadedByKeyword = new Map(
    loadedRules.map((rule) => [String(rule.keyword || "").trim(), rule])
  );
  state.loaded[kind] = keywords.map((keyword) => loadedByKeyword.get(keyword));

  try {
    const saved = JSON.parse(state.savedSnapshot);
    const savedRules = saved[kind] || [];
    const savedByKeyword = new Map(
      savedRules.map((rule) => [String(rule.keyword || "").trim(), rule])
    );
    saved[kind] = keywords.map((keyword) => savedByKeyword.get(keyword));
    state.savedSnapshot = draftSnapshot(saved);
  } catch {
    // Keep the existing snapshot if it cannot be adjusted safely.
  }
}

async function persistRuleOrder(kind, keywords) {
  try {
    const response = await bridge.apiPost("reorder", { kind, keywords });
    if (response?.status === "error" || response?.ok !== true) {
      throw new Error(response?.message || "保存排序失败，请刷新后重试");
    }
    updateSavedRuleOrder(kind, keywords);
    renderDirtyState();
    setStatus("规则顺序已保存", "success");
    return true;
  } catch (error) {
    setStatus(error?.message || "保存排序失败，请刷新后重试", "error", false);
    return false;
  }
}

async function moveRule(fromIndex, insertionIndex) {
  const rules = getRules();
  if (
    fromIndex < 0 ||
    fromIndex >= rules.length ||
    insertionIndex < 0 ||
    insertionIndex > rules.length
  ) {
    return;
  }

  syncCurrentRule();
  const previousOrder = rules.slice();
  const currentRule = getCurrentRule();
  const selectedRules = getSelectedRules();
  const [movedRule] = rules.splice(fromIndex, 1);
  if (fromIndex < insertionIndex) insertionIndex -= 1;
  if (insertionIndex === fromIndex) {
    rules.splice(fromIndex, 0, movedRule);
    return;
  }
  rules.splice(insertionIndex, 0, movedRule);
  remapRuleState(currentRule, selectedRules);
  renderAll();

  const keywords = getPersistableRuleOrder();
  if (!keywords) {
    setStatus("顺序已调整；请先保存新增、删除或关键词名称修改", "info", false);
    return;
  }
  if (!(await persistRuleOrder(state.currentKind, keywords))) {
    rules.splice(0, rules.length, ...previousOrder);
    remapRuleState(currentRule, selectedRules);
    renderAll();
  }
}

function clearRuleDragState() {
  state.draggedRuleIndex = -1;
  for (const node of els.ruleList.querySelectorAll(".dragging, .drag-over")) {
    node.classList.remove("dragging", "drag-over");
  }
}

function renderRuleList() {
  const rules = getRules();
  const filtered = filterRules(rules);
  const label = state.currentKind === "command_triggered" ? TEXT.keywordTab : TEXT.detectTab;
  els.listMeta.textContent = state.selectionMode
    ? `已选择 ${getSelectedRuleIndices().length} 条`
    : `${label} ${filtered.length} 条`;
  renderSelectionActions(filtered);
  const reorderable = isRuleReorderable();
  els.ruleList.innerHTML = filtered
    .map(
      ({ rule, index }) => `
      <article
        class="rule-card ${state.currentRuleIndex === index ? "active" : ""} ${
          state.selectedRuleIndices.has(index) ? "selected" : ""
        } ${reorderable ? "reorderable" : ""}"
        data-rule-index="${index}"
        draggable="${reorderable}"
      >
        <div class="rule-card-head">
          <div class="rule-card-leading">
            ${
              state.selectionMode
                ? `<input class="rule-select" type="checkbox" data-rule-select="${index}" ${
                    state.selectedRuleIndices.has(index) ? "checked" : ""
                  } aria-label="选择规则 ${escapeHtml(rule.keyword || TEXT.unnamedRule)}" />`
                : ""
            }
            <div class="rule-card-title">${escapeHtml(rule.keyword || TEXT.unnamedRule)}</div>
          </div>
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
    node.addEventListener("click", (event) => {
      const index = Number(node.dataset.ruleIndex);
      if (state.selectionMode) {
        if (event.target.closest("[data-rule-select]")) return;
        toggleRuleSelection(index);
        return;
      }
      syncCurrentRule();
      state.currentRuleIndex = index;
      state.currentEntryIndex = 0;
      renderAll();
    });
  }

  for (const node of els.ruleList.querySelectorAll("[data-rule-select]")) {
    node.addEventListener("change", () => toggleRuleSelection(Number(node.dataset.ruleSelect)));
  }

  if (!reorderable) return;
  for (const node of els.ruleList.querySelectorAll("[data-rule-index]")) {
    node.addEventListener("dragstart", (event) => {
      state.draggedRuleIndex = Number(node.dataset.ruleIndex);
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", String(state.draggedRuleIndex));
      node.classList.add("dragging");
    });
    node.addEventListener("dragend", clearRuleDragState);
  }
  for (const node of els.ruleList.querySelectorAll("[data-rule-index]")) {
    node.addEventListener("dragover", (event) => {
      if (state.draggedRuleIndex < 0) return;
      event.preventDefault();
      node.classList.add("drag-over");
      event.dataTransfer.dropEffect = "move";
    });
    node.addEventListener("dragleave", () => node.classList.remove("drag-over"));
    node.addEventListener("drop", (event) => {
      event.preventDefault();
      const targetIndex = Number(node.dataset.ruleIndex);
      const before = event.clientY < node.getBoundingClientRect().top + node.offsetHeight / 2;
      const insertionIndex = targetIndex + (before ? 0 : 1);
      const fromIndex = state.draggedRuleIndex;
      clearRuleDragState();
      void moveRule(fromIndex, insertionIndex);
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

function getOverrideFields(kind) {
  const fields = [
    ...BOOLEAN_OVERRIDE_FIELDS.map(([key, label]) => [key, label, "bool"]),
    ...INT_OVERRIDE_FIELDS,
  ];
  if (kind === "auto_detect") {
    fields.push(...DETECT_EXTRA_OVERRIDE_FIELDS);
  }
  return fields;
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
  const fields = getOverrideFields(state.currentKind);

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
      renderDirtyState();
    });
  }

  for (const node of els.overrideGrid.querySelectorAll("[data-override-value]")) {
    node.addEventListener("input", () => {
      const key = node.dataset.overrideValue;
      rule.overrides[key] = Math.max(0, Number(node.value || 0));
      renderDirtyState();
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
              ${iconButton("up", "上移回复", "data-entry-up", index, { disabled: index === 0 })}
              ${iconButton("down", "下移回复", "data-entry-down", index, {
                disabled: index === rule.entries.length - 1,
              })}
              ${iconButton("trash", "删除回复", "data-entry-delete", index, { danger: true })}
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
  renderDirtyState();
}

async function deleteEntry(index) {
  const rule = getCurrentRule();
  if (!rule) return;
  if (rule.entries.length === 1) {
    setStatus(TEXT.keepOneEntry, "error", false);
    return;
  }
  if (!window.confirm("确定删除这条回复吗？")) return;
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

function renderBulkEditor() {
  const selectedRules = getSelectedRules();
  els.bulkEditForm.classList.toggle("hidden", selectedRules.length === 0);
  if (!selectedRules.length) return;

  els.bulkScopeModeInput.value = "unchanged";
  els.bulkGroupsModeInput.value = "unchanged";
  els.bulkGroupsInput.value = "";
  els.bulkGroupsInput.disabled = true;

  els.bulkOverrideGrid.innerHTML = getOverrideFields(state.currentKind)
    .map(([key, label, type]) => {
      if (type === "int") {
        return `
          <label class="field">
            <span>${escapeHtml(label)}</span>
            <input
              class="text-input mono"
              type="number"
              min="0"
              placeholder="${TEXT.unchanged}"
              data-bulk-override-value="${key}"
            />
          </label>
        `;
      }
      return `
        <label class="field">
          <span>${escapeHtml(label)}</span>
          <select class="text-input" data-bulk-override-bool="${key}">
            <option value="unchanged">${TEXT.unchanged}</option>
            <option value="true">${TEXT.boolOn}</option>
            <option value="false">${TEXT.boolOff}</option>
          </select>
        </label>
      `;
    })
    .join("");

  for (const node of els.bulkOverrideGrid.querySelectorAll("[data-bulk-override-bool]")) {
    node.addEventListener("change", () => {
      applyBulkOverride(node.dataset.bulkOverrideBool, node.value);
    });
  }
  for (const node of els.bulkOverrideGrid.querySelectorAll("[data-bulk-override-value]")) {
    node.addEventListener("change", () => {
      applyBulkOverride(node.dataset.bulkOverrideValue, node.value);
    });
  }
}

function refreshBulkDraftView() {
  renderRuleList();
  renderDirtyState();
}

function applyBulkScopeMode() {
  const selectedRules = getSelectedRules();
  if (!selectedRules.length) return;

  const scopeMode = els.bulkScopeModeInput.value;
  if (scopeMode === "unchanged") {
    restoreBulkScope(selectedRules);
    refreshBulkDraftView();
    return;
  }
  captureBulkScope(selectedRules);
  for (const rule of selectedRules) {
    if (scopeMode === "disabled") {
      rule.enabled = false;
      rule.mode = "whitelist";
    } else {
      rule.enabled = true;
      rule.mode = scopeMode;
    }
  }
  refreshBulkDraftView();
}

function applyBulkGroups() {
  const selectedRules = getSelectedRules();
  if (!selectedRules.length) return;
  const groupsMode = els.bulkGroupsModeInput.value;
  if (groupsMode === "unchanged") {
    restoreBulkGroups(selectedRules);
  } else if (groupsMode === "set") {
    captureBulkGroups(selectedRules);
    const groups = parseGroupInput(els.bulkGroupsInput.value);
    for (const rule of selectedRules) rule.groups = [...groups];
  } else if (groupsMode === "clear") {
    captureBulkGroups(selectedRules);
    for (const rule of selectedRules) rule.groups = [];
  } else {
    return;
  }
  refreshBulkDraftView();
}

function applyBulkOverride(key, value) {
  const selectedRules = getSelectedRules();
  if (!selectedRules.length) return;
  if (value === "unchanged" || value === "") {
    restoreBulkOverride(selectedRules, key);
    refreshBulkDraftView();
    return;
  }
  const field = getOverrideFields(state.currentKind).find(([fieldKey]) => fieldKey === key);
  if (!field) return;
  const [, , type] = field;
  captureBulkOverride(selectedRules, key);
  if (type === "int") {
    const numericValue = Number(value);
    if (!Number.isFinite(numericValue)) return;
    for (const rule of selectedRules) {
      rule.overrides ||= {};
      rule.overrides[key] = Math.max(0, numericValue);
    }
  } else {
    for (const rule of selectedRules) {
      rule.overrides ||= {};
      rule.overrides[key] = value === "true";
    }
  }
  refreshBulkDraftView();
}

function buildMediaEndpoint(type, path) {
  const pathParts = String(path || "")
    .replaceAll("\\", "/")
    .split("/")
    .filter(Boolean);
  return ["media", String(type || "").trim(), ...pathParts].join("/");
}

function showMediaPreviewError(container, message = "无法预览此媒体，可尝试下载。") {
  container.querySelector("[data-media-loading]")?.classList.add("hidden");
  container.querySelector("[data-media-preview]")?.classList.add("hidden");
  const error = container.querySelector("[data-media-error]");
  if (!error) return;
  error.textContent = message;
  error.classList.remove("hidden");
}

async function loadMediaPreview(container) {
  if (container.dataset.mediaPreviewState) return;
  container.dataset.mediaPreviewState = "loading";
  const type = container.dataset.mediaType || "";
  const path = container.dataset.mediaPath || "";
  try {
    const response = await bridge.apiGet("media-preview", { type, path });
    if (!response?.url) {
      showMediaPreviewError(container, response?.message);
      container.dataset.mediaPreviewState = "error";
      return;
    }
    const preview = container.querySelector("[data-media-preview]");
    if (!preview) return;
    preview.src = response.url;
    preview.classList.remove("hidden");
    container.querySelector("[data-media-loading]")?.classList.add("hidden");
    container.dataset.mediaPreviewState = "ready";
  } catch {
    showMediaPreviewError(container);
    container.dataset.mediaPreviewState = "error";
  }
}

async function downloadMedia(node) {
  const type = node.dataset.mediaType || "";
  const path = node.dataset.mediaPath || "";
  if (!type || !path) return;
  const fileName = path.replaceAll("\\", "/").split("/").filter(Boolean).pop() || "media.bin";
  try {
    setStatus(`正在下载 ${fileName}...`, "info", false);
    await bridge.download(buildMediaEndpoint(type, path), {}, fileName);
    setStatus("媒体下载已开始", "success");
  } catch (error) {
    setStatus(error?.message || "下载失败", "error", false);
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
    const path = escapeHtml(item.path || "");
    const mediaType = escapeHtml(item.type);
    let preview = "";
    if (item.type === "image") {
      preview = `<img class="hidden" alt="${path}" data-media-preview />`;
    } else if (item.type === "record") {
      preview = `<audio class="hidden" controls preload="metadata" data-media-preview></audio>`;
    } else {
      preview = `<video class="hidden" controls preload="metadata" data-media-preview></video>`;
    }
    return `
      <div class="media-preview" data-media-container data-media-type="${mediaType}" data-media-path="${path}">
        ${preview}
        <div class="media-preview-loading" data-media-loading>正在加载预览...</div>
        <div class="media-preview-error hidden" data-media-error>无法预览此媒体，可尝试下载。</div>
      </div>
      <div class="media-actions">
        <div class="component-path">${path}</div>
        <button
          class="media-download"
          type="button"
          data-media-download
          data-media-type="${mediaType}"
          data-media-path="${path}"
          title="下载媒体"
        >下载</button>
      </div>
    `;
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
            ${iconButton("up", "上移组件", "data-component-up", index, { disabled: index === 0 })}
            ${iconButton("down", "下移组件", "data-component-down", index, {
              disabled: index === entry.components.length - 1,
            })}
            ${iconButton("trash", "删除组件", "data-component-delete", index, { danger: true })}
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
      renderDirtyState();
    });
  }
  for (const node of els.componentList.querySelectorAll("[data-component-qq]")) {
    node.addEventListener("input", () => {
      entry.components[Number(node.dataset.componentQq)].qq = node.value.trim();
      renderEntryList();
      renderDirtyState();
    });
  }
  for (const node of els.componentList.querySelectorAll("[data-component-face]")) {
    node.addEventListener("input", () => {
      entry.components[Number(node.dataset.componentFace)].id = Math.max(0, Number(node.value || 0));
      renderEntryList();
      renderDirtyState();
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
      renderDirtyState();
    });
  }
  for (const node of els.componentList.querySelectorAll("[data-media-preview]")) {
    node.addEventListener("error", () => {
      const container = node.closest("[data-media-container]");
      if (container) showMediaPreviewError(container);
    });
  }
  for (const node of els.componentList.querySelectorAll("[data-media-container]")) {
    loadMediaPreview(node);
  }
  for (const node of els.componentList.querySelectorAll("[data-media-download]")) {
    node.addEventListener("click", () => downloadMedia(node));
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
  renderDirtyState();
}

function renderEditor() {
  if (state.selectionMode) {
    els.emptyState.classList.add("hidden");
    els.editor.classList.remove("hidden");
    els.normalEditorBody.classList.add("hidden");
    els.bulkEditor.classList.remove("hidden");
    els.editorEyebrow.textContent = "选择模式";
    els.editorTitle.textContent = "批量修改属性";
    els.deleteRuleBtn.classList.remove("hidden");
    els.deleteRuleBtn.setAttribute("aria-label", "删除已选规则");
    els.deleteRuleBtn.title = "删除已选规则";
    renderBulkEditor();
    return;
  }

  els.normalEditorBody.classList.remove("hidden");
  els.bulkEditor.classList.add("hidden");
  els.deleteRuleBtn.classList.remove("hidden");
  els.deleteRuleBtn.setAttribute("aria-label", "删除当前规则");
  els.deleteRuleBtn.title = "删除当前规则";
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
  renderDirtyState();
}

async function loadState() {
  const data = await bridge.apiGet("state");
  state.selectionMode = false;
  state.selectedRuleIndices.clear();
  state.newRuleRefs.clear();
  state.draggedRuleIndex = -1;
  clearBulkRevertState();
  state.loaded = data;
  state.draft = {
    command_triggered: clone(data.command_triggered || []),
    auto_detect: clone(data.auto_detect || []),
  };
  state.savedSnapshot = draftSnapshot(state.draft);
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
  setStatus(getSaveLoadingMessage(), "info", false);
  try {
    const response = await bridge.apiPost("save-all", payload);
    state.loaded = response;
    state.draft = {
      command_triggered: clone(response.command_triggered || []),
      auto_detect: clone(response.auto_detect || []),
    };
    state.newRuleRefs.clear();
    state.savedSnapshot = draftSnapshot(state.draft);
    clearBulkRevertState();
    renderAll();
    return response;
  } catch (error) {
    setStatus(error?.message || TEXT.saveFailed, "error", false);
    throw error;
  }
}

async function saveAll() {
  if (!state.selectionMode) syncCurrentRule();
  await postDraft();
  setStatus(getSaveStatusMessage(), "success");
}

function createRule() {
  if (state.selectionMode) {
    state.selectionMode = false;
    state.selectedRuleIndices.clear();
  }
  const rules = getRules();
  const rule = makeEmptyRule(state.currentKind);
  rule.__webuiNew = true;
  rules.push(rule);
  state.newRuleRefs.add(rule);
  state.currentRuleIndex = rules.length - 1;
  state.currentEntryIndex = 0;
  renderAll();
  setStatus(TEXT.createDraft, "info", true);
}

async function deleteCurrentRule() {
  if (state.selectionMode) {
    await deleteSelectedRules();
    return;
  }
  const rules = getRules();
  if (state.currentRuleIndex < 0) return;
  const rule = getCurrentRule();
  if (!rule) return;
  if (state.newRuleRefs.has(rule) || rule.__webuiNew) {
    syncCurrentRule();
    rules.splice(state.currentRuleIndex, 1);
    state.newRuleRefs.delete(rule);
    state.currentRuleIndex = Math.min(state.currentRuleIndex, rules.length - 1);
    state.currentEntryIndex = 0;
    renderAll();
    setStatus(TEXT.deleteDraft, "success");
    return;
  }
  if (!window.confirm("确定删除当前规则吗？此操作会立即保存。")) return;
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

async function deleteSelectedRules() {
  const rules = getRules();
  const indices = getSelectedRuleIndices();
  if (!indices.length) {
    setStatus("请先选择要删除的规则", "error", false);
    return;
  }
  if (!window.confirm(`确定删除选中的 ${indices.length} 条规则吗？此操作会立即保存。`)) return;

  const selectedRules = indices.map((index) => rules[index]);
  const currentRule = getCurrentRule();
  for (const index of [...indices].sort((left, right) => right - left)) {
    rules.splice(index, 1);
  }
  state.selectionMode = false;
  state.selectedRuleIndices.clear();
  state.currentRuleIndex = selectedRules.includes(currentRule)
    ? Math.min(state.currentRuleIndex, rules.length - 1)
    : rules.indexOf(currentRule);
  state.currentEntryIndex = 0;
  try {
    await postDraft();
    setStatus(`已删除 ${indices.length} 条规则`, "success");
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
  renderDirtyState();
}

function addComponent(type) {
  const entry = getCurrentEntry();
  if (!entry) return;
  if (type === "text") entry.components.push({ type: "text", content: "" });
  if (type === "at") entry.components.push({ type: "at", qq: "" });
  if (type === "atall") entry.components.push({ type: "atall" });
  renderComponentList();
  renderEntryList();
  renderDirtyState();
}

async function handleUpload() {
  const file = els.hiddenUploadInput.files?.[0];
  if (!file) return;
  const uploadRule = MEDIA_UPLOAD_RULES[state.uploadType];
  const extension = `.${file.name.split(".").pop()?.toLowerCase() || ""}`;
  if (!uploadRule || !uploadRule.extensions.has(extension)) {
    setStatus(`请选择有效的${uploadRule?.label || "媒体"}文件`, "error", false);
    els.hiddenUploadInput.value = "";
    return;
  }
  setStatus(`正在上传 ${file.name}...`, "info", false);
  try {
    const response = await bridge.upload(`upload-media/${state.uploadType}`, file);
    const entry = getCurrentEntry();
    if (entry) {
      entry.components.push(response.item);
      renderComponentList();
      renderEntryList();
      renderDirtyState();
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
      if (!state.selectionMode) syncCurrentRule();
      state.selectionMode = false;
      state.selectedRuleIndices.clear();
      clearBulkRevertState();
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
  els.selectionModeBtn.addEventListener("click", () => setSelectionMode(!state.selectionMode));
  els.selectFilteredBtn.addEventListener("click", selectFilteredRules);
  els.bulkScopeModeInput.addEventListener("change", applyBulkScopeMode);
  els.bulkGroupsModeInput.addEventListener("change", () => {
    els.bulkGroupsInput.disabled = els.bulkGroupsModeInput.value !== "set";
    if (els.bulkGroupsModeInput.value !== "set") els.bulkGroupsInput.value = "";
    if (["unchanged", "clear"].includes(els.bulkGroupsModeInput.value)) applyBulkGroups();
    if (els.bulkGroupsModeInput.value === "set" && els.bulkGroupsInput.value.trim()) {
      applyBulkGroups();
    }
  });
  els.bulkGroupsInput.addEventListener("input", applyBulkGroups);
  els.saveBtn.addEventListener("click", saveAll);
  els.deleteRuleBtn.addEventListener("click", deleteCurrentRule);
  els.newEntryBtn.addEventListener("click", createEntry);
  els.refreshBtn.addEventListener("click", async () => {
    if (hasUnsavedChanges() && !window.confirm("重新载入会放弃未保存修改，确定继续吗？")) {
      return;
    }
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
      els.hiddenUploadInput.accept = MEDIA_UPLOAD_RULES[state.uploadType]?.accept || "";
      els.hiddenUploadInput.click();
    });
  }
  els.hiddenUploadInput.addEventListener("change", handleUpload);
}

await bridge.ready();
installEvents();
await loadState();
