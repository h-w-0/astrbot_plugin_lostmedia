import aiohttp
import json
from datetime import datetime, timezone, timedelta
import shlex
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import astrbot.api.message_components as Comp
import urllib.parse

# ---------------- 常量 ----------------
GRAPHQL_URL = "https://wikit.unitreaty.org/apiv1/graphql"
WIKI = "lostmedia"
PAGE_SIZE = 5

# /sr 需要排除的 URL 路径前缀
EXCLUDED_URL_PATTERNS = (
    "/deleted:",
    "/info:",
    "/admin:",
    "/forum:",
    "/setting:",
    "/statistics:",
    "/tags:",
)

# ---------------- 工具函数 ----------------


def escape_gql_string(s: str) -> str:
    """手动转义 GraphQL 字符串，保留原始中文"""
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def should_include_url(url: str) -> bool:
    """检查 URL 是否不包含排除列表中的路径"""
    if not url:
        return True
    return not any(pattern in url for pattern in EXCLUDED_URL_PATTERNS)


def format_url(url: str) -> str:
    """统一域名替换"""
    if not url:
        return ""
    return url.replace("http://lostmedia.wikidot.com", "https://lostmediawiki.cn")


def get_today_tz() -> str:
    """获取北京时间今天的日期 YYYY-MM-DD"""
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime("%Y-%m-%d")


def get_yesterday_tz() -> str:
    """获取北京时间昨天的日期 YYYY-MM-DD"""
    tz = timezone(timedelta(hours=8))
    yesterday = datetime.now(tz) - timedelta(days=1)
    return yesterday.strftime("%Y-%m-%d")


def get_week_ago_tz() -> str:
    """获取北京时间7天前的日期 YYYY-MM-DD"""
    tz = timezone(timedelta(hours=8))
    week_ago = datetime.now(tz) - timedelta(days=6)
    return week_ago.strftime("%Y-%m-%d")


async def graphql_query(query: str) -> dict:
    """发送 GraphQL 请求并返回 data 部分"""
    payload = {"query": query}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(GRAPHQL_URL, json=payload, timeout=15) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(
                        f"GraphQL 请求失败，状态码：{resp.status}，响应：{text[:500]}"
                    )
                    return None
                data = await resp.json()
                if "errors" in data:
                    logger.error(
                        f"GraphQL 返回错误: {json.dumps(data['errors'], ensure_ascii=False)[:500]}"
                    )
                    return None
                return data.get("data")
    except Exception as e:
        logger.error(f"GraphQL 请求异常: {e}")
        return None


# ---------------- 插件主类 ----------------


