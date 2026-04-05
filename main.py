from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register, StarTools
from astrbot.api import logger
import os
import asyncio

from .modules.command_triggered import CommandTriggeredModule
from .modules.auto_detect import AutoDetectModule
from .modules.utils import PluginUtils

class KeywordsReplyPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config or {}
        self.data_dir = StarTools.get_data_dir("astrbot_plugin_keywords_reply")
        self.image_dir = os.path.join(self.data_dir, "images")
        self.record_dir = os.path.join(self.data_dir, "records")
        self.video_dir = os.path.join(self.data_dir, "videos")
        self.data_file = os.path.join(self.data_dir, "keywords.json")
        
        os.makedirs(self.image_dir, exist_ok=True)
        os.makedirs(self.record_dir, exist_ok=True)
        os.makedirs(self.video_dir, exist_ok=True)
        
        self._save_lock = asyncio.Lock()
        self._regex_cache = {}
        self.utils = PluginUtils(self)
        self.data = self.utils.normalize_data(self.utils.load_data())
        self.data_version = 1
        self.cmd_module = CommandTriggeredModule(self)
        self.detect_module = AutoDetectModule(self)
        
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
        """查看指定关键词的某个回复。用法: /查看关键词回复 <关键词序号/内容> [回复序号]。语音/视频会另行发送。"""
        try:
            async for res in self.cmd_module.view_reply(event):
                yield res
        except Exception as e:
            logger.error(f"查看关键词回复异常: {e}", exc_info=True)
            yield event.plain_result(f"查看回复时发生错误: {e}")

    @filter.command("添加关键词回复")
    async def add_keyword_reply_cmd(self, event: AstrMessageEvent):
        """为指定关键词添加新回复。用法: /添加关键词回复 <关键词序号/内容> [新回复内容]。可直接引用一条消息作为回复内容。"""
        try:
            async for res in self.cmd_module.add_reply(event):
                yield res
        except Exception as e:
            logger.error(f"添加关键词回复异常: {e}", exc_info=True)
            yield event.plain_result(f"添加回复时发生错误: {e}")

    @filter.command("编辑关键词回复")
    async def edit_keyword_reply_cmd(self, event: AstrMessageEvent):
        """修改指定关键词的某个回复条目。用法: /编辑关键词回复 <关键词序号/内容> [回复序号] [新内容]。可直接引用一条消息作为新内容。"""
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
        """为指定检测词添加新回复。用法: /添加检测词回复 <检测词序号/内容> [新回复内容]。可直接引用一条消息作为回复内容。"""
        try:
            async for res in self.detect_module.add_reply(event):
                yield res
        except Exception as e:
            logger.error(f"添加检测词回复异常: {e}", exc_info=True)
            yield event.plain_result(f"添加回复时发生错误: {e}")

    @filter.command("编辑检测词回复")
    async def edit_detect_reply_cmd(self, event: AstrMessageEvent):
        """修改指定检测词的某个回复条目。用法: /编辑检测词回复 <检测词序号/内容> [回复序号] [新内容]。可直接引用一条消息作为新内容。"""
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

        entry = await self.cmd_module.handle_message(event)
        if entry:
            if isinstance(entry, list):
                sent = await self.utils.send_entries_forward_reply(event, entry, kw_delay)
                if not sent:
                    await self.utils.send_entry_reply(event, entry[0], kw_delay, use_quote=True)
            else:
                await self.utils.send_entry_reply(event, entry, kw_delay, use_quote=True)
            event.stop_event()
            return

        entry = await self.detect_module.handle_message(event)
        if entry:
            if isinstance(entry, list):
                sent = await self.utils.send_entries_forward_reply(event, entry, dt_delay)
                if not sent:
                    await self.utils.send_entry_reply(event, entry[0], dt_delay, use_quote=True)
            else:
                await self.utils.send_entry_reply(event, entry, dt_delay, use_quote=True)
            event.stop_event()
            return
