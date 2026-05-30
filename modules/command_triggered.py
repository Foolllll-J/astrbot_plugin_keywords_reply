import re
import random
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Plain
from ..webui.payloads import get_effective_bool

class CommandTriggeredModule:
    def __init__(self, plugin):
        self.plugin = plugin
        self.data_key = "command_triggered"
        self._cache_version = -1
        self._exact_index_cs = {}
        self._exact_index_ci = {}
        self._regex_indices = []

    def _permission_denied_result(self, event: AstrMessageEvent, message: str = "权限不足。"):
        return self.plugin.utils.permission_denied_result(event, message)

    def _is_enabled_in_group(self, cfg: dict, group_id: str) -> bool:
        if not cfg.get("enabled", True):
            return False
        mode = cfg.get("mode", "whitelist")
        groups = cfg.get("groups", [])
        if mode == "whitelist":
            return group_id in groups
        return group_id not in groups

    def _keyword_equals(self, left: str, right: str, is_regex: bool = False) -> bool:
        """关键词内容比较：仅对非正则关键词应用 case_sensitive 配置。"""
        if is_regex or get_effective_bool(
            self.plugin, None, "case_sensitive_override", "case_sensitive"
        ):
            return left == right
        return left.lower() == right.lower()

    def _ensure_match_index(self):
        if self._cache_version == self.plugin.data_version:
            return

        self._exact_index_cs = {}
        self._exact_index_ci = {}
        self._regex_indices = []
        data = self.plugin.data[self.data_key]
        for idx, cfg in enumerate(data):
            keyword = cfg.get("keyword")
            if not keyword:
                continue
            if cfg.get("regex", False):
                self._regex_indices.append(idx)
                continue
            self._exact_index_cs.setdefault(keyword, []).append(idx)
            self._exact_index_ci.setdefault(keyword.lower(), []).append(idx)

        self._cache_version = self.plugin.data_version

    def _match_keyword(self, text, keyword_cfg):
        keyword = keyword_cfg["keyword"]
        is_regex = keyword_cfg.get("regex", False)

        if is_regex:
            # 正则模式不受全局 case_sensitive 配置影响，大小写由正则本身控制。
            compiled = self.plugin.utils.get_compiled_regex(self.data_key, keyword, 0)
            if compiled is None:
                return False
            return compiled.fullmatch(text) is not None
        else:
            case_sensitive = get_effective_bool(
                self.plugin, keyword_cfg, "case_sensitive_override", "case_sensitive"
            )
            if not case_sensitive:
                text = text.lower()
                keyword = keyword.lower()
            return text == keyword

    async def handle_message(self, event: AstrMessageEvent):
        if not event.is_at_or_wake_command:
            return None

        if not event.get_group_id():
            return None
            
        msg_str = event.message_str.strip()
        if not msg_str:
            return None
            
        potential_cmd = msg_str.split()[0]
        group_id = event.get_group_id()

        self._ensure_match_index()
        candidate_indices = []
        candidate_indices.extend(self._exact_index_cs.get(potential_cmd, []))
        candidate_indices.extend(self._exact_index_ci.get(potential_cmd.lower(), []))
        candidate_indices.extend(self._regex_indices)

        checked = set()
        data = self.plugin.data[self.data_key]
        for idx in sorted(candidate_indices):
            if idx in checked:
                continue
            checked.add(idx)
            cfg = data[idx]
            if cfg.get("regex", False) and not self._match_keyword(potential_cmd, cfg):
                continue

            if not cfg.get("enabled", True):
                continue

            mode = cfg.get("mode", "whitelist")
            groups = cfg.get("groups", [])

            if group_id:
                if mode == "whitelist":
                    if group_id not in groups:
                        continue
                else: # blacklist
                    if group_id in groups:
                        continue

            logger.info(f"关键词触发: {potential_cmd} (来自: {event.get_sender_id()})")
            if not cfg["entries"]:
                return None
            if self.plugin.utils.should_use_forwarded_replies(
                event, cfg["entries"], rule_cfg=cfg
            ):
                return {"payload": list(cfg["entries"]), "rule": cfg}
            entry = random.choice(cfg["entries"])
            return {"payload": entry, "rule": cfg}
        return None

    def _find_indices(self, param: str) -> list[int]:
        data = self.plugin.data[self.data_key]
        if not data:
            return []

        try:
            indices = []
            parts = param.split(',')
            for part in parts:
                if '-' in part:
                    start, end = map(int, part.split('-'))
                    indices.extend(range(start-1, end))
                else:
                    indices.append(int(part)-1)
            
            valid_indices = [i for i in indices if 0 <= i < len(data)]
            if valid_indices:
                return valid_indices
        except ValueError:
            pass

        indices = []
        for i, cfg in enumerate(data):
            if self._keyword_equals(cfg["keyword"], param, cfg.get("regex", False)):
                indices.append(i)
        
        return indices

    def _strip_components(self, components, keyword, remaining):
        """从组件列表中剥离命令和关键词，保留回复内容。"""
        reply_components = []
        for i, comp in enumerate(components):
            if isinstance(comp, Plain):
                text = comp.text
                k_idx = text.find(keyword)
                search_start = k_idx + len(keyword) if k_idx != -1 else 0
                
                if remaining:
                    r_idx = text.find(remaining, search_start)
                    if r_idx != -1:
                        reply_components.append(Plain(text[r_idx:]))
                        reply_components.extend(components[i+1:])
                        return reply_components
                
                if k_idx != -1:
                    after_keyword = text[search_start:].lstrip()
                    if after_keyword:
                        reply_components.append(Plain(after_keyword))
                    reply_components.extend(components[i+1:])
                    return reply_components
        return components[1:] if components else []

    async def add_item(self, event: AstrMessageEvent):
        if not self.plugin.utils.is_admin(event):
            denied = self._permission_denied_result(event)
            if denied:
                yield denied
            return

        full_text = event.message_str.strip()
        parts = full_text.split(None, 1)
        if len(parts) < 2:
            yield event.plain_result("格式错误。用法: /添加关键词 [-r] <关键词> <回复内容>")
            return
            
        args_text = parts[1].lstrip()
        
        is_regex = False
        if args_text.startswith("-r"):
            is_regex = True
            args_text = args_text[2:].lstrip()
            
        if not args_text:
            yield event.plain_result("格式错误。用法: /添加关键词 [-r] <关键词> <回复内容>")
            return

        match = re.search(r'\s+', args_text)
        if match:
            keyword = args_text[:match.start()]
            remaining = args_text[match.end():]
        else:
            keyword = args_text
            remaining = ""

        if not keyword:
            yield event.plain_result("关键词不能为空。")
            return

        if is_regex:
            if not self.plugin.utils.is_safe_regex(keyword):
                yield event.plain_result("正则表达式存在安全风险，请简化后重试。")
                return
            try:
                re.compile(keyword)
            except Exception as e:
                yield event.plain_result(f"无效的正则表达式: {e}")
                return

        components = event.get_messages()
        reply_components = self._strip_components(components, keyword, remaining)
        
        entry, has_media = self.plugin.utils.parse_message_to_entry(reply_components)
        reply_entry = await self.plugin.utils.fetch_reply_entry(event)
        entry = self.plugin.utils.merge_entries(entry, reply_entry)
        if not self.plugin.utils.entry_has_payload(entry):
            yield event.plain_result("回复内容不能为空。")
            return

        keyword_cfg = next(
            (
                item
                for item in self.plugin.data[self.data_key]
                if self._keyword_equals(item["keyword"], keyword, item.get("regex", False))
            ),
            None,
        )
        
        current_group_id = event.get_group_id()
        is_group = event.get_platform_name() != "private"
        
        if keyword_cfg:
            processed_entry = await self.plugin.utils.process_entry_media(entry)
            keyword_cfg["entries"].append(processed_entry)
            keyword_cfg["regex"] = is_regex
            status_msg = f"已为现有关键词添加新回复（当前共有 {len(keyword_cfg['entries'])} 个回复）。"
        else:
            processed_entry = await self.plugin.utils.process_entry_media(entry)
            
            if is_group and current_group_id:
                enabled = True
                mode = "whitelist"
                groups = [current_group_id]
                status_msg = f"已成功添加关键词，并在当前群聊启用。"
            else:
                enabled = False
                mode = "whitelist"
                groups = []
                status_msg = "已成功添加关键词。由于在非群聊环境创建，已默认全局禁用。"
            
            keyword_cfg = {
                "keyword": keyword,
                "entries": [processed_entry],
                "regex": is_regex,
                "enabled": enabled,
                "mode": mode,
                "groups": groups
            }
            self.plugin.data[self.data_key].append(keyword_cfg)

        await self.plugin.utils.save_data_async()
        logger.info(f"添加关键词: {keyword} (操作者: {event.get_sender_id()})")
        
        yield event.plain_result(f"成功操作关键词: {keyword}\n{status_msg}")

    async def edit_item(self, event: AstrMessageEvent):
        if not self.plugin.utils.is_admin(event):
            denied = self._permission_denied_result(event, "只有管理员或白名单用户可以执行此操作。")
            if denied:
                yield denied
            return
            
        msg_parts = event.message_str.strip().split()
        if len(msg_parts) < 3:
            yield event.plain_result("格式错误。用法: /编辑关键词 [-r] <序号或内容> <新关键词>")
            return

        is_regex = False
        idx_param = ""
        new_keyword = ""

        if msg_parts[1] == "-r":
            is_regex = True
            if len(msg_parts) < 4:
                yield event.plain_result("格式错误。用法: /编辑关键词 -r <序号或内容> <新关键词>")
                return
            idx_param = msg_parts[2]
            new_keyword = msg_parts[3]
        else:
            idx_param = msg_parts[1]
            new_keyword = msg_parts[2]

        indices = self._find_indices(idx_param)
        if not indices:
            yield event.plain_result(f"未找到匹配 '{idx_param}' 的关键词。")
            return
        
        idx = indices[0]
        
        if is_regex:
            try:
                re.compile(new_keyword)
            except Exception as e:
                yield event.plain_result(f"无效的正则表达式: {e}")
                return
        
        if 0 <= idx < len(self.plugin.data[self.data_key]):
            old_keyword = self.plugin.data[self.data_key][idx]["keyword"]
            self.plugin.data[self.data_key][idx]["keyword"] = new_keyword
            self.plugin.data[self.data_key][idx]["regex"] = is_regex
            await self.plugin.utils.save_data_async()
            logger.info(f"编辑关键词: {old_keyword} -> {new_keyword} (操作者: {event.get_sender_id()})")
            yield event.plain_result(f"关键词 '{old_keyword}' 已修改为 '{new_keyword}'。")
        else:
            yield event.plain_result("序号无效。")

    async def del_items(self, event: AstrMessageEvent):
        if not self.plugin.utils.is_admin(event):
            denied = self._permission_denied_result(event)
            if denied:
                yield denied
            return
            
        parts = event.message_str.strip().split(None, 1)
        if len(parts) < 2:
            yield event.plain_result("格式错误。用法: /删除关键词 <序号或关键词内容>")
            return
            
        param = parts[1]
        indices = self._find_indices(param)
        
        if not indices:
            yield event.plain_result(f"未找到匹配 '{param}' 的关键词。")
            return

        try:
            indices.sort(reverse=True)
            deleted_keywords = []
            for idx in indices:
                cfg = self.plugin.data[self.data_key].pop(idx)
                deleted_keywords.append(cfg['keyword'])
            
            await self.plugin.utils.save_data_async()
            logger.info(f"删除关键词: {', '.join(deleted_keywords)} (操作者: {event.get_sender_id()})")
            yield event.plain_result(f"关键词 '{', '.join(deleted_keywords)}' 已删除。")
        except Exception as e:
            logger.error(f"删除关键词异常: {e}")
            yield event.plain_result(f"操作失败: {e}")

    async def toggle_groups(self, event: AstrMessageEvent, enable: bool):
        if not self.plugin.utils.is_admin(event):
            denied = self._permission_denied_result(event)
            if denied:
                yield denied
            return
            
        parts = event.message_str.strip().split()
        cmd_name = "启用" if enable else "禁用"
        if len(parts) < 2:
            yield event.plain_result(f"格式错误。用法: /{cmd_name}关键词 <序号或关键词内容> [群号1] [群号2] ...")
            return
            
        param = parts[1]
        indices = self._find_indices(param)
        
        if not indices:
            yield event.plain_result(f"未找到匹配 '{param}' 的关键词。")
            return

        args = parts[2:]
        for idx in indices:
            cfg = self.plugin.data[self.data_key][idx]
            
            current_group_id = event.get_group_id()
            is_group = event.get_platform_name() != "private"

            if enable:
                if not args:
                    if is_group and current_group_id:
                        if cfg["mode"] == "blacklist":
                            if current_group_id in cfg["groups"]:
                                cfg["groups"].remove(current_group_id)
                        else:
                            if current_group_id not in cfg["groups"]:
                                cfg["groups"].append(current_group_id)
                        cfg["enabled"] = True
                        groups_str = f"当前群聊 ({current_group_id})"
                    else:
                        yield event.plain_result("当前不在群聊中，请指定群号或使用'全局'参数。")
                        return
                elif args[0] == "全局":
                    cfg["enabled"] = True
                    cfg["mode"] = "blacklist"
                    cfg["groups"] = []
                    groups_str = "全局 (所有群聊)"
                else:
                    if cfg["mode"] != "whitelist":
                        cfg["mode"] = "whitelist"
                        cfg["groups"] = []
                    
                    for gid in args:
                        if not gid.isdigit():
                            yield event.plain_result(f"群号格式错误: {gid}")
                            return
                        if gid not in cfg["groups"]:
                            cfg["groups"].append(gid)
                    groups_str = ", ".join(args)
                    cfg["enabled"] = True
            else: # 禁用
                if not args:
                    if is_group and current_group_id:
                        if cfg["mode"] != "blacklist":
                            cfg["mode"] = "blacklist"
                            cfg["groups"] = []
                        if current_group_id not in cfg["groups"]:
                            cfg["groups"].append(current_group_id)
                        groups_str = f"当前群聊 ({current_group_id})"
                        cfg["enabled"] = True
                    else:
                        cfg["enabled"] = False
                        groups_str = "全局"
                elif args[0] == "全局":
                    cfg["enabled"] = False
                    groups_str = "全局"
                else:
                    if cfg["mode"] != "blacklist":
                        cfg["mode"] = "blacklist"
                        cfg["groups"] = []
                    
                    for gid in args:
                        if not gid.isdigit():
                            yield event.plain_result(f"群号格式错误: {gid}")
                            return
                        if gid not in cfg["groups"]:
                            cfg["groups"].append(gid)
                    groups_str = ", ".join(args)
                    cfg["enabled"] = True

            await self.plugin.utils.save_data_async()
            logger.info(f"修改关键词群聊限制: {cfg['keyword']} -> {cmd_name} {groups_str} (操作者: {event.get_sender_id()})")
            yield event.plain_result(f"关键词 '{cfg['keyword']}' {cmd_name} 群聊: {groups_str}")

    async def list_items(self, event):
        if not self.plugin.utils.is_admin(event):
            allow_group_users = self.plugin.config.get("allow_group_member_list_keywords", False)
            group_id = event.get_group_id()
            if not allow_group_users or not group_id:
                denied = self._permission_denied_result(event)
                if denied:
                    yield denied
                return

            enabled_keywords = [
                cfg.get("keyword", "")
                for cfg in self.plugin.data[self.data_key]
                if cfg.get("keyword") and self._is_enabled_in_group(cfg, group_id)
            ]
            res = f"当前群聊({group_id})启用的关键词:\n"
            if not enabled_keywords:
                res += "无"
            else:
                for i, keyword in enumerate(enabled_keywords, 1):
                    res += f"{i}. {keyword}\n"
            yield event.plain_result(res.strip())
            return

        res = "关键词列表:\n"
        if not self.plugin.data[self.data_key]:
            res += "无\n"
        else:
            for i, cfg in enumerate(self.plugin.data[self.data_key], 1):
                regex_str = " [正则]" if cfg.get("regex", False) else ""
                
                enabled = cfg.get("enabled", True)
                mode = cfg.get("mode", "whitelist")
                groups = cfg.get("groups", [])
                
                if not enabled:
                    groups_str = " [全局禁用]"
                else:
                    if mode == "blacklist":
                        if not groups:
                            groups_str = " [全局启用]"
                        else:
                            groups_str = f" [黑名单:{','.join(groups)}]"
                    else: # whitelist
                        if not groups:
                            groups_str = " [未启用]"
                        else:
                            groups_str = f" [白名单:{','.join(groups)}]"
                
                res += f"【{i}】 {cfg['keyword']}{regex_str}{groups_str}\n"
                for j, entry in enumerate(cfg["entries"], 1):
                    content = self.plugin.utils.summarize_entry_for_list(entry, 50)
                    res += f"  └─ {j}. {content}\n"
        yield event.plain_result(res.strip())

    async def view_item(self, event: AstrMessageEvent):
        if not self.plugin.utils.is_admin(event):
            denied = self._permission_denied_result(event)
            if denied:
                yield denied
            return

        parts = event.message_str.strip().split()
        if len(parts) < 2:
            yield event.plain_result("用法: /查看关键词 <序号或关键词内容>")
            return
        
        if len(parts) >= 3:
            async for res in self.view_reply(event):
                yield res
            return
            
        param = parts[1]
        indices = self._find_indices(param)
        
        if not indices:
            yield event.plain_result(f"未找到匹配 '{param}' 的关键词。")
            return
            
        for idx in indices:
            cfg = self.plugin.data[self.data_key][idx]
            entries = cfg.get("entries", [])
            
            if len(entries) == 1:
                entry = entries[0]
                
                enabled = cfg.get("enabled", True)
                mode = cfg.get("mode", "whitelist")
                groups = cfg.get("groups", [])
                
                if not enabled:
                    groups_str = "全局禁用"
                else:
                    if mode == "blacklist":
                        groups_str = "全局启用" if not groups else f"黑名单模式 (禁用群: {', '.join(groups)})"
                    else:
                        groups_str = "未在任何群聊启用" if not groups else f"白名单模式 (允许群: {', '.join(groups)})"

                intro = f"关键词: {cfg['keyword']}\n"
                intro += f"类型: {'正则匹配' if cfg.get('regex') else '精确匹配'}\n"
                intro += f"状态: {groups_str}\n"
                intro += "回复详情：\n"
                async for res in self.plugin.utils.yield_entry_detail_results(event, intro, entry, render_template=False):
                    yield res
            else:
                enabled = cfg.get("enabled", True)
                mode = cfg.get("mode", "whitelist")
                groups = cfg.get("groups", [])
                
                if not enabled:
                    groups_str = "全局禁用"
                else:
                    if mode == "blacklist":
                        groups_str = "全局启用" if not groups else f"黑名单模式 (禁用群: {', '.join(groups)})"
                    else:
                        groups_str = "未在任何群聊启用" if not groups else f"白名单模式 (允许群: {', '.join(groups)})"

                header = f"关键词: {cfg['keyword']}\n"
                header += f"类型: {'正则匹配' if cfg.get('regex') else '精确匹配'}\n"
                header += f"状态: {groups_str}\n"
                header += f"回复数量: {len(entries)}"
                res_obj = self.plugin.utils.build_entries_preview_result(event, header, entries, render_template=False)
                if res_obj and res_obj.chain:
                    yield res_obj
                else:
                    yield event.plain_result(header)


    async def view_reply(self, event: AstrMessageEvent):
        if not self.plugin.utils.is_admin(event):
            denied = self._permission_denied_result(event)
            if denied:
                yield denied
            return

        parts = event.message_str.strip().split()
        if len(parts) < 2:
            yield event.plain_result("用法: /查看关键词回复 <关键词序号/内容> [回复序号]")
            return
        
        try:
            param = parts[1]
            indices = self._find_indices(param)
            if not indices:
                yield event.plain_result(f"未找到匹配 '{param}' 的关键词。")
                return
            
            idx = indices[0]
            cfg = self.plugin.data[self.data_key][idx]
            entries = cfg.get("entries", [])
            
            if len(parts) < 3:
                if len(entries) == 1:
                    reply_idx = 0
                else:
                    yield event.plain_result(f"该关键词有 {len(entries)} 个回复，请指定回复序号。")
                    return
            else:
                try:
                    reply_idx = int(parts[2]) - 1
                except ValueError:
                    yield event.plain_result("回复序号必须是数字。")
                    return
            
            if 0 <= reply_idx < len(entries):
                entry = entries[reply_idx]
                intro = f"关键词 '{cfg['keyword']}' 的第 {reply_idx+1} 个回复：\n\n"
                async for res in self.plugin.utils.yield_entry_detail_results(event, intro, entry, render_template=False):
                    yield res
                return
            else:
                yield event.plain_result("回复序号无效。")
        except Exception as e:
            logger.error(f"查看回复异常: {e}")
            yield event.plain_result(f"操作失败: {e}")

    async def add_reply(self, event: AstrMessageEvent):
        if not self.plugin.utils.is_admin(event):
            denied = self._permission_denied_result(event)
            if denied:
                yield denied
            return

        full_text = event.message_str.strip()
        parts = full_text.split(None, 2)
        if len(parts) < 2:
            yield event.plain_result("用法: /添加关键词回复 <关键词序号/内容> [回复内容]\n可直接引用一条消息作为回复内容，正文可省略。")
            return
            
        param = parts[1]
        indices = self._find_indices(param)
        if not indices:
            yield event.plain_result(f"未找到匹配 '{param}' 的关键词。")
            return
            
        target_idx = indices[0]
        cfg = self.plugin.data[self.data_key][target_idx]
        
        content = parts[2] if len(parts) > 2 else ""
        components = event.get_messages()
        reply_components = self._strip_components(components, param, content)
        
        entry, has_media = self.plugin.utils.parse_message_to_entry(reply_components)
        reply_entry = await self.plugin.utils.fetch_reply_entry(event)
        entry = self.plugin.utils.merge_entries(entry, reply_entry)
        if not self.plugin.utils.entry_has_payload(entry):
            yield event.plain_result("回复内容不能为空。")
            return

        processed_entry = await self.plugin.utils.process_entry_media(entry)
        cfg["entries"].append(processed_entry)
        await self.plugin.utils.save_data_async()
        
        yield event.plain_result(f"已为关键词 '{cfg['keyword']}' 添加新回复（当前共有 {len(cfg['entries'])} 个回复）。")

    async def edit_reply(self, event: AstrMessageEvent):
        if not self.plugin.utils.is_admin(event):
            denied = self._permission_denied_result(event)
            if denied:
                yield denied
            return

        # 格式: /编辑关键词回复 [关键词ID/内容] [回复序号] [新内容]
        # 或: /编辑关键词回复 [关键词ID/内容] [新内容] (当仅有一个回复时)
        full_text = event.message_str.strip()
        parts = full_text.split(None, 3) # 最多拆分4部分: 指令, ID/内容, (序号), 内容
        
        if len(parts) < 2:
            yield event.plain_result("格式错误。用法:\n/编辑关键词回复 <关键词序号/内容> <回复序号> [新内容]\n/编辑关键词回复 <关键词序号/内容> [新内容] (单回复时)\n可直接引用一条消息作为新内容，正文可省略。")
            return

        try:
            param = parts[1]
            indices = self._find_indices(param)
            if not indices:
                yield event.plain_result(f"未找到匹配 '{param}' 的关键词。")
                return
            
            kw_idx = indices[0]
            cfg = self.plugin.data[self.data_key][kw_idx]
            entries = cfg["entries"]
            
            # 判断是标准格式还是简化格式
            components = event.get_messages()
            if len(entries) == 1:
                # 只有一条回复时，优先尝试解析为：指令 ID 序号 内容
                # 但如果 序号 不是 1，或者没有 内容 且没有图片，则视为：指令 ID 内容
                try:
                    reply_idx_val = int(parts[2]) if len(parts) > 2 else None
                    if reply_idx_val == 1 and (len(parts) >= 4 or any(not isinstance(c, Plain) for c in components)):
                        # 标准格式: ID 1 内容
                        reply_idx = 0
                        new_content_raw = parts[3] if len(parts) >= 4 else ""
                    else:
                        # 简化格式: ID 内容
                        reply_idx = 0
                        new_content_raw = full_text.split(None, 2)[2] if len(parts) > 2 else ""
                except (ValueError, IndexError):
                    # 简化格式
                    reply_idx = 0
                    new_content_raw = full_text.split(None, 2)[2] if len(parts) > 2 else ""
            else:
                # 多条回复，必须指定序号
                if len(parts) < 3:
                    yield event.plain_result(f"该关键词有 {len(entries)} 个回复，请指定要编辑的序号。")
                    return
                try:
                    reply_idx_val = int(parts[2])
                    if 1 <= reply_idx_val <= len(entries):
                        reply_idx = reply_idx_val - 1
                        if len(parts) < 4 and not any(not isinstance(c, Plain) for c in components):
                            yield event.plain_result("请输入新的回复内容。")
                            return
                        new_content_raw = parts[3] if len(parts) >= 4 else ""
                    else:
                        yield event.plain_result(f"回复序号无效。请输入 1-{len(entries)} 之间的数字。")
                        return
                except ValueError:
                    yield event.plain_result("回复序号必须是数字。")
                    return

            # 解析新内容 (包含图片处理)
            # 重新获取组件并剔除前面的指令部分
            processed_comps = []
            first_plain_found = False
            for comp in components:
                if isinstance(comp, Plain) and not first_plain_found:
                    # 找到第一个文字组件，它包含了指令和参数
                    # 我们将其替换为提取出的 new_content_raw
                    if new_content_raw:
                        processed_comps.append(Plain(new_content_raw))
                    first_plain_found = True
                elif not isinstance(comp, Plain) or first_plain_found:
                    # 后续组件（图片等）或第一个文字组件之后的文字
                    processed_comps.append(comp)
            
            entry, has_media = self.plugin.utils.parse_message_to_entry(processed_comps)
            reply_entry = await self.plugin.utils.fetch_reply_entry(event)
            entry = self.plugin.utils.merge_entries(entry, reply_entry)
            if not self.plugin.utils.entry_has_payload(entry):
                 yield event.plain_result("回复内容不能为空。")
                 return
            
            processed_entry = await self.plugin.utils.process_entry_media(entry)
            cfg["entries"][reply_idx] = processed_entry
            
            await self.plugin.utils.save_data_async()
            logger.info(f"编辑关键词回复: {cfg['keyword']} (序号 {reply_idx+1}) (操作者: {event.get_sender_id()})")
            yield event.plain_result(f"已更新关键词 '{cfg['keyword']}' 的第 {reply_idx+1} 个回复。")

        except Exception as e:
            logger.error(f"编辑回复异常: {e}", exc_info=True)
            yield event.plain_result(f"操作失败: {e}")

    async def delete_reply(self, event: AstrMessageEvent):
        if not self.plugin.utils.is_admin(event):
            denied = self._permission_denied_result(event)
            if denied:
                yield denied
            return
            
        parts = event.message_str.strip().split()
        if len(parts) < 2:
            yield event.plain_result("格式错误。用法: /删除关键词回复 <关键词序号/内容> [回复序号]")
            return
            
        try:
            param = parts[1]
            indices = self._find_indices(param)
            if not indices:
                yield event.plain_result(f"未找到匹配 '{param}' 的关键词。")
                return
            
            idx = indices[0]
            keyword_cfg = self.plugin.data[self.data_key][idx]
            entries = keyword_cfg["entries"]
            
            if len(parts) < 3:
                if len(entries) == 1:
                    reply_idx = 0
                else:
                    yield event.plain_result(f"该关键词有 {len(entries)} 个回复，请指定要删除的回复序号。")
                    return
            else:
                try:
                    reply_idx = int(parts[2]) - 1
                except ValueError:
                    yield event.plain_result("回复序号必须是数字。")
                    return
            
            if 0 <= reply_idx < len(entries):
                keyword_cfg["entries"].pop(reply_idx)
                keyword = keyword_cfg["keyword"]
                
                await self.plugin.utils.save_data_async()
                logger.info(f"删除关键词回复: {keyword} 序号 {idx+1}, 回复序号 {reply_idx+1} (操作者: {event.get_sender_id()})")
                yield event.plain_result(f"已删除关键词 '{keyword}' 的第 {reply_idx+1} 个回复。")
            else:
                yield event.plain_result("回复序号无效。")
        except Exception as e:
            logger.error(f"删除回复异常: {e}")
            yield event.plain_result(f"操作失败: {e}")
