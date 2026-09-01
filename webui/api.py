from __future__ import annotations

import asyncio
import base64
import datetime
import hashlib
import mimetypes
import traceback
from pathlib import Path
from typing import Any

from astrbot.api import logger
from quart import jsonify, request, send_file

from .payloads import build_plugin_state_payload, sanitize_rule_collections


PLUGIN_NAME = "astrbot_plugin_keywords_reply"

MEDIA_UPLOAD_SUFFIXES = {
    "image": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"},
    "record": {".amr", ".mp3", ".wav", ".ogg", ".oga", ".m4a", ".aac", ".flac"},
    "video": {".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv"},
}


class KeywordsReplyWebUIApi:
    def __init__(self, plugin):
        self.plugin = plugin

    def register(self) -> None:
        self.plugin.context.register_web_api(
            f"/{PLUGIN_NAME}/state",
            self._wrap_handler(self.get_state),
            ["GET"],
            "Get keywords reply rule state",
        )
        self.plugin.context.register_web_api(
            f"/{PLUGIN_NAME}/save-all",
            self._wrap_handler(self.save_all),
            ["POST"],
            "Save keywords reply rules",
        )
        self.plugin.context.register_web_api(
            f"/{PLUGIN_NAME}/reorder",
            self._wrap_handler(self.reorder_rules),
            ["POST"],
            "Reorder keywords reply rules",
        )
        self.plugin.context.register_web_api(
            f"/{PLUGIN_NAME}/upload-media/<component_type>",
            self._wrap_handler(self.upload_media),
            ["POST"],
            "Upload keywords reply media asset",
        )
        self.plugin.context.register_web_api(
            f"/{PLUGIN_NAME}/media/<component_type>/<path:filename>",
            self._wrap_handler(self.serve_media),
            ["GET"],
            "Preview keywords reply media asset",
        )
        self.plugin.context.register_web_api(
            f"/{PLUGIN_NAME}/media-preview",
            self._wrap_handler(self.get_media_preview),
            ["GET"],
            "Read keywords reply media preview",
        )

    def _wrap_handler(self, handler):
        async def wrapped(*args, **kwargs):
            try:
                return await handler(*args, **kwargs)
            except ValueError as exc:
                return jsonify({"status": "error", "message": str(exc)})
            except Exception as exc:  # pragma: no cover - runtime guard
                logger.error(
                    "Keywords Reply WebUI API failed in %s: %s\n%s",
                    getattr(handler, "__name__", "unknown"),
                    exc,
                    traceback.format_exc(),
                )
                return jsonify({"status": "error", "message": "保存失败，请检查输入后重试。"})

        return wrapped

    async def get_state(self):
        return jsonify(build_plugin_state_payload(self.plugin))

    async def save_all(self):
        payload = await request.get_json(force=True)
        sanitized = sanitize_rule_collections(payload or {})

        for section in ("command_triggered", "auto_detect"):
            for rule in sanitized[section]:
                if rule.get("regex", False):
                    keyword = rule["keyword"]
                    if not self.plugin.utils.is_safe_regex(keyword):
                        raise ValueError(f"规则 '{keyword}' 的正则表达式存在安全风险")
                    self.plugin.utils.get_compiled_regex(f"webui:{section}", keyword, 0)
                    import re

                    re.compile(keyword)

        self.plugin.data = self.plugin.utils.normalize_data(sanitized)
        await self.plugin.utils.save_data_async()
        return jsonify({"ok": True, **build_plugin_state_payload(self.plugin)})

    async def reorder_rules(self):
        payload = await request.get_json(force=True)
        kind = str(payload.get("kind", "")).strip()
        keywords = payload.get("keywords")
        if kind not in {"command_triggered", "auto_detect"}:
            raise ValueError("不支持的规则类型")
        if not isinstance(keywords, list) or any(not str(keyword or "").strip() for keyword in keywords):
            raise ValueError("缺少有效的排序列表")

        normalized_keywords = [str(keyword).strip() for keyword in keywords]
        current_rules = list(self.plugin.data.get(kind, []) or [])
        current_keywords = [str(rule.get("keyword", "")).strip() for rule in current_rules]
        if (
            len(normalized_keywords) != len(current_keywords)
            or len(set(normalized_keywords)) != len(normalized_keywords)
            or set(normalized_keywords) != set(current_keywords)
        ):
            raise ValueError("排序对象与当前数据不一致，请刷新后重试")

        rules_by_keyword = {str(rule.get("keyword", "")).strip(): rule for rule in current_rules}
        self.plugin.data[kind] = [rules_by_keyword[keyword] for keyword in normalized_keywords]
        await self.plugin.utils.save_data_async()
        return jsonify({"ok": True, "keywords": normalized_keywords})

    async def upload_media(self, component_type: str):
        files = await request.files
        file = files.get("file")
        if file is None:
            raise ValueError("未提供上传文件")

        component_type = str(component_type or "").strip().lower()
        if component_type not in {"image", "record", "video"}:
            raise ValueError("不支持的媒体类型")

        original_filename = str(file.filename or "").strip()
        suffix = Path(original_filename).suffix.lower()
        if suffix not in MEDIA_UPLOAD_SUFFIXES[component_type]:
            media_labels = {"image": "图片", "record": "语音", "video": "视频"}
            raise ValueError(f"请选择有效的{media_labels[component_type]}文件")

        target_dir = {
            "image": Path(self.plugin.image_dir),
            "record": Path(self.plugin.record_dir),
            "video": Path(self.plugin.video_dir),
        }[component_type]
        digest = hashlib.md5(
            f"{original_filename}-{datetime.datetime.now().timestamp()}".encode("utf-8")
        ).hexdigest()[:8]
        filename = (
            f"{component_type}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{digest}{suffix}"
        )
        target_path = target_dir / filename
        await file.save(target_path)
        return jsonify(
            {
                "ok": True,
                "item": {"type": component_type, "path": filename},
            }
        )

    async def serve_media(self, component_type: str, filename: str):
        resolved_path = self._resolve_media_path(component_type, filename)
        if resolved_path is None:
            return jsonify({"status": "error", "message": "媒体文件不存在"}), 404

        media_type, _ = mimetypes.guess_type(resolved_path.name)
        return await send_file(
            resolved_path,
            mimetype=media_type or "application/octet-stream",
        )

    async def get_media_preview(self):
        component_type = request.args.get("type", "")
        filename = request.args.get("path", "")
        resolved_path = self._resolve_media_path(component_type, filename)
        if resolved_path is None:
            return jsonify({"status": "error", "message": "媒体文件不存在"}), 404

        max_preview_size = 16 * 1024 * 1024
        try:
            if resolved_path.stat().st_size > max_preview_size:
                return jsonify(
                    {
                        "ok": False,
                        "previewable": False,
                        "message": "媒体文件过大，请直接下载。",
                    }
                )
            content = await asyncio.to_thread(resolved_path.read_bytes)
        except OSError:
            return jsonify({"status": "error", "message": "读取媒体文件失败"}), 404

        media_type, _ = mimetypes.guess_type(resolved_path.name)
        if not media_type:
            media_type = {
                "image": "image/jpeg",
                "record": "audio/amr",
                "video": "video/mp4",
            }.get(str(component_type).strip().lower(), "application/octet-stream")
        encoded = base64.b64encode(content).decode("ascii")
        return jsonify(
            {
                "ok": True,
                "previewable": True,
                "url": f"data:{media_type};base64,{encoded}",
            }
        )

    def _resolve_media_path(self, component_type: str, filename: str) -> Path | None:
        component_type = str(component_type or "").strip().lower()
        media_dirs = {
            "image": Path(self.plugin.image_dir),
            "record": Path(self.plugin.record_dir),
            "video": Path(self.plugin.video_dir),
        }
        target_dir = media_dirs.get(component_type)
        if target_dir is None:
            return None

        try:
            requested_path = Path(str(filename or ""))
            if requested_path.is_absolute() or any(
                part in {"", ".", ".."} for part in requested_path.parts
            ):
                return None

            resolved_dir = target_dir.resolve()
            resolved_path = (resolved_dir / requested_path).resolve()
            resolved_path.relative_to(resolved_dir)
        except (OSError, ValueError):
            return None

        if not resolved_path.is_file():
            return None
        return resolved_path
