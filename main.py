from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register, StarTools
from astrbot.api import logger
from astrbot.api.message_components import *
import os
import json
import re
import aiohttp
import hashlib
import asyncio
from datetime import datetime

from .modules.command_triggered import CommandTriggeredModule
from .modules.auto_detect import AutoDetectModule

@register("astrbot_plugin_keywords_reply", "Foolllll", "支持图文回复、正则匹配关键词和灵活管理的关键词回复插件。", "v1.2.0", "https://github.com/Foolllll-J/astrbot_plugin_keywords_reply")
class KeywordsReplyPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config or {}
        self.data_dir = StarTools.get_data_dir("astrbot_plugin_keywords_reply")
        self.image_dir = os.path.join(self.data_dir, "images")
        self.data_file = os.path.join(self.data_dir, "keywords.json")
        
        os.makedirs(self.image_dir, exist_ok=True)
        
        self._save_lock = asyncio.Lock()
        self._regex_cache = {}
        self.data = self._normalize_data(self._load_data())
        self.data_version = 1
        self.cmd_module = CommandTriggeredModule(self)
        self.detect_module = AutoDetectModule(self)
        
    def _normalize_data(self, data: dict) -> dict:
        """确保数据结构完整，避免旧版本数据缺字段导致异常。"""
        if not isinstance(data, dict):
            return {"command_triggered": [], "auto_detect": []}
        data.setdefault("command_triggered", [])
        data.setdefault("auto_detect", [])
        return data

    def _load_data(self):
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载关键词数据失败: {e}")
        return {"command_triggered": [], "auto_detect": []}

    async def _save_data_async(self):
        tmp_file = f"{self.data_file}.tmp"
        async with self._save_lock:
            self.data_version += 1
            self._regex_cache.clear()
            try:
                payload = json.dumps(self.data, ensure_ascii=False, indent=2)
                with open(tmp_file, "w", encoding="utf-8") as f:
                    f.write(payload)
                os.replace(tmp_file, self.data_file)
            except Exception as e:
                logger.error(f"保存关键词数据失败: {e}")
                try:
                    if os.path.exists(tmp_file):
                        os.remove(tmp_file)
                except Exception:
                    pass
                return

        self._cleanup_unused_images()

    def _save_data(self):
        """兼容旧调用，建议在协程中改用 _save_data_async。"""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._save_data_async())
        except RuntimeError:
            asyncio.run(self._save_data_async())

    def _collect_referenced_images(self) -> set[str]:
        refs = set()
        for section in ("command_triggered", "auto_detect"):
            for cfg in self.data.get(section, []):
                for entry in cfg.get("entries", []):
                    for image in entry.get("images", []):
                        path = image.get("path")
                        if path:
                            refs.add(os.path.basename(path))
        return refs

    def _cleanup_unused_images(self):
        """清理不再被任何词条引用的本地图片。"""
        try:
            referenced = self._collect_referenced_images()
            removed = 0
            for name in os.listdir(self.image_dir):
                full_path = os.path.join(self.image_dir, name)
                if not os.path.isfile(full_path):
                    continue
                if name not in referenced:
                    os.remove(full_path)
                    removed += 1
            if removed > 0:
                logger.info(f"已清理未引用图片: {removed} 个")
        except Exception as e:
            logger.error(f"清理未引用图片失败: {e}")

    def _permission_denied_result(self, event: AstrMessageEvent, message: str = "权限不足。"):
        if self.config.get("notify_permission_denied", True):
            return event.plain_result(message)
        return None

    def _get_compiled_regex(self, scope: str, pattern: str, flags: int = 0):
        cache_key = (scope, pattern, flags)
        compiled = self._regex_cache.get(cache_key)
        if compiled is not None:
            return compiled
        try:
            compiled = re.compile(pattern, flags)
            self._regex_cache[cache_key] = compiled
            return compiled
        except Exception as e:
            logger.error(f"正则表达式编译失败 ({scope}: {pattern}): {e}")
            return None

    def _build_template_context(self, event: AstrMessageEvent) -> dict:
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

    def _render_template_text(self, event: AstrMessageEvent, text: str) -> str:
        if not text:
            return text
        if not self.config.get("enable_text_template", True):
            return text
        context = self._build_template_context(event)
        pattern = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
        return pattern.sub(lambda m: str(context.get(m.group(1), m.group(0))), text)

    async def _download_image(self, url: str) -> str:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        filename = hashlib.md5(content).hexdigest() + ".jpg"
                        path = os.path.join(self.image_dir, filename)
                        with open(path, "wb") as f:
                            f.write(content)
                        return path
        except Exception as e:
            logger.error(f"下载图片失败: {e}")
        return None

    def _is_admin(self, event: AstrMessageEvent):
        if event.is_admin():
            return True
        sender_id = str(event.get_sender_id())
        whitelist = {str(uid) for uid in self.config.get("whitelist", [])}
        return sender_id in whitelist

    def _parse_message_to_entry(self, components):
        text_parts = []
        images = []
        for comp in components:
            if isinstance(comp, Plain):
                text_parts.append(comp.text)
            elif isinstance(comp, Image):
                images.append({"url": comp.url, "file": comp.file, "path": comp.path})
        
        entry = {
            "text": "".join(text_parts).strip(),
            "images": images
        }
        return entry, len(images) > 0

    async def _process_entry_images(self, entry):
        processed_images = []
        for item in entry.get("images", []):
            url = item.get("url")
            path = item.get("path")
            # 如果是本地路径且在我们的图片目录下，只保留文件名
            if path and os.path.exists(path) and self.image_dir in path:
                processed_images.append({"path": os.path.basename(path)})
            elif url:
                local_path = await self._download_image(url)
                if local_path:
                    processed_images.append({"path": os.path.basename(local_path)})
                else:
                    processed_images.append(item)
            else:
                processed_images.append(item)
        
        entry["images"] = processed_images
        return entry

    def _get_reply_result(self, event: AstrMessageEvent, entry: dict, use_quote: bool = False, render_template: bool = True):
        try:
            chain = []
            
            if use_quote and self.config.get("quote_reply", False) and event.message_obj and event.message_obj.message_id:
                chain.append(Reply(id=event.message_obj.message_id))
            
            if entry.get("text"):
                text = entry["text"]
                if render_template:
                    text = self._render_template_text(event, text)
                chain.append(Plain(text))
            
            for img in entry.get("images", []):
                path = img.get("path")
                if path:
                    full_path = os.path.join(self.image_dir, path)
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

    def _is_safe_regex(self, pattern: str) -> bool:
        dangerous_patterns = [
            r'\(\?\:',
            r'\(\?\!',
            r'\(\?\<',
            r'\*\+',
            r'\+\*',
            r'\*\*',
            r'\+\+',
            r'\((?:[^()]*[+*{][^()]*)\)\s*\+',
            r'\{[^{}]*\}[^{}]*\{[^{}]*\}',
        ]
        
        if len(pattern) > 100:
            return False
            
        for dangerous in dangerous_patterns:
            if re.search(dangerous, pattern):
                return False
                
        return True

    @filter.command("添加关键词")
    async def add_keyword_cmd(self, event: AstrMessageEvent):
        """添加新关键词和回复。用法: /添加关键词 <关键词> <回复内容(支持图片)>"""
        try:
            async for res in self.cmd_module.add_item(event):
                yield res
        except Exception as e:
            logger.error(f"添加关键词异常: {e}", exc_info=True)
            yield event.plain_result(f"添加关键词时发生错误: {e}")

    @filter.command("编辑关键词")
    async def edit_keyword_cmd(self, event: AstrMessageEvent):
        """修改关键词触发词。用法: /编辑关键词 <序号或旧关键词> <新关键词>"""
        try:
            async for res in self.cmd_module.edit_item(event):
                yield res
        except Exception as e:
            logger.error(f"编辑关键词异常: {e}", exc_info=True)
            yield event.plain_result(f"编辑关键词时发生错误: {e}")

    @filter.command("删除关键词")
    async def del_keyword_cmd(self, event: AstrMessageEvent):
        """删除关键词及其所有回复。用法: /删除关键词 <序号或关键词内容>"""
        try:
            async for res in self.cmd_module.del_items(event):
                yield res
        except Exception as e:
            logger.error(f"删除关键词异常: {e}", exc_info=True)
            yield event.plain_result(f"删除关键词时发生错误: {e}")

    @filter.command("启用关键词")
    async def enable_keyword_cmd(self, event: AstrMessageEvent):
        """在指定群聊或全局启用关键词。用法: /启用关键词 <序号或内容> [群号/全局]"""
        try:
            async for res in self.cmd_module.toggle_groups(event, True):
                yield res
        except Exception as e:
            logger.error(f"启用关键词异常: {e}", exc_info=True)
            yield event.plain_result(f"启用关键词时发生错误: {e}")

    @filter.command("禁用关键词")
    async def disable_keyword_cmd(self, event: AstrMessageEvent):
        """在指定群聊或全局禁用关键词。用法: /禁用关键词 <序号或内容> [群号/全局]"""
        try:
            async for res in self.cmd_module.toggle_groups(event, False):
                yield res
        except Exception as e:
            logger.error(f"禁用关键词异常: {e}", exc_info=True)
            yield event.plain_result(f"禁用关键词时发生错误: {e}")

    @filter.command("查看关键词列表", alias=["查看所有关键词"])
    async def list_keywords_cmd(self, event: AstrMessageEvent):
        """列出所有关键词。用法: /查看关键词列表"""
        try:
            async for res in self.cmd_module.list_items(event):
                yield res
        except Exception as e:
            logger.error(f"查看关键词列表异常: {e}", exc_info=True)
            yield event.plain_result(f"查看关键词列表时发生错误: {e}")

    @filter.command("查看关键词")
    async def view_keyword_cmd(self, event: AstrMessageEvent):
        """查看关键词详情。用法: /查看关键词 <序号或内容>"""
        try:
            async for res in self.cmd_module.view_item(event):
                yield res
        except Exception as e:
            logger.error(f"查看关键词异常: {e}", exc_info=True)
            yield event.plain_result(f"查看关键词详情时发生错误: {e}")

    @filter.command("查看关键词回复")
    async def view_keyword_reply_cmd(self, event: AstrMessageEvent):
        """查看指定关键词的某个回复。用法: /查看关键词回复 <关键词序号/内容> [回复序号]"""
        try:
            async for res in self.cmd_module.view_reply(event):
                yield res
        except Exception as e:
            logger.error(f"查看关键词回复异常: {e}", exc_info=True)
            yield event.plain_result(f"查看回复时发生错误: {e}")

    @filter.command("添加关键词回复")
    async def add_keyword_reply_cmd(self, event: AstrMessageEvent):
        """为指定关键词添加新回复。用法: /添加关键词回复 <关键词序号/内容> <新回复内容(支持图片)>"""
        try:
            async for res in self.cmd_module.add_reply(event):
                yield res
        except Exception as e:
            logger.error(f"添加关键词回复异常: {e}", exc_info=True)
            yield event.plain_result(f"添加回复时发生错误: {e}")

    @filter.command("编辑关键词回复")
    async def edit_keyword_reply_cmd(self, event: AstrMessageEvent):
        """修改指定关键词的某个回复条目。用法: /编辑关键词回复 <关键词序号/内容> [回复序号] <新内容>"""
        try:
            async for res in self.cmd_module.edit_reply(event):
                yield res
        except Exception as e:
            logger.error(f"编辑关键词回复异常: {e}", exc_info=True)
            yield event.plain_result(f"编辑回复时发生错误: {e}")

    @filter.command("删除关键词回复")
    async def del_keyword_reply_cmd(self, event: AstrMessageEvent):
        """删除指定关键词的某个回复条目。用法: /删除关键词回复 <关键词序号/内容> [回复序号]"""
        try:
            async for res in self.cmd_module.delete_reply(event):
                yield res
        except Exception as e:
            logger.error(f"删除关键词回复异常: {e}", exc_info=True)
            yield event.plain_result(f"删除回复时发生错误: {e}")

    @filter.command("添加检测词")
    async def add_detect_cmd(self, event: AstrMessageEvent):
        """添加自动监听型检测词。用法: /添加检测词 [-r] <关键词> <回复内容> (-r 表示正则)"""
        try:
            async for res in self.detect_module.add_item(event):
                yield res
        except Exception as e:
            logger.error(f"添加检测词异常: {e}", exc_info=True)
            yield event.plain_result(f"添加检测词时发生错误: {e}")

    @filter.command("编辑检测词")
    async def edit_detect_cmd(self, event: AstrMessageEvent):
        """修改检测词触发词或正则开关。用法: /编辑检测词 [-r] <序号或内容> <新检测词>"""
        try:
            async for res in self.detect_module.edit_item(event):
                yield res
        except Exception as e:
            logger.error(f"编辑检测词异常: {e}", exc_info=True)
            yield event.plain_result(f"编辑检测词时发生错误: {e}")

    @filter.command("删除检测词")
    async def del_detect_cmd(self, event: AstrMessageEvent):
        """删除检测词及其所有回复。用法: /删除检测词 <序号或内容>"""
        try:
            async for res in self.detect_module.del_items(event):
                yield res
        except Exception as e:
            logger.error(f"删除检测词异常: {e}", exc_info=True)
            yield event.plain_result(f"删除检测词时发生错误: {e}")

    @filter.command("启用检测词")
    async def enable_detect_cmd(self, event: AstrMessageEvent):
        """在指定群聊或全局启用检测词。用法: /启用检测词 <序号或内容> [群号/全局]"""
        try:
            async for res in self.detect_module.toggle_groups(event, True):
                yield res
        except Exception as e:
            logger.error(f"启用检测词异常: {e}", exc_info=True)
            yield event.plain_result(f"启用检测词时发生错误: {e}")

    @filter.command("禁用检测词")
    async def disable_detect_cmd(self, event: AstrMessageEvent):
        """在指定群聊或全局禁用检测词。用法: /禁用检测词 <序号或内容> [群号/全局]"""
        try:
            async for res in self.detect_module.toggle_groups(event, False):
                yield res
        except Exception as e:
            logger.error(f"禁用检测词异常: {e}", exc_info=True)
            yield event.plain_result(f"禁用检测词时发生错误: {e}")

    @filter.command("查看检测词列表", alias=["查看所有检测词"])
    async def list_detects_cmd(self, event: AstrMessageEvent):
        """列出所有检测词。用法: /查看检测词列表"""
        try:
            async for res in self.detect_module.list_items(event):
                yield res
        except Exception as e:
            logger.error(f"查看检测词列表异常: {e}", exc_info=True)
            yield event.plain_result(f"查看检测词列表时发生错误: {e}")

    @filter.command("查看检测词")
    async def view_detect_cmd(self, event: AstrMessageEvent):
        """查看检测词详情。用法: /查看检测词 <序号或内容>"""
        try:
            async for res in self.detect_module.view_item(event):
                yield res
        except Exception as e:
            logger.error(f"查看检测词异常: {e}", exc_info=True)
            yield event.plain_result(f"查看检测词详情时发生错误: {e}")

    @filter.command("查看检测词回复")
    async def view_detect_reply_cmd(self, event: AstrMessageEvent):
        """查看指定检测词的某个回复。用法: /查看检测词回复 <检测词序号/内容> [回复序号]"""
        try:
            async for res in self.detect_module.view_reply(event):
                yield res
        except Exception as e:
            logger.error(f"查看检测词回复异常: {e}", exc_info=True)
            yield event.plain_result(f"查看回复时发生错误: {e}")

    @filter.command("添加检测词回复")
    async def add_detect_reply_cmd(self, event: AstrMessageEvent):
        """为指定检测词添加新回复。用法: /添加检测词回复 <检测词序号/内容> <新回复内容(支持图片)>"""
        try:
            async for res in self.detect_module.add_reply(event):
                yield res
        except Exception as e:
            logger.error(f"添加检测词回复异常: {e}", exc_info=True)
            yield event.plain_result(f"添加回复时发生错误: {e}")

    @filter.command("编辑检测词回复")
    async def edit_detect_reply_cmd(self, event: AstrMessageEvent):
        """修改指定检测词的某个回复条目。用法: /编辑检测词回复 <检测词序号/内容> [回复序号] <新内容>"""
        try:
            async for res in self.detect_module.edit_reply(event):
                yield res
        except Exception as e:
            logger.error(f"编辑检测词回复异常: {e}", exc_info=True)
            yield event.plain_result(f"编辑回复时发生错误: {e}")

    @filter.command("删除检测词回复")
    async def del_detect_reply_cmd(self, event: AstrMessageEvent):
        """删除指定检测词的某个回复条目。用法: /删除检测词回复 <检测词序号/内容> [回复序号]"""
        try:
            async for res in self.detect_module.delete_reply(event):
                yield res
        except Exception as e:
            logger.error(f"删除检测词回复异常: {e}", exc_info=True)
            yield event.plain_result(f"删除回复时发生错误: {e}")

    async def _send_and_recall(self, event: AstrMessageEvent, result: MessageEventResult, delay: int):
        if not result: return
        
        if delay > 0 and event.get_platform_name() == "aiocqhttp":
            try:
                client = event.bot
                group_id = event.get_group_id()
                user_id = event.get_sender_id()
                
                # 构造消息
                message = []
                for comp in result.chain:
                    if isinstance(comp, Plain):
                        message.append({"type": "text", "data": {"text": comp.text}})
                    elif isinstance(comp, Image):
                        if comp.file:
                            # 转换为绝对路径
                            abs_path = os.path.abspath(comp.file)
                            message.append({"type": "image", "data": {"file": f"file:///{abs_path}"}})
                        elif comp.url:
                            message.append({"type": "image", "data": {"file": comp.url}})
                    elif isinstance(comp, Reply):
                        message.append({"type": "reply", "data": {"id": comp.id}})
                
                if group_id:
                    ret = await client.api.call_action("send_group_msg", group_id=int(group_id), message=message)
                else:
                    if delay >= 120:
                        logger.warning(f"私聊环境撤回延迟不能超过 120 秒，已自动调整为 115 秒。")
                        delay = 115
                    ret = await client.api.call_action("send_private_msg", user_id=int(user_id), message=message)
                
                message_id = ret.get("message_id")
                if message_id:
                    await asyncio.sleep(delay)
                    await client.api.call_action("delete_msg", message_id=message_id)
            except Exception as e:
                logger.error(f"发送或撤回消息失败: {e}")
        else:
            # 非 aiocqhttp 平台或无延迟，直接发送
            await event.send(result)

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        """处理所有消息事件，包括命令触发和自动检测。"""
        msg = event.message_str.strip()
        if not msg: return
        
        management_prefixes = ["/添加", "/编辑", "/删除", "/启用", "/禁用", "/查看", "添加", "编辑", "删除", "启用", "禁用", "查看"]
        if any(msg.startswith(p) for p in management_prefixes):
            return
            
        recall_delay = self.config.get("recall_delay", "0 0").split()
        kw_delay = int(recall_delay[0]) if len(recall_delay) > 0 else 0
        dt_delay = int(recall_delay[1]) if len(recall_delay) > 1 else 0

        res = await self.cmd_module.handle_message(event)
        if res:
            if kw_delay > 0:
                await self._send_and_recall(event, res, kw_delay)
                event.stop_event()
            else:
                yield res
                event.stop_event()
            return

        res = await self.detect_module.handle_message(event)
        if res:
            if dt_delay > 0:
                await self._send_and_recall(event, res, dt_delay)
                event.stop_event()
            else:
                yield res
                event.stop_event()
            return
