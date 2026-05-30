from __future__ import annotations

import datetime
import hashlib
import traceback
from pathlib import Path
from typing import Any

from astrbot.api import logger
from quart import jsonify, request

from .payloads import build_plugin_state_payload, sanitize_rule_collections


PLUGIN_NAME = "astrbot_plugin_keywords_reply"


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
            f"/{PLUGIN_NAME}/upload-media/<component_type>",
            self._wrap_handler(self.upload_media),
            ["POST"],
            "Upload keywords reply media asset",
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

    async def upload_media(self, component_type: str):
        files = await request.files
        file = files.get("file")
        if file is None:
            raise ValueError("未提供上传文件")

        component_type = str(component_type or "").strip().lower()
        if component_type not in {"image", "record", "video"}:
            raise ValueError("不支持的媒体类型")

        target_dir = {
            "image": Path(self.plugin.image_dir),
            "record": Path(self.plugin.record_dir),
            "video": Path(self.plugin.video_dir),
        }[component_type]
        suffix = Path(file.filename or "").suffix or {
            "image": ".jpg",
            "record": ".amr",
            "video": ".mp4",
        }[component_type]
        digest = hashlib.md5(
            f"{file.filename}-{datetime.datetime.now().timestamp()}".encode("utf-8")
        ).hexdigest()[:8]
        filename = (
            f"{component_type}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{digest}{suffix}"
        )
        target_path = target_dir / filename
        await file.save(target_path)
        return jsonify({"ok": True, "item": {"type": component_type, "path": filename}})
