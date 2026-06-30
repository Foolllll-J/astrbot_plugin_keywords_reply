import asyncio
import hashlib
import json
import os
import re
import shutil
from datetime import datetime
from urllib.parse import unquote, urlparse

import aiohttp

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageEventResult, MessageChain
from astrbot.api.message_components import At, Face, Image, Node, Nodes, Plain, Record, Reply, Video
from ..webui.payloads import get_effective_bool


class PluginUtils:
    def __init__(self, plugin):
        self.plugin = plugin
        self._mention_pattern = re.compile(
            r"\[@\s*(\d+)\]",
        )
        self._forward_bot_info = {}

    def build_empty_entry(self) -> dict:
        return {
            "text": "",
            "images": [],
            "records": [],
            "videos": [],
            "ats": [],
            "faces": [],
            "forwards": [],
        }

    def entry_has_payload(self, entry: dict | None) -> bool:
        entry = entry or {}
        return bool(
            (entry.get("text") or "").strip()
            or entry.get("images")
            or entry.get("records")
            or entry.get("videos")
            or entry.get("ats")
            or entry.get("faces")
            or entry.get("forwards")
        )

    def normalize_data(self, data: dict) -> dict:
        if not isinstance(data, dict):
            return {"command_triggered": [], "auto_detect": []}
        data.setdefault("command_triggered", [])
        data.setdefault("auto_detect", [])
        for section in ("command_triggered", "auto_detect"):
            for cfg in data.get(section, []):
                for entry in cfg.get("entries", []):
                    entry.setdefault("text", "")
                    entry.setdefault("images", [])
                    entry.setdefault("records", [])
                    entry.setdefault("videos", [])
                    entry.setdefault("ats", [])
                    entry.setdefault("faces", [])
                    entry.setdefault("forwards", [])
        return data

    def load_data(self):
        if os.path.exists(self.plugin.data_file):
            try:
                with open(self.plugin.data_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载关键词数据失败: {e}")
        return {"command_triggered": [], "auto_detect": []}

    async def save_data_async(self):
        tmp_file = f"{self.plugin.data_file}.tmp"
        async with self.plugin._save_lock:
            self.plugin.data_version += 1
            self.plugin._regex_cache.clear()
            try:
                payload = json.dumps(self.plugin.data, ensure_ascii=False, indent=2)
                with open(tmp_file, "w", encoding="utf-8") as f:
                    f.write(payload)
                os.replace(tmp_file, self.plugin.data_file)
            except Exception as e:
                logger.error(f"保存关键词数据失败: {e}")
                try:
                    if os.path.exists(tmp_file):
                        os.remove(tmp_file)
                except Exception:
                    pass
                return

        self.cleanup_unused_media()

    def save_data(self):
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.save_data_async())
        except RuntimeError:
            asyncio.run(self.save_data_async())

    def collect_referenced_media(self) -> dict:
        refs = {"images": set(), "records": set(), "videos": set()}
        for section in ("command_triggered", "auto_detect"):
            for cfg in self.plugin.data.get(section, []):
                for entry in cfg.get("entries", []):
                    for image in entry.get("images", []):
                        path = image.get("path")
                        if path:
                            refs["images"].add(os.path.basename(path))
                    for record in entry.get("records", []):
                        path = record.get("path")
                        if path:
                            refs["records"].add(os.path.basename(path))
                    for video in entry.get("videos", []):
                        path = video.get("path")
                        if path:
                            refs["videos"].add(os.path.basename(path))
        return refs

    def cleanup_unused_media(self):
        try:
            referenced = self.collect_referenced_media()
            removed = 0
            for base_dir, key in (
                (self.plugin.image_dir, "images"),
                (self.plugin.record_dir, "records"),
                (self.plugin.video_dir, "videos"),
            ):
                for name in os.listdir(base_dir):
                    full_path = os.path.join(base_dir, name)
                    if not os.path.isfile(full_path):
                        continue
                    if name not in referenced[key]:
                        os.remove(full_path)
                        removed += 1
            if removed > 0:
                logger.info(f"已清理未引用媒体文件: {removed} 个")
        except Exception as e:
            logger.error(f"清理未引用媒体文件失败: {e}")

    def permission_denied_result(self, event: AstrMessageEvent, message: str = "权限不足。"):
        if self.plugin.config.get("notify_permission_denied", True):
            return event.plain_result(message)
        return None

    def get_compiled_regex(self, scope: str, pattern: str, flags: int = 0):
        cache_key = (scope, pattern, flags)
        compiled = self.plugin._regex_cache.get(cache_key)
        if compiled is not None:
            return compiled
        try:
            compiled = re.compile(pattern, flags)
            self.plugin._regex_cache[cache_key] = compiled
            return compiled
        except Exception as e:
            logger.error(f"正则表达式编译失败({scope}: {pattern}): {e}")
            return None

    def get_platform_adapter_name(self, platform_id: str) -> str:
        if not platform_id:
            return ""

        platform_inst = self.plugin.context.get_platform_inst(platform_id)
        if not platform_inst:
            return platform_id

        try:
            if hasattr(platform_inst, "meta"):
                meta = platform_inst.meta()
                if hasattr(meta, "name") and meta.name:
                    return str(meta.name)
        except Exception:
            pass

        return platform_id

    def get_platform_api_client(self, platform_id: str):
        platform_inst = self.plugin.context.get_platform_inst(platform_id)
        if not platform_inst:
            return None

        if hasattr(platform_inst, "bot") and hasattr(platform_inst.bot, "api"):
            return platform_inst.bot.api
        if hasattr(platform_inst, "client") and hasattr(platform_inst.client, "api"):
            return platform_inst.client.api
        return None

    def is_qq_platform_event(self, event: AstrMessageEvent) -> bool:
        platform_id = event.get_platform_id()
        adapter_name = self.get_platform_adapter_name(platform_id).lower()
        platform_name = str(event.get_platform_name() or "").lower()
        candidates = {adapter_name, platform_name, str(platform_id or "").lower()}
        return any(name in {"aiocqhttp", "onebot", "napcat"} for name in candidates if name)

    def should_use_forwarded_replies(
        self,
        event: AstrMessageEvent,
        entries: list[dict],
        rule_cfg: dict | None = None,
    ) -> bool:
        if not get_effective_bool(
            self.plugin,
            rule_cfg,
            "qq_forward_all_replies_override",
            "qq_forward_all_replies",
        ):
            return False
        if len(entries or []) <= 1:
            return False
        if not event.get_group_id():
            return False
        if any(entry.get("forwards") for entry in entries or []):
            return False
        return self.is_qq_platform_event(event)

    def _get_platform_instances(self) -> list:
        pm = getattr(self.plugin.context, "platform_manager", None)
        if not pm:
            return []
        if hasattr(pm, "platform_insts"):
            return list(getattr(pm, "platform_insts") or [])
        if hasattr(pm, "get_insts"):
            try:
                return list(pm.get_insts() or [])
            except Exception:
                return []
        return []

    async def get_forward_bot_identity(self, event: AstrMessageEvent) -> tuple[int, str]:
        platform_id = event.get_platform_id()
        cache_key = str(platform_id or "")
        cached = self._forward_bot_info.get(cache_key)
        if cached:
            return cached

        bot = getattr(event, "bot", None)
        if bot is None:
            platform_inst = self.plugin.context.get_platform_inst(platform_id) if platform_id else None
            if platform_inst is not None:
                if hasattr(platform_inst, "get_client"):
                    try:
                        bot = platform_inst.get_client()
                    except Exception:
                        bot = None
                if bot is None and hasattr(platform_inst, "bot"):
                    bot = platform_inst.bot

        if bot is None:
            for platform_inst in self._get_platform_instances():
                try:
                    meta = platform_inst.meta() if hasattr(platform_inst, "meta") else None
                    meta_id = str(getattr(meta, "id", "") or "")
                    meta_name = str(getattr(meta, "name", "") or "").lower()
                    if platform_id and meta_id != str(platform_id):
                        continue
                    if platform_id or any(token in meta_name for token in ("qq", "onebot", "aiocqhttp", "napcat")):
                        if hasattr(platform_inst, "get_client"):
                            bot = platform_inst.get_client()
                        elif hasattr(platform_inst, "bot"):
                            bot = platform_inst.bot
                        if bot is not None:
                            break
                except Exception:
                    continue

        self_id = 0
        node_name = "AstrBot"
        if bot is not None and hasattr(bot, "get_login_info"):
            try:
                info = await bot.get_login_info()
                self_id = int(info.get("user_id") or 0)
                node_name = str(info.get("nickname") or info.get("user_name") or node_name)
            except Exception as exc:
                logger.debug(f"获取 QQ 合并转发 bot 信息失败: {exc}")

        if self_id <= 0:
            try:
                self_id = int(event.get_self_id() or 0)
            except Exception:
                self_id = 0

        identity = (self_id, node_name)
        self._forward_bot_info[cache_key] = identity
        return identity

    def extract_reply_message_id(self, event: AstrMessageEvent) -> str | None:
        try:
            message_obj = getattr(event, "message_obj", None)
            segments = getattr(message_obj, "message", None) if message_obj is not None else None
            if isinstance(segments, list):
                for seg in segments:
                    if seg.__class__.__name__ == "Reply":
                        seg_id = str(getattr(seg, "id", "") or getattr(seg, "message_id", "") or "").strip()
                        if seg_id:
                            return seg_id
        except Exception:
            pass

        try:
            message_obj = getattr(event, "message_obj", None)
            raw_message = getattr(message_obj, "raw_message", None) if message_obj is not None else None
            raw_segments = raw_message.get("message") if isinstance(raw_message, dict) else None
            if isinstance(raw_segments, list):
                for seg in raw_segments:
                    if isinstance(seg, dict) and str(seg.get("type", "")).lower() == "reply":
                        data = seg.get("data", {}) or {}
                        seg_id = str(data.get("id", "") or data.get("message_id", "") or "").strip()
                        if seg_id:
                            return seg_id
        except Exception:
            pass

        text = str(getattr(event, "message_str", "") or "")
        match = re.search(r"\[CQ:reply,id=([0-9]+)\]", text, flags=re.IGNORECASE)
        if match:
            return str(match.group(1)).strip()
        return None

    def build_template_context(self, event: AstrMessageEvent) -> dict:
        now = datetime.now()
        sender_name = ""
        try:
            sender_name = event.get_sender_name() or ""
        except Exception:
            sender_name = ""
        return {
            "user_id": str(event.get_sender_id() or ""),
            "user_name": sender_name,
            "group_id": str(event.get_group_id() or ""),
            "self_id": str(event.get_self_id() or ""),
            "platform": str(event.get_platform_name() or ""),
            "message": event.message_str or "",
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        }

    def render_template_text(self, event: AstrMessageEvent, text: str) -> str:
        if not text:
            return text
        if not self.plugin.config.get("enable_text_template", True):
            return text
        context = self.build_template_context(event)
        pattern = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
        return pattern.sub(lambda m: str(context.get(m.group(1), m.group(0))), text)

    async def download_image(self, url: str) -> str | None:
        try:
            if url.startswith(("http://", "https://")):
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            content = await resp.read()
                        else:
                            return None
            elif os.path.exists(url):
                with open(url, "rb") as f:
                    content = f.read()
            else:
                return None
            ext = ".jpg"
            if not url.startswith(("http://", "https://")):
                ext = os.path.splitext(url)[1] or ".jpg"
            filename = hashlib.md5(content).hexdigest() + ext
            path = os.path.join(self.plugin.image_dir, filename)
            with open(path, "wb") as f:
                f.write(content)
            return path
        except Exception as e:
            logger.error(f"下载图片失败: {e}")
        return None

    async def download_media_file(self, url: str, media_type: str) -> str | None:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return None
                    content = await resp.read()

            suffix = {
                "image": ".jpg",
                "record": ".amr",
                "video": ".mp4",
            }.get(media_type, "")
            filename = hashlib.md5(content).hexdigest() + suffix
            base_dir = {
                "image": self.plugin.image_dir,
                "record": self.plugin.record_dir,
                "video": self.plugin.video_dir,
            }[media_type]
            path = os.path.join(base_dir, filename)
            with open(path, "wb") as f:
                f.write(content)
            return filename
        except Exception as e:
            logger.error(f"下载媒体失败({media_type}): {e}")
            return None

    async def save_media_file(self, source_path: str, media_type: str) -> str | None:
        try:
            suffix = os.path.splitext(source_path)[1] or {
                "image": ".jpg",
                "record": ".amr",
                "video": ".mp4",
            }.get(media_type, "")
            filename = hashlib.md5(
                f"{media_type}:{datetime.now().timestamp()}:{source_path}".encode("utf-8")
            ).hexdigest() + suffix
            base_dir = {
                "image": self.plugin.image_dir,
                "record": self.plugin.record_dir,
                "video": self.plugin.video_dir,
            }[media_type]
            target_path = os.path.join(base_dir, filename)
            shutil.copy(source_path, target_path)
            return filename
        except Exception as e:
            logger.error(f"保存媒体失败({media_type}): {e}")
            return None

    def is_admin(self, event: AstrMessageEvent):
        if event.is_admin():
            return True
        sender_id = str(event.get_sender_id())
        whitelist = {str(uid) for uid in self.plugin.config.get("whitelist", [])}
        return sender_id in whitelist

    def parse_message_to_entry(self, components):
        text_parts = []
        images = []
        records = []
        videos = []
        ats = []
        faces = []
        for comp in components:
            if isinstance(comp, Plain):
                plain_text, inline_ats = self._extract_inline_ats(comp.text)
                if plain_text:
                    text_parts.append(plain_text)
                ats.extend(inline_ats)
            elif isinstance(comp, Image):
                images.append({"url": comp.url, "file": comp.file, "path": comp.path})
            elif isinstance(comp, Record):
                records.append(
                    {
                        "url": getattr(comp, "url", None),
                        "file": getattr(comp, "file", None),
                        "path": getattr(comp, "path", None),
                    }
                )
            elif isinstance(comp, Video):
                videos.append(
                    {
                        "url": getattr(comp, "url", None),
                        "file": getattr(comp, "file", None),
                        "path": getattr(comp, "path", None),
                    }
                )
            elif isinstance(comp, At):
                qq = str(comp.qq)
                ats.append({"qq": qq, "all": qq.lower() == "all"})
            elif isinstance(comp, Face):
                faces.append({"id": comp.id})

        entry = {
            "text": "".join(text_parts).strip(),
            "images": images,
            "records": records,
            "videos": videos,
            "ats": ats,
            "faces": faces,
        }
        has_media = any((images, records, videos, ats, faces))
        return entry, has_media

    def _extract_inline_ats(self, text: str) -> tuple[str, list[dict]]:
        if not text:
            return "", []

        inline_ats: list[dict] = []
        text_parts: list[str] = []
        last_end = 0

        for match in self._mention_pattern.finditer(text):
            if match.start() > last_end:
                text_parts.append(text[last_end:match.start()])

            inline_ats.append({"qq": match.group(1), "all": False})
            last_end = match.end()

        if last_end < len(text):
            text_parts.append(text[last_end:])

        return "".join(text_parts), inline_ats

    async def process_entry_media(self, entry):
        processed_images = []
        for item in entry.get("images", []):
            url = item.get("url")
            path = item.get("path")
            if path and os.path.exists(path) and self.plugin.image_dir in path:
                processed_images.append({"path": os.path.basename(path)})
            elif url:
                local_path = await self.download_image(url)
                if local_path:
                    processed_images.append({"path": os.path.basename(local_path)})
                else:
                    processed_images.append(item)
            else:
                processed_images.append(item)
        entry["images"] = processed_images

        processed_records = []
        for item in entry.get("records", []):
            path = item.get("path")
            source_path = None
            if path and os.path.exists(path) and self.plugin.record_dir in path:
                processed_records.append({"path": os.path.basename(path)})
                continue
            if path and os.path.exists(path):
                source_path = path
            elif item.get("file") and os.path.exists(item["file"]):
                source_path = item["file"]
            if source_path:
                filename = await self.save_media_file(source_path, "record")
                if filename:
                    processed_records.append({"path": filename})
            elif item.get("url"):
                filename = await self.download_media_file(item["url"], "record")
                if filename:
                    processed_records.append({"path": filename})
        entry["records"] = processed_records

        processed_videos = []
        for item in entry.get("videos", []):
            path = item.get("path")
            source_path = None
            if path and os.path.exists(path) and self.plugin.video_dir in path:
                processed_videos.append({"path": os.path.basename(path)})
                continue
            if path and os.path.exists(path):
                source_path = path
            elif item.get("file") and os.path.exists(item["file"]):
                source_path = item["file"]
            if source_path:
                filename = await self.save_media_file(source_path, "video")
                if filename:
                    processed_videos.append({"path": filename})
            elif item.get("url"):
                filename = await self.download_media_file(item["url"], "video")
                if filename:
                    processed_videos.append({"path": filename})
        entry["videos"] = processed_videos
        return entry

    async def build_entry_from_onebot_segments(self, segments: list[dict]) -> dict:
        entry = self.build_empty_entry()

        text_parts = []
        for seg in segments or []:
            if not isinstance(seg, dict):
                continue
            seg_type = str(seg.get("type", "")).lower()
            data = seg.get("data", {}) or {}

            if seg_type == "text":
                content = str(data.get("text", "") or "")
                if content:
                    plain_text, inline_ats = self._extract_inline_ats(content)
                    if plain_text:
                        text_parts.append(plain_text)
                    entry["ats"].extend(inline_ats)
            elif seg_type == "at":
                qq = str(data.get("qq", "") or "").strip()
                if qq:
                    entry["ats"].append({"qq": qq, "all": qq.lower() == "all"})
            elif seg_type == "face":
                face_id = data.get("id")
                if face_id is not None:
                    entry["faces"].append({"id": face_id})
            elif seg_type == "image":
                source = str(data.get("file", "") or "").strip()
                url = str(data.get("url", "") or "").strip()
                resolved_url = url or (source if source.startswith(("http://", "https://")) else None)
                resolved_path = None if resolved_url else (source or None)
                entry["images"].append({"file": source or None, "url": resolved_url, "path": resolved_path})
            elif seg_type == "record":
                source = str(data.get("file", "") or "").strip()
                url = str(data.get("url", "") or "").strip()
                resolved_url = url or (source if source.startswith(("http://", "https://")) else None)
                resolved_path = None if resolved_url else (source or None)
                entry["records"].append({"file": source or None, "url": resolved_url, "path": resolved_path})
            elif seg_type == "video":
                source = str(data.get("file", "") or "").strip()
                url = str(data.get("url", "") or "").strip()
                resolved_url = url or (source if source.startswith(("http://", "https://")) else None)
                resolved_path = None if resolved_url else (source or None)
                entry["videos"].append({"file": source or None, "url": resolved_url, "path": resolved_path})
            elif seg_type == "forward":
                forward_id = str(
                    data.get("id", "")
                    or data.get("message_id", "")
                    or data.get("res_id", "")
                    or ""
                ).strip()
                if forward_id:
                    entry["forwards"].append({"id": forward_id})

        entry["text"] = "".join(text_parts).strip()
        return entry

    async def fetch_reply_entry(self, event: AstrMessageEvent) -> dict:
        empty_entry = self.build_empty_entry()

        platform_id = event.get_platform_id()
        if self.get_platform_adapter_name(platform_id) != "aiocqhttp":
            return empty_entry

        reply_message_id = self.extract_reply_message_id(event)
        if not reply_message_id or not reply_message_id.isdigit():
            return empty_entry

        api = self.get_platform_api_client(platform_id)
        if not api:
            return empty_entry

        try:
            original_msg = await api.call_action("get_msg", message_id=int(reply_message_id))
        except Exception as exc:
            logger.warning(f"获取引用消息失败: message_id={reply_message_id}, error={exc}")
            return empty_entry

        message_segments = original_msg.get("message") if isinstance(original_msg, dict) else None
        if not isinstance(message_segments, list):
            return empty_entry

        entry = await self.build_entry_from_onebot_segments(message_segments)
        if entry.get("forwards"):
            relayed_forward = await self._relay_forward_reply_to_self(
                event, int(reply_message_id)
            )
            if relayed_forward:
                entry["forwards"] = [relayed_forward]
            else:
                entry["forwards"] = []
        return entry

    async def _relay_forward_reply_to_self(
        self, event: AstrMessageEvent, source_message_id: int
    ) -> dict | None:
        if not source_message_id:
            return None

        bot = getattr(event, "bot", None)
        platform_id = event.get_platform_id()
        if bot is None and platform_id:
            platform_inst = self.plugin.context.get_platform_inst(platform_id)
            if platform_inst is not None:
                if hasattr(platform_inst, "get_client"):
                    try:
                        bot = platform_inst.get_client()
                    except Exception:
                        bot = None
                if bot is None and hasattr(platform_inst, "bot"):
                    bot = platform_inst.bot

        api = getattr(bot, "api", None)
        if api is None:
            return None

        try:
            login_info = await api.call_action("get_login_info")
            self_id = int(login_info.get("user_id") or 0)
            if self_id <= 0:
                return None

            ret = await api.call_action(
                "forward_friend_single_msg",
                user_id=self_id,
                message_id=source_message_id,
            )

            relay_msg_id = ""
            if isinstance(ret, dict):
                relay_msg_id = str(
                    ret.get("message_id", "")
                    or ret.get("data", {}).get("message_id", "")
                    or ""
                ).strip()
            if relay_msg_id:
                return {"id": relay_msg_id}

            await asyncio.sleep(1)
            history_result = await api.call_action(
                "get_friend_msg_history",
                user_id=self_id,
                count=10,
            )
            messages = []
            if isinstance(history_result, dict):
                messages = history_result.get("messages", []) or history_result.get(
                    "data", {}
                ).get("messages", [])

            for msg in reversed(messages):
                relay_msg_id = str(msg.get("message_id", "") or "").strip()
                if relay_msg_id:
                    return {"id": relay_msg_id}
        except Exception as exc:
            logger.warning(f"转存引用的合并转发消息失败: {exc}")
        return None

    def merge_entries(self, primary: dict, secondary: dict) -> dict:
        primary = primary or {}
        secondary = secondary or {}
        primary_text = (primary.get("text") or "").strip()
        secondary_text = (secondary.get("text") or "").strip()

        merged_text = primary_text
        if primary_text and secondary_text:
            merged_text = f"{primary_text}\n{secondary_text}"
        elif secondary_text:
            merged_text = secondary_text

        return {
            "text": merged_text,
            "images": list(primary.get("images", [])) + list(secondary.get("images", [])),
            "records": list(primary.get("records", [])) + list(secondary.get("records", [])),
            "videos": list(primary.get("videos", [])) + list(secondary.get("videos", [])),
            "ats": list(primary.get("ats", [])) + list(secondary.get("ats", [])),
            "faces": list(primary.get("faces", [])) + list(secondary.get("faces", [])),
            "forwards": list(primary.get("forwards", [])) + list(secondary.get("forwards", [])),
        }

    def summarize_entry_for_list(self, entry: dict, max_text: int = 30) -> str:
        text = (entry.get("text") or "").replace("\n", " ")
        summary = text[:max_text]
        if len(text) > max_text:
            summary += "..."
        placeholders = []
        if entry.get("images"):
            placeholders.append("[图片]")
        if entry.get("records"):
            placeholders.append("[语音]")
        if entry.get("videos"):
            placeholders.append("[视频]")
        if entry.get("forwards"):
            placeholders.append("[聊天记录]")
        if not summary:
            return "".join(placeholders)
        return f"{summary}{''.join(placeholders)}"

    def build_entry_placeholder_text(self, entry: dict, include_images: bool = True) -> str:
        lines = []
        if entry.get("text"):
            lines.append(entry["text"])
        if include_images and entry.get("images"):
            lines.append(f"[图片 x{len(entry['images'])}]")
        if entry.get("records"):
            lines.append("[语音]")
        if entry.get("videos"):
            lines.append("[视频]")
        if entry.get("forwards"):
            lines.append("[聊天记录]")
        return "\n".join(lines).strip()

    def get_reply_result(
        self,
        event: AstrMessageEvent,
        entry: dict,
        use_quote: bool = False,
        render_template: bool = True,
        rule_cfg: dict | None = None,
    ):
        try:
            chain = []

            if (
                use_quote
                and get_effective_bool(
                    self.plugin, rule_cfg, "quote_reply_override", "quote_reply"
                )
                and event.message_obj
                and event.message_obj.message_id
            ):
                chain.append(Reply(id=event.message_obj.message_id))

            if entry.get("text"):
                text = entry["text"]
                if render_template:
                    text = self.render_template_text(event, text)
                chain.append(Plain(text))

            for at in entry.get("ats", []):
                if at.get("all"):
                    chain.append(At(qq="all"))
                else:
                    chain.append(At(qq=at.get("qq")))

            for face in entry.get("faces", []):
                chain.append(Face(id=face.get("id")))

            for img in entry.get("images", []):
                path = img.get("path")
                if path:
                    full_path = os.path.join(self.plugin.image_dir, path)
                    if os.path.exists(full_path):
                        chain.append(Image(file=full_path))
                    else:
                        logger.warning(f"图片文件不存在: {full_path}")
                elif img.get("url"):
                    chain.append(Image(url=img["url"]))

            if not chain:
                logger.warning(f"回复内容为空。Entry: {entry}")
                return None

            return MessageEventResult(chain=chain)

        except Exception as e:
            logger.error(f"构建回复结果失败: {e}", exc_info=True)
            return None

    def build_entry_message_chunks(
        self,
        event: AstrMessageEvent,
        entry: dict,
        use_quote: bool = False,
        render_template: bool = True,
        rule_cfg: dict | None = None,
    ):
        chunks = []
        first_chunk = []
        quote_component = None

        if (
            use_quote
            and get_effective_bool(
                self.plugin, rule_cfg, "quote_reply_override", "quote_reply"
            )
            and event.message_obj
            and event.message_obj.message_id
        ):
            quote_component = Reply(id=event.message_obj.message_id)

        if entry.get("text"):
            text = entry["text"]
            if render_template:
                text = self.render_template_text(event, text)
            first_chunk.append(Plain(text))

        for at in entry.get("ats", []):
            if at.get("all"):
                first_chunk.append(At(qq="all"))
            else:
                first_chunk.append(At(qq=at.get("qq")))

        for face in entry.get("faces", []):
            first_chunk.append(Face(id=face.get("id")))

        for img in entry.get("images", []):
            path = img.get("path")
            if path:
                full_path = os.path.join(self.plugin.image_dir, path)
                if os.path.exists(full_path):
                    first_chunk.append(Image(file=full_path))
            elif img.get("url"):
                first_chunk.append(Image(url=img["url"]))

        if first_chunk:
            if quote_component is not None:
                first_chunk.insert(0, quote_component)
            chunks.append(first_chunk)

        for record in entry.get("records", []):
            path = record.get("path")
            if path:
                full_path = os.path.join(self.plugin.record_dir, path)
                if os.path.exists(full_path):
                    chunks.append([Record.fromFileSystem(full_path)])

        for video in entry.get("videos", []):
            path = video.get("path")
            if path:
                full_path = os.path.join(self.plugin.video_dir, path)
                if os.path.exists(full_path):
                    chunks.append([Video.fromFileSystem(full_path)])

        return chunks

    async def _send_forward_reply(
        self,
        event: AstrMessageEvent,
        forward: dict,
        delay: int = 0,
    ) -> bool:
        forward_id = str(forward.get("id", "") or "").strip()
        group_id = event.get_group_id()
        if not forward_id or not group_id:
            return False

        bot = getattr(event, "bot", None)
        if bot is None:
            platform_inst = self.plugin.context.get_platform_inst(event.get_platform_id())
            if platform_inst is not None:
                if hasattr(platform_inst, "get_client"):
                    try:
                        bot = platform_inst.get_client()
                    except Exception:
                        bot = None
                if bot is None and hasattr(platform_inst, "bot"):
                    bot = platform_inst.bot

        api = getattr(bot, "api", None)
        if api is None:
            return False

        try:
            ret = await api.call_action(
                "forward_group_single_msg",
                group_id=int(group_id),
                message_id=int(forward_id),
            )
            message_id = int(ret.get("message_id") or 0) if isinstance(ret, dict) else 0
            if delay > 0 and message_id > 0:
                actual_delay = min(delay, 115) if delay >= 120 else delay
                await asyncio.sleep(actual_delay)
                await api.call_action("delete_msg", message_id=message_id)
            return True
        except Exception as exc:
            logger.error(f"发送聊天记录回复失败: {exc}", exc_info=True)
            return False

    def _component_file_to_onebot_file(self, file_value: str) -> str:
        if not file_value:
            return ""

        raw = str(file_value).strip()
        if raw.startswith(("http://", "https://")):
            return raw

        if raw.startswith("file://"):
            parsed = urlparse(raw)
            path = unquote(parsed.path or "")
            if os.name == "nt" and path.startswith("/") and len(path) > 2 and path[2] == ":":
                path = path[1:]
            abs_path = os.path.abspath(path)
            return f"file:///{abs_path.replace(os.sep, '/')}"

        abs_path = os.path.abspath(raw)
        return f"file:///{abs_path.replace(os.sep, '/')}"

    async def yield_entry_detail_results(
        self,
        event: AstrMessageEvent,
        intro: str,
        entry: dict,
        render_template: bool = False,
    ):
        placeholder_text = self.build_entry_placeholder_text(entry, include_images=False)
        preview_text = intro if intro.endswith("\n") else f"{intro}\n"
        if placeholder_text:
            preview_text = f"{preview_text}{placeholder_text}"
        elif self.entry_needs_rich_preview(entry) and preview_text.endswith("\n"):
            # Keep the line break before rich components from being collapsed.
            preview_text = f"{preview_text}\u200b"

        preview_entry = {
            "text": preview_text,
            "images": entry.get("images", []),
            "records": [],
            "videos": [],
            "ats": entry.get("ats", []),
            "faces": entry.get("faces", []),
        }
        res_obj = self.get_reply_result(event, preview_entry, use_quote=False, render_template=render_template)
        if res_obj and res_obj.chain:
            yield res_obj
        else:
            yield event.plain_result(preview_entry["text"])

        for record in entry.get("records", []):
            path = record.get("path")
            if not path:
                continue
            full_path = os.path.join(self.plugin.record_dir, path)
            if os.path.exists(full_path):
                yield MessageEventResult(chain=[Record.fromFileSystem(full_path)])

        for video in entry.get("videos", []):
            path = video.get("path")
            if not path:
                continue
            full_path = os.path.join(self.plugin.video_dir, path)
            if os.path.exists(full_path):
                yield MessageEventResult(chain=[Video.fromFileSystem(full_path)])

    def build_entry_preview_result(
        self,
        event: AstrMessageEvent,
        intro: str,
        entry: dict,
        render_template: bool = False,
    ):
        placeholder_text = self.build_entry_placeholder_text(entry, include_images=False)
        preview_text = intro if intro.endswith("\n") else f"{intro}\n"
        if placeholder_text:
            preview_text = f"{preview_text}{placeholder_text}"
        elif self.entry_needs_rich_preview(entry) and preview_text.endswith("\n"):
            # Keep the line break before rich components from being collapsed.
            preview_text = f"{preview_text}\u200b"

        preview_entry = {
            "text": preview_text,
            "images": entry.get("images", []),
            "records": [],
            "videos": [],
            "ats": entry.get("ats", []),
            "faces": entry.get("faces", []),
        }
        return self.get_reply_result(event, preview_entry, use_quote=False, render_template=render_template)

    def build_entry_preview_text(
        self,
        event: AstrMessageEvent,
        intro: str,
        entry: dict,
        render_template: bool = False,
    ) -> str:
        placeholder_entry = dict(entry)
        if render_template and placeholder_entry.get("text"):
            placeholder_entry["text"] = self.render_template_text(event, placeholder_entry["text"])

        placeholder_text = self.build_entry_placeholder_text(placeholder_entry, include_images=False)
        preview_text = intro if intro.endswith("\n") else f"{intro}\n"
        if placeholder_text:
            preview_text = f"{preview_text}{placeholder_text}"
        return preview_text

    def entry_needs_rich_preview(self, entry: dict) -> bool:
        return bool(entry.get("images") or entry.get("ats") or entry.get("faces"))

    def build_entries_preview_result(
        self,
        event: AstrMessageEvent,
        header: str,
        entries: list[dict],
        render_template: bool = False,
    ):
        chain = []
        pending_text_parts = [header]

        def flush_pending_text():
            nonlocal pending_text_parts
            if pending_text_parts:
                chain.append(Plain("".join(pending_text_parts)))
                pending_text_parts = []

        for i, entry in enumerate(entries, 1):
            intro = f"【{i}】\n"
            preview_text = self.build_entry_preview_text(
                event,
                intro,
                entry,
                render_template=render_template,
            )
            plain_separator = "\n" if i == 1 else "\n\n"
            rich_separator = "\n\u200b" if i == 1 else "\n\n\u200b"

            if self.entry_needs_rich_preview(entry):
                pending_text_parts.append(rich_separator)
                flush_pending_text()

                preview_result = self.build_entry_preview_result(event, intro, entry, render_template=render_template)
                if preview_result and preview_result.chain:
                    chain.extend(preview_result.chain)
                else:
                    chain.append(Plain(intro.rstrip("\n")))
            else:
                pending_text_parts.append(plain_separator)
                pending_text_parts.append(preview_text)

        flush_pending_text()
        return MessageEventResult(chain=chain)

    async def send_entry_reply(
        self,
        event: AstrMessageEvent,
        entry: dict,
        delay: int = 0,
        use_quote: bool = True,
        rule_cfg: dict | None = None,
    ):
        chunks = self.build_entry_message_chunks(
            event,
            entry,
            use_quote=use_quote,
            render_template=True,
            rule_cfg=rule_cfg,
        )
        forwards = list(entry.get("forwards", []))
        if not chunks and not forwards:
            return

        if delay > 0 and event.get_platform_name() == "aiocqhttp":
            sent_any = False
            try:
                client = event.bot
                group_id = event.get_group_id()
                user_id = event.get_sender_id()
                message_ids = []

                for chunk in chunks:
                    message = []
                    for comp in chunk:
                        if isinstance(comp, Plain):
                            message.append({"type": "text", "data": {"text": comp.text}})
                        elif isinstance(comp, At):
                            message.append({"type": "at", "data": {"qq": str(comp.qq)}})
                        elif isinstance(comp, Face):
                            message.append({"type": "face", "data": {"id": comp.id}})
                        elif isinstance(comp, Image):
                            if comp.file:
                                message.append({"type": "image", "data": {"file": self._component_file_to_onebot_file(comp.file)}})
                            elif comp.url:
                                message.append({"type": "image", "data": {"file": comp.url}})
                        elif isinstance(comp, Record):
                            message.append({"type": "record", "data": {"file": self._component_file_to_onebot_file(comp.file)}})
                        elif isinstance(comp, Video):
                            message.append({"type": "video", "data": {"file": self._component_file_to_onebot_file(comp.file)}})
                        elif isinstance(comp, Reply):
                            message.append({"type": "reply", "data": {"id": comp.id}})

                    if group_id:
                        ret = await client.api.call_action("send_group_msg", group_id=int(group_id), message=message)
                    else:
                        actual_delay = min(delay, 115) if delay >= 120 else delay
                        ret = await client.api.call_action("send_private_msg", user_id=int(user_id), message=message)
                        delay = actual_delay
                    sent_any = True
                    message_id = ret.get("message_id")
                    if message_id:
                        message_ids.append(message_id)

                for forward in forwards:
                    forward_message_id = await self._send_forward_reply(
                        event, forward, delay=0
                    )
                    sent_any = bool(forward_message_id) or sent_any
                    if forward_message_id > 0:
                        message_ids.append(forward_message_id)

                if message_ids:
                    try:
                        await asyncio.sleep(delay)
                        for message_id in message_ids:
                            await client.api.call_action("delete_msg", message_id=message_id)
                    except Exception as e:
                        logger.error(f"撤回消息失败: {e}")
                return
            except Exception as e:
                logger.error(f"发送消息失败: {e}")
                if sent_any:
                    return

        for chunk in chunks:
            await event.send(MessageEventResult(chain=chunk))
        for forward in forwards:
            await self._send_forward_reply(event, forward, delay=delay)

    async def send_entries_forward_reply(
        self,
        event: AstrMessageEvent,
        entries: list[dict],
        delay: int = 0,
        rule_cfg: dict | None = None,
    ):
        if not entries:
            return False

        self_id, node_name = await self.get_forward_bot_identity(event)
        nodes = []
        for entry in entries:
            chunks = self.build_entry_message_chunks(
                event,
                entry,
                use_quote=False,
                render_template=True,
                rule_cfg=rule_cfg,
            )
            for chunk in chunks:
                if chunk:
                    nodes.append(Node(uin=self_id, name=node_name, content=chunk))

        if not nodes:
            return False

        try:
            group_id = event.get_group_id()
            if not group_id:
                return False

            bot = getattr(event, "bot", None)
            if bot is None:
                platform_inst = self.plugin.context.get_platform_inst(event.get_platform_id())
                if platform_inst is not None:
                    if hasattr(platform_inst, "get_client"):
                        try:
                            bot = platform_inst.get_client()
                        except Exception:
                            bot = None
                    if bot is None and hasattr(platform_inst, "bot"):
                        bot = platform_inst.bot

            if bot is None or not hasattr(bot, "call_action"):
                return False

            payload = await Nodes(nodes).to_dict()
            ret = await bot.call_action(
                "send_group_forward_msg",
                group_id=int(group_id),
                messages=payload.get("messages", []),
            )

            message_id = 0
            if isinstance(ret, dict):
                message_id = int(ret.get("message_id") or 0)

            if delay > 0 and message_id > 0:
                actual_delay = min(delay, 115) if delay >= 120 else delay
                await asyncio.sleep(actual_delay)
                await bot.call_action("delete_msg", message_id=message_id)
            return True
        except Exception as exc:
            logger.error(f"发送 QQ 合并转发回复失败: {exc}", exc_info=True)
            return False

    def is_safe_regex(self, pattern: str) -> bool:
        dangerous_patterns = [
            r"\(\?\:",
            r"\(\?\!",
            r"\(\?\<",
            r"\*\+",
            r"\+\*",
            r"\*\*",
            r"\+\+",
            r"\((?:[^()]*[+*{][^()]*)\)\s*\+",
            r"\{[^{}]*\}[^{}]*\{[^{}]*\}",
        ]

        if len(pattern) > 100:
            return False

        for dangerous in dangerous_patterns:
            if re.search(dangerous, pattern):
                return False

        return True