@register("astrbot_plugin_lostmedia", "H_W", "失传媒体插件 - Wikit GraphQL", "2.0.0")
class LostmediaPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    # ============================================
    #  /help
    # ============================================
    @filter.command("help")
    async def help(self, event: AstrMessageEvent):
        help_text = (
            "🔍 失传媒体插件 v2.0（Wikit GraphQL API）\n"
            "----------\n"
            "/sr <关键词> [页码]\n"
            "  按标题搜索条目（自动过滤管理/系统页面）\n"
            "/tag <标签> [页码]\n"
            "  按标签搜索条目\n"
            "/tagrank [页码]\n"
            "  标签使用量排行榜（每页 10 个）\n\n"
            "/jr [页码]\n"
            "  今日新增页面\n"
            "/zr [页码]\n"
            "  昨日新增页面\n"
            "/week [页码]\n"
            "  最近 7 天新增页面（含「起草中」统计）\n\n"
            "/lmcy\n"
            "  当前成员数\n\n"
            "/img\n"
            "  随机获取一张失传媒体图片\n"
            "/imgtags <标签>\n"
            "  按标签获取失传媒体图片\n"
            "/imgpage <页面>\n"
            "  按页面 短URL 获取失传媒体图片\n"
            "/imginfo\n"
            "  查看图片缓存统计\n\n"
            "/help\n"
            "  显示本帮助"
        )
        yield event.plain_result(help_text)

    # ============================================
    #  /sr <关键词> [页码]
    # ============================================
    @filter.command("sr")
    async def sr(self, event: AstrMessageEvent):
        """
        按标题关键词搜索 lostmedia 条目，自动排除管理/系统页面。
        用法: /sr <关键词> [页码]
        """
        message = event.message_str.strip()
        try:
            args = shlex.split(message)
        except ValueError:
            args = message.split()

        if len(args) < 2:
            yield event.plain_result("请提供搜索关键词。用法：/sr <关键词> [页码]")
            return

        keyword = args[1]
        page = 1
        if len(args) > 2:
            try:
                page = int(args[2])
                if page < 1:
                    page = 1
            except ValueError:
                yield event.plain_result("页码应为正整数。")
                return

        # 先取较多结果，在本地过滤后再分页
        q_keyword = escape_gql_string(keyword)
        query = f"""
        {{
            articles(wiki: ["{WIKI}"], titleKeyword: {q_keyword}, pageSize: 200) {{
                nodes {{
                    title
                    url
                    author
                }}
                pageInfo {{
                    total
                }}
            }}
        }}
        """

        data = await graphql_query(query)
        if data is None:
            yield event.plain_result("搜索服务暂时不可用，请稍后再试。")
            return

        articles_data = data.get("articles")
        if not articles_data:
            yield event.plain_result("搜索服务返回异常，请稍后再试。")
            return

        all_nodes = articles_data.get("nodes", [])
        raw_total = articles_data.get("pageInfo", {}).get("total", 0)

        # 过滤掉不希望展示的页面
        filtered_nodes = [
            n for n in all_nodes if should_include_url(n.get("url", ""))
        ]
        total = len(filtered_nodes)

        if total == 0:
            yield event.plain_result(f"未找到标题包含「{keyword}」的条目。")
            return

        # 分页
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        if page > total_pages:
            page = total_pages
        start = (page - 1) * PAGE_SIZE
        end = start + PAGE_SIZE
        nodes = filtered_nodes[start:end]

        lines = [
            f"🔍 标题搜索「{keyword}」共 {total} 条（第 {page}/{total_pages} 页）:",
            "----------",
        ]
        for i, item in enumerate(nodes, start=start + 1):
            title = item.get("title", "无标题")
            url = format_url(item.get("url", ""))
            author = item.get("author", "未知")
            lines.append(f"{i}. {title}")
            if url:
                lines.append(f"   🔗 {url}")
            lines.append(f"   ✍️ {author}")
            lines.append("")

        # 分页导航
        if total_pages > 1:
            lines.append("📖 翻页:")
            nav_parts = []
            if page > 1:
                nav_parts.append(f"上一页: /sr {keyword} {page - 1}")
            if page < total_pages:
                nav_parts.append(f"下一页: /sr {keyword} {page + 1}")
            if nav_parts:
                lines.append("  " + "  |  ".join(nav_parts))
            lines.append(f"  跳转: /sr {keyword} <页码>")

        # 提示被过滤数量
        filtered_count = raw_total - total
        if filtered_count > 0:
            lines.append(f"\n💡 已自动过滤 {filtered_count} 个管理/系统页面")

        yield event.plain_result("\n".join(lines))

    # ============================================
    #  /tag <标签> [页码]
    # ============================================
    @filter.command("tag")
    async def tag(self, event: AstrMessageEvent):
        """
        按标签搜索 lostmedia 条目。
        用法: /tag <标签> [页码]
        """
        message = event.message_str.strip()
        try:
            args = shlex.split(message)
        except ValueError:
            args = message.split()

        if len(args) < 2:
            yield event.plain_result("请提供标签名称。用法：/tag <标签> [页码]")
            return

        tag_name = args[1]
        page = 1
        if len(args) > 2:
            try:
                page = int(args[2])
                if page < 1:
                    page = 1
            except ValueError:
                yield event.plain_result("页码应为正整数。")
                return

        q_tag = escape_gql_string(tag_name)
        query = f"""
        {{
            articles(wiki: ["{WIKI}"], includeTags: [{q_tag}], page: {page}, pageSize: {PAGE_SIZE}) {{
                nodes {{
                    title
                    url
                    author
                    tags
                }}
                pageInfo {{
                    total
                    page
                    pageSize
                    hasNextPage
                }}
            }}
        }}
        """

        data = await graphql_query(query)
        if data is None:
            yield event.plain_result("查询服务暂时不可用，请稍后再试。")
            return

        articles_data = data.get("articles")
        if not articles_data:
            yield event.plain_result("查询服务返回异常，请稍后再试。")
            return

        nodes = articles_data.get("nodes", [])
        page_info = articles_data.get("pageInfo", {})
        total = page_info.get("total", 0)
        cur_page = page_info.get("page", page)
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE) if total else 1
        has_next = page_info.get("hasNextPage", False)

        if total == 0 or not nodes:
            yield event.plain_result(f"未找到标签为「{tag_name}」的条目。")
            return

        lines = [
            f"🏷️ 标签「{tag_name}」共 {total} 条（第 {cur_page}/{total_pages} 页）:",
            "----------",
        ]
        for i, item in enumerate(nodes, start=1):
            title = item.get("title", "无标题")
            url = format_url(item.get("url", ""))
            author = item.get("author", "未知")
            tags = item.get("tags", [])
            tag_str = ", ".join(tags) if tags else "（无标签）"
            lines.append(f"{i}. {title}")
            if url:
                lines.append(f"   🔗 {url}")
            lines.append(f"     🏷️ {tag_str}")
            lines.append("")

        if total_pages > 1:
            lines.append("📖 翻页:")
            nav_parts = []
            if cur_page > 1:
                nav_parts.append(f"上一页: /tag {tag_name} {cur_page - 1}")
            if has_next:
                nav_parts.append(f"下一页: /tag {tag_name} {cur_page + 1}")
            if nav_parts:
                lines.append("  " + "  |  ".join(nav_parts))
            lines.append(f"  跳转: /tag {tag_name} <页码>")

        yield event.plain_result("\n".join(lines))

    # ============================================
    #  /tagrank [页码]  —— 每页固定 10 个
    # ============================================
    @filter.command("tagrank")
    async def tagrank(self, event: AstrMessageEvent):
        """
        显示 lostmedia 维基的标签使用量排行榜。
        用法: /tagrank [页码]
        """
        message = event.message_str.strip()
        args = message.split()

        page = 1
        if len(args) > 1:
            try:
                page = int(args[1])
                if page < 1:
                    page = 1
            except ValueError:
                yield event.plain_result("页码应为正整数。")
                return

        query = f"""
        {{
            tagRanking(wiki: "{WIKI}") {{
                rank
                name
                value
            }}
        }}
        """

        data = await graphql_query(query)
        if data is None:
            yield event.plain_result("排行榜服务暂时不可用，请稍后再试。")
            return

        all_ranking = data.get("tagRanking", [])
        if not all_ranking:
            yield event.plain_result("暂无标签数据。")
            return

        # 每页 10 条
        per_page = 10
        total_items = len(all_ranking)
        total_pages = max(1, (total_items + per_page - 1) // per_page)
        if page > total_pages:
            page = total_pages

        start = (page - 1) * per_page
        end = start + per_page
        ranking = all_ranking[start:end]

        lines = [
            f"🏆 Lostmedia 标签排行榜（第 {page}/{total_pages} 页，共 {total_items} 个标签）:",
            "----------",
        ]
        for item in ranking:
            rank = item.get("rank", "?")
            name = item.get("name", "未知")
            value = item.get("value", 0)
            lines.append(f"  #{rank:<4} {name:<20}  {value} 次")

        lines.append("")
        if total_pages > 1:
            lines.append("📖 翻页:")
            nav_parts = []
            if page > 1:
                nav_parts.append(f"上一页: /tagrank {page - 1}")
            if page < total_pages:
                nav_parts.append(f"下一页: /tagrank {page + 1}")
            if nav_parts:
                lines.append("  " + "  |  ".join(nav_parts))
            lines.append(f"  跳转: /tagrank <页码>")

        lines.append(f"\n💡 使用 /tag <标签名> 查看该标签下的条目")

        yield event.plain_result("\n".join(lines))

    # ============================================
    #  /jr [页码]  —— 今日新增
    # ============================================
    @filter.command("jr")
    async def jr(self, event: AstrMessageEvent):
        """显示今日新增页面。用法: /jr [页码]"""
        message = event.message_str.strip()
        args = message.split()

        page = 1
        if len(args) > 1:
            try:
                page = int(args[1])
                if page < 1:
                    page = 1
            except ValueError:
                yield event.plain_result("页码应为正整数。")
                return

        today = get_today_tz()
        yield event.plain_result(
            await self._render_date_pages(today, page, "jr")
        )

    # ============================================
    #  /zr [页码]  —— 昨日新增
    # ============================================
    @filter.command("zr")
    async def zr(self, event: AstrMessageEvent):
        """显示昨日新增页面。用法: /zr [页码]"""
        message = event.message_str.strip()
        args = message.split()

        page = 1
        if len(args) > 1:
            try:
                page = int(args[1])
                if page < 1:
                    page = 1
            except ValueError:
                yield event.plain_result("页码应为正整数。")
                return

        yesterday = get_yesterday_tz()
        yield event.plain_result(
            await self._render_date_pages(yesterday, page, "zr")
        )

    async def _render_date_pages(self, date_str: str, page: int, cmd: str) -> str:
        """
        按日期查询新增页面并格式化输出。
        cmd 用于生成翻页链接（jr / zr）。
        """
        query = f"""
        {{
            articles(wiki: ["{WIKI}"], createdFrom: "{date_str}", page: {page}, pageSize: {PAGE_SIZE}) {{
                nodes {{
                    title
                    url
                    author
                    created_at
                }}
                pageInfo {{
                    total
                    page
                    pageSize
                    hasNextPage
                }}
            }}
        }}
        """

        data = await graphql_query(query)
        if data is None:
            return "查询服务暂时不可用，请稍后再试。"

        articles_data = data.get("articles")
        if not articles_data:
            return "查询服务返回异常，请稍后再试。"

        nodes = articles_data.get("nodes", [])
        page_info = articles_data.get("pageInfo", {})
        total = page_info.get("total", 0)
        cur_page = page_info.get("page", page)
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE) if total else 1
        has_next = page_info.get("hasNextPage", False)

        if total == 0 or not nodes:
            return f"📅 {date_str} 没有新增页面。"

        tz = timezone(timedelta(hours=8))
        lines = [
            f"📅 {date_str} 新增 {total} 条（第 {cur_page}/{total_pages} 页）:",
            "----------",
        ]
        for i, item in enumerate(nodes, start=1):
            title = item.get("title", "无标题")
            url = format_url(item.get("url", ""))
            author = item.get("author", "未知")
            created_at = item.get("created_at", "")
            time_str = ""
            if created_at:
                try:
                    dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    time_str = dt.astimezone(tz).strftime("%H:%M")
                except Exception:
                    time_str = created_at
            lines.append(f"{i}. {title}")
            if url:
                lines.append(f"   🔗 {url}")
            lines.append(f"   ✍️ {author}  🕐 {time_str}")
            lines.append("")

        if total_pages > 1:
            lines.append("📖 翻页:")
            nav_parts = []
            if cur_page > 1:
                nav_parts.append(f"上一页: /{cmd} {cur_page - 1}")
            if has_next:
                nav_parts.append(f"下一页: /{cmd} {cur_page + 1}")
            if nav_parts:
                lines.append("  " + "  |  ".join(nav_parts))
            lines.append(f"  跳转: /{cmd} <页码>")

        return "\n".join(lines)

    # ============================================
    #  /week [页码]  —— 最近 7 天
    # ============================================
    @filter.command("week")
    async def week(self, event: AstrMessageEvent):
        """
        显示最近 7 天新增页面（含「起草中」标签统计）。
        用法: /week [页码]
        """
        message = event.message_str.strip()
        args = message.split()

        page = 1
        if len(args) > 1:
            try:
                page = int(args[1])
                if page < 1:
                    page = 1
            except ValueError:
                yield event.plain_result("页码应为正整数。")
                return

        today = get_today_tz()
        week_ago = get_week_ago_tz()

        # 组合查询：一次请求拿到总数、草稿数、列表
        query = f"""
        {{
            all: articles(wiki: ["{WIKI}"], createdFrom: "{week_ago}", pageSize: 1) {{
                pageInfo {{ total }}
            }}
            draft: articles(wiki: ["{WIKI}"], createdFrom: "{week_ago}", includeTags: ["起草中"], pageSize: 1) {{
                pageInfo {{ total }}
            }}
            list: articles(wiki: ["{WIKI}"], createdFrom: "{week_ago}", page: {page}, pageSize: {PAGE_SIZE}) {{
                nodes {{
                    title
                    url
                    author
                    created_at
                    tags
                }}
                pageInfo {{
                    total
                    page
                    pageSize
                    hasNextPage
                }}
            }}
        }}
        """

        data = await graphql_query(query)
        if data is None:
            yield event.plain_result("查询服务暂时不可用，请稍后再试。")
            return

        all_info = data.get("all", {}).get("pageInfo", {})
        draft_info = data.get("draft", {}).get("pageInfo", {})
        list_data = data.get("list", {})

        total_all = all_info.get("total", 0)
        total_draft = draft_info.get("total", 0)

        nodes = list_data.get("nodes", []) if list_data else []
        page_info = list_data.get("pageInfo", {}) if list_data else {}
        cur_page = page_info.get("page", page)
        list_total = page_info.get("total", 0)
        total_pages = max(1, (list_total + PAGE_SIZE - 1) // PAGE_SIZE) if list_total else 1
        has_next = page_info.get("hasNextPage", False)

        if total_all == 0:
            yield event.plain_result(
                f"📅 {week_ago} ~ {today} 期间没有新增页面。"
            )
            return

        tz = timezone(timedelta(hours=8))
        lines = [
            f"📊 最近 7 天（{week_ago} ~ {today}）新增页面统计:",
            f"   📄 总计: {total_all} 条",
            f"   📝 含「起草中」标签: {total_draft} 条",
            "----------",
        ]

        if nodes:
            lines.append(f"📋 列表（第 {cur_page}/{total_pages} 页）:")
            for i, item in enumerate(nodes, start=1):
                title = item.get("title", "无标题")
                url = format_url(item.get("url", ""))
                author = item.get("author", "未知")
                created_at = item.get("created_at", "")
                tags = item.get("tags", [])
                time_str = ""
                if created_at:
                    try:
                        dt = datetime.fromisoformat(
                            created_at.replace("Z", "+00:00")
                        )
                        time_str = dt.astimezone(tz).strftime("%m-%d %H:%M")
                    except Exception:
                        time_str = created_at
                has_draft_tag = "起草中" in tags
                draft_mark = " 📝" if has_draft_tag else ""
                lines.append(f"{i}. {title}{draft_mark}")
                if url:
                    lines.append(f"   🔗 {url}")
                lines.append(f"   ✍️ {author}  🕐 {time_str}")
                lines.append("")

            if total_pages > 1:
                lines.append("📖 翻页:")
                nav_parts = []
                if cur_page > 1:
                    nav_parts.append(f"上一页: /week {cur_page - 1}")
                if has_next:
                    nav_parts.append(f"下一页: /week {cur_page + 1}")
                if nav_parts:
                    lines.append("  " + "  |  ".join(nav_parts))
                lines.append(f"  跳转: /week <页码>")

        yield event.plain_result("\n".join(lines))

    # ============================================
    #  /lmcy
    # ============================================
    @filter.command("lmcy")
    async def lmcy(self, event: AstrMessageEvent):
        """查询失传媒体中文维基当前成员数"""
        url = "https://wikit.unitreaty.org/wikidot/memberlist?wiki=lostmedia&force=true"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        yield event.plain_result(f"请求失败，状态码：{resp.status}")
                        return
                    data = await resp.json()
                    total = data.get("totalMembers")
                    if total is not None:
                        yield event.plain_result(
                            f"📊 当前失传媒体中文维基成员数：{total}"
                        )
                    else:
                        yield event.plain_result("未能获取成员数信息。")
        except Exception as e:
            logger.error(f"请求成员数 API 失败: {e}")
            yield event.plain_result("发生错误，请稍后再试。")
    
        # ============================================
        # /img — 默认排除成人/血腥内容，用户不可自定义
        # ============================================
        @filter.command("img")
            async def img(self, event: AstrMessageEvent):
                """随机获取一张失传媒体图片（自动过滤成人/血腥内容）。用法: /img"""
                base_url = "https://lostmediawiki.cn/random-img.php"
                exclude = "成人内容-血腥内容"
                url = f"{base_url}?tags=-{urllib.parse.quote(exclude)}"
            
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(url, timeout=15) as resp:
                            if resp.status != 200:
                                yield event.plain_result(f"请求失败，状态码：{resp.status}")
                                return
                            data = await resp.json()
                except Exception as e:
                    logger.error(f"请求随机图片 API 失败: {e}")
                    yield event.plain_result("发生错误，请稍后再试。")
                    return
            
                deal_title = data.get("deal-title", "未知标题")
                image_url = data.get("image", "").replace("\\/", "/")
            
                if not image_url:
                    yield event.plain_result("未获取到图片链接。")
                    return
            
                chain = [
                    Comp.Plain(f"🎞️ {deal_title}\n"),
                    Comp.Image.fromURL(image_url),
                ]
                yield event.chain_result(chain)
            
            
            # ============================================
            # /imgtags <标签> — 按标签搜索，无默认过滤
            # ============================================
            @filter.command("imgtags")
            async def imgtags(self, event: AstrMessageEvent):
                """按标签获取失传媒体图片。用法: /imgtags <标签>"""
                message = event.message_str.strip()
                try:
                    args = shlex.split(message)
                except ValueError:
                    args = message.split()
            
                if len(args) < 2:
                    yield event.plain_result("请提供标签名称。用法：/imgtags <标签>")
                    return
            
                tag = args[1]
                base_url = "https://lostmediawiki.cn/random-img.php"
                url = f"{base_url}?tags={urllib.parse.quote(tag)}"
            
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(url, timeout=15) as resp:
                            if resp.status != 200:
                                yield event.plain_result(f"请求失败，状态码：{resp.status}")
                                return
                            data = await resp.json()
                except Exception as e:
                    logger.error(f"请求随机图片 API 失败: {e}")
                    yield event.plain_result("发生错误，请稍后再试。")
                    return
            
                deal_title = data.get("deal-title", "未知标题")
                image_url = data.get("image", "").replace("\\/", "/")
            
                if not image_url:
                    yield event.plain_result("未获取到图片链接。")
                    return
            
                chain = [
                    Comp.Plain(f"🎞️ {deal_title}\n"),
                    Comp.Image.fromURL(image_url),
                ]
                yield event.chain_result(chain)
            
            
            # ============================================
            # /imgpage <页面> — 按 page 参数获取
            # ============================================
            @filter.command("imgpage")
            async def imgpage(self, event: AstrMessageEvent):
                """按页面 ID 获取失传媒体图片。用法: /imgpage <页面>"""
                message = event.message_str.strip()
                args = message.split()
            
                if len(args) < 2:
                    yield event.plain_result("请提供页面 ID。用法：/imgpage <页面>")
                    return
            
                page = args[1]
                base_url = "https://lostmediawiki.cn/random-img.php"
                url = f"{base_url}?page={urllib.parse.quote(page)}"
            
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(url, timeout=15) as resp:
                            if resp.status != 200:
                                yield event.plain_result(f"请求失败，状态码：{resp.status}")
                                return
                            data = await resp.json()
                except Exception as e:
                    logger.error(f"请求图片页面 API 失败: {e}")
                    yield event.plain_result("发生错误，请稍后再试。")
                    return
            
                deal_title = data.get("deal-title", "未知标题")
                image_url = data.get("image", "").replace("\\/", "/")
            
                if not image_url:
                    yield event.plain_result("未获取到图片链接。")
                    return
            
                chain = [
                    Comp.Plain(f"🎞️ {deal_title}\n"),
                    Comp.Image.fromURL(image_url),
                ]
                yield event.chain_result(chain)
            
            
            # ============================================
            # /imginfo — 返回缓存统计信息
            # ============================================
            @filter.command("imginfo")
            async def imginfo(self, event: AstrMessageEvent):
                """查看图片缓存统计。用法: /imginfo"""
                url = "https://lostmediawiki.cn/random-img.php?info=true"
            
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(url, timeout=15) as resp:
                            if resp.status != 200:
                                yield event.plain_result(f"请求失败，状态码：{resp.status}")
                                return
                            data = await resp.json()
                except Exception as e:
                    logger.error(f"请求图片统计信息失败: {e}")
                    yield event.plain_result("发生错误，请稍后再试。")
                    return
            
                total_pages = data.get("total_pages", "未知")
                pages_with_info = data.get("pages_with_info", "未知")
                pages_with_images = data.get("pages_with_images", "未知")
                total_images = data.get("total_images", "未知")
            
                result = (
                    f"📊 失传媒体图片缓存统计\n"
                    f"----------\n"
                    f"缓存目录总数：{total_pages}\n"
                    f"含图缓存目录总数：{pages_with_images}\n"
                    f"所有图片文件数：{total_images}"
                )
                yield event.plain_result(result)
