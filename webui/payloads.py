from __future__ import annotations

import re
from typing import Any


BOOL_OVERRIDE_FIELDS = (
    ("quote_reply", "quote_reply_override"),
    ("qq_forward_all_replies", "qq_forward_all_replies_override"),
)

KEYWORD_OVERRIDE_FIELDS = BOOL_OVERRIDE_FIELDS + (
    ("case_sensitive", "case_sensitive_override"),
    ("recall_delay", "recall_delay_override"),
)

DETECT_OVERRIDE_FIELDS = KEYWORD_OVERRIDE_FIELDS + (
    ("cooldown", "cooldown_override"),
    (
        "ignore_cooldown_on_exact_match",
        "ignore_cooldown_on_exact_match_override",
    ),
)


def _parse_recall_delay_config(raw: Any) -> tuple[int, int]:
    parts = str(raw or "0 0").split()
    keyword_delay = _safe_int(parts[0]) if len(parts) > 0 else 0
    detect_delay = _safe_int(parts[1]) if len(parts) > 1 else 0
    return max(0, keyword_delay), max(0, detect_delay)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clean_group_ids(groups: Any) -> list[str]:
    normalized: list[str] = []
    values: list[Any]
    if isinstance(groups, str):
        values = re.split(r"[\s,，、;；]+", groups)
    else:
        values = list(groups or [])
    for group_id in values:
        text = str(group_id or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _build_component_list(entry: dict[str, Any]) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    text = str(entry.get("text", "") or "")
    if text:
        components.append({"type": "text", "content": text})

    for at in entry.get("ats", []) or []:
        if at.get("all"):
            components.append({"type": "atall"})
            continue
        qq = str(at.get("qq", "") or "").strip()
        if qq:
            components.append({"type": "at", "qq": qq})

    for face in entry.get("faces", []) or []:
        face_id = _safe_int(face.get("id"), -1)
        if face_id >= 0:
            components.append({"type": "face", "id": face_id})

    for media_type in ("images", "records", "videos"):
        component_type = media_type[:-1]
        for item in entry.get(media_type, []) or []:
            path = str(item.get("path", "") or "").strip()
            if path:
                components.append({"type": component_type, "path": path})

    for item in entry.get("forwards", []) or []:
        forward_id = str(item.get("id", "") or "").strip()
        if forward_id:
            components.append({"type": "forward", "id": forward_id})

    return components


def _build_entry_payload(entry: dict[str, Any]) -> dict[str, Any]:
    components = _build_component_list(entry)
    return {
        "components": components,
        "summary": summarize_components(components),
    }


def summarize_components(components: list[dict[str, Any]]) -> str:
    text_value = ""
    image_count = 0
    record_count = 0
    video_count = 0
    at_count = 0
    face_count = 0
    forward_count = 0

    for item in components:
        item_type = item.get("type")
        if item_type == "text" and not text_value:
            text_value = str(item.get("content", "") or "").replace("\n", " ").strip()
        elif item_type in {"at", "atall"}:
            at_count += 1
        elif item_type == "face":
            face_count += 1
        elif item_type == "image":
            image_count += 1
        elif item_type == "record":
            record_count += 1
        elif item_type == "video":
            video_count += 1
        elif item_type == "forward":
            forward_count += 1

    summary = text_value[:36]
    if len(text_value) > 36:
        summary += "..."

    tags: list[str] = []
    if image_count:
        tags.append(f"[图片 x{image_count}]")
    if record_count:
        tags.append(f"[语音 x{record_count}]")
    if video_count:
        tags.append(f"[视频 x{video_count}]")
    if at_count:
        tags.append(f"[@ x{at_count}]")
    if face_count:
        tags.append(f"[表情 x{face_count}]")
    if forward_count:
        tags.append(f"[聊天记录 x{forward_count}]")

    if summary:
        return f"{summary}{''.join(tags)}"
    if tags:
        return "".join(tags)
    return "(空回复)"


def _serialize_override_value(
    plugin: Any,
    rule: dict[str, Any],
    kind: str,
    field_name: str,
    stored_name: str,
) -> Any:
    if field_name == "recall_delay":
        return get_effective_recall_delay(plugin, rule, kind)
    if field_name == "cooldown":
        return get_effective_int(plugin, rule, stored_name, field_name)
    return get_effective_bool(plugin, rule, stored_name, field_name)


def _serialize_rule(plugin: Any, rule: dict[str, Any], kind: str) -> dict[str, Any]:
    overrides = {}
    field_mapping = KEYWORD_OVERRIDE_FIELDS if kind == "command_triggered" else DETECT_OVERRIDE_FIELDS
    for field_name, stored_name in field_mapping:
        overrides[field_name] = _serialize_override_value(
            plugin, rule, kind, field_name, stored_name
        )

    return {
        "keyword": str(rule.get("keyword", "") or ""),
        "regex": bool(rule.get("regex", False)),
        "enabled": bool(rule.get("enabled", True)),
        "mode": str(rule.get("mode", "whitelist") or "whitelist"),
        "groups": _clean_group_ids(rule.get("groups", [])),
        "entries": [_build_entry_payload(entry) for entry in rule.get("entries", []) or []],
        "overrides": overrides,
    }


def build_plugin_state_payload(plugin: Any) -> dict[str, Any]:
    keyword_delay, detect_delay = _parse_recall_delay_config(
        plugin.config.get("recall_delay", "0 0")
    )
    return {
        "command_triggered": [
            _serialize_rule(plugin, rule, "command_triggered")
            for rule in plugin.data.get("command_triggered", [])
        ],
        "auto_detect": [
            _serialize_rule(plugin, rule, "auto_detect")
            for rule in plugin.data.get("auto_detect", [])
        ],
        "defaults": {
            "quote_reply": bool(plugin.config.get("quote_reply", False)),
            "qq_forward_all_replies": bool(
                plugin.config.get("qq_forward_all_replies", False)
            ),
            "keyword_recall_delay": keyword_delay,
            "detect_recall_delay": detect_delay,
            "case_sensitive": bool(plugin.config.get("case_sensitive", False)),
            "cooldown": max(0, _safe_int(plugin.config.get("cooldown", 0))),
            "ignore_cooldown_on_exact_match": bool(
                plugin.config.get("ignore_cooldown_on_exact_match", False)
            ),
            "enable_text_template": bool(
                plugin.config.get("enable_text_template", True)
            ),
        },
    }


def _sanitize_components(components: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for item in components or []:
        item_type = str(item.get("type", "") or "").strip().lower()
        if item_type == "text":
            content = str(item.get("content", "") or "")
            sanitized.append({"type": "text", "content": content})
        elif item_type == "at":
            qq = str(item.get("qq", "") or "").strip()
            if qq:
                sanitized.append({"type": "at", "qq": qq})
        elif item_type == "atall":
            sanitized.append({"type": "atall"})
        elif item_type == "face":
            face_id = _safe_int(item.get("id"), -1)
            if face_id >= 0:
                sanitized.append({"type": "face", "id": face_id})
        elif item_type in {"image", "record", "video"}:
            path = str(item.get("path", "") or "").strip()
            if path and not path.startswith(("..", "/", "\\")):
                sanitized.append({"type": item_type, "path": path})
        elif item_type == "forward":
            forward_id = str(item.get("id", "") or "").strip()
            if forward_id.isdigit():
                sanitized.append({"type": "forward", "id": forward_id})
    return sanitized


def _components_to_entry(components: list[dict[str, Any]]) -> dict[str, Any]:
    entry = {
        "text": "",
        "images": [],
        "records": [],
        "videos": [],
        "ats": [],
        "faces": [],
        "forwards": [],
    }

    text_parts: list[str] = []
    for item in components:
        item_type = item["type"]
        if item_type == "text":
            text_parts.append(str(item.get("content", "")))
        elif item_type == "at":
            entry["ats"].append({"qq": str(item.get("qq", "") or ""), "all": False})
        elif item_type == "atall":
            entry["ats"].append({"qq": "all", "all": True})
        elif item_type == "face":
            entry["faces"].append({"id": _safe_int(item.get("id"))})
        elif item_type == "image":
            entry["images"].append({"path": item["path"]})
        elif item_type == "record":
            entry["records"].append({"path": item["path"]})
        elif item_type == "video":
            entry["videos"].append({"path": item["path"]})
        elif item_type == "forward":
            entry["forwards"].append({"id": item["id"]})

    entry["text"] = "".join(text_parts).strip()
    return entry


def _sanitize_override_value(raw_value: Any, *, value_type: str) -> Any:
    if value_type == "bool":
        if isinstance(raw_value, bool):
            return raw_value
        if isinstance(raw_value, (int, float)):
            return raw_value != 0
        if isinstance(raw_value, str):
            normalized = raw_value.strip().lower()
            if normalized in {"", "0", "false", "off", "no"}:
                return False
            if normalized in {"1", "true", "on", "yes"}:
                return True
        return bool(raw_value)
    if value_type == "int":
        return max(0, _safe_int(raw_value))
    raise ValueError("Unsupported override type")


def _sanitize_rule(rule: dict[str, Any], kind: str) -> dict[str, Any]:
    keyword = str(rule.get("keyword", "") or "").strip()
    if not keyword:
        raise ValueError("规则关键字不能为空")

    sanitized = {
        "keyword": keyword,
        "regex": bool(rule.get("regex", False)),
        "enabled": bool(rule.get("enabled", True)),
        "mode": str(rule.get("mode", "whitelist") or "whitelist"),
        "groups": _clean_group_ids(rule.get("groups", [])),
        "entries": [],
    }
    if sanitized["mode"] not in {"whitelist", "blacklist"}:
        sanitized["mode"] = "whitelist"

    entries = rule.get("entries", []) or []
    for item in entries:
        components = _sanitize_components(item.get("components", []))
        entry = _components_to_entry(components)
        has_rich = any(
            entry[key]
            for key in ("images", "records", "videos", "ats", "faces", "forwards")
        )
        if components or entry["text"] or has_rich:
            sanitized["entries"].append(entry)

    if not sanitized["entries"]:
        raise ValueError(f"规则 '{keyword}' 至少需要一条非空回复")

    overrides = rule.get("overrides", {}) or {}
    field_mapping = KEYWORD_OVERRIDE_FIELDS if kind == "command_triggered" else DETECT_OVERRIDE_FIELDS
    for field_name, stored_name in field_mapping:
        if field_name not in overrides:
            continue
        if field_name in {"recall_delay", "cooldown"}:
            value = _sanitize_override_value(overrides.get(field_name), value_type="int")
        else:
            value = _sanitize_override_value(overrides.get(field_name), value_type="bool")
        if field_name == "case_sensitive" and kind == "auto_detect":
            sanitized["case_sensitive_override"] = value
        else:
            sanitized[stored_name] = value

    return sanitized


def sanitize_rule_collections(payload: dict[str, Any]) -> dict[str, Any]:
    result = {"command_triggered": [], "auto_detect": []}
    for section in ("command_triggered", "auto_detect"):
        seen: set[str] = set()
        for rule in payload.get(section, []) or []:
            sanitized = _sanitize_rule(rule, section)
            key = sanitized["keyword"]
            normalized = key.lower()
            if normalized in seen:
                section_label = "关键词" if section == "command_triggered" else "检测词"
                raise ValueError(f"{section_label} '{key}' 重复")
            seen.add(normalized)
            result[section].append(sanitized)
    return result


def get_effective_bool(
    plugin: Any,
    rule: dict[str, Any] | None,
    override_key: str,
    config_key: str,
) -> bool:
    if rule and override_key in rule:
        return bool(rule.get(override_key))
    if rule and config_key == "case_sensitive" and "case_sensitive" in rule:
        return bool(rule.get("case_sensitive"))
    return bool(plugin.config.get(config_key, False))


def get_effective_int(
    plugin: Any,
    rule: dict[str, Any] | None,
    override_key: str,
    config_key: str,
) -> int:
    if rule and override_key in rule:
        return max(0, _safe_int(rule.get(override_key)))
    return max(0, _safe_int(plugin.config.get(config_key, 0)))


def get_effective_recall_delay(
    plugin: Any,
    rule: dict[str, Any] | None,
    kind: str,
) -> int:
    if rule and "recall_delay_override" in rule:
        return max(0, _safe_int(rule.get("recall_delay_override")))
    keyword_delay, detect_delay = _parse_recall_delay_config(
        plugin.config.get("recall_delay", "0 0")
    )
    return keyword_delay if kind == "command_triggered" else detect_delay
