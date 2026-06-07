import aiohttp
import json
from datetime import datetime, timezone, timedelta
import shlex
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

# ---------------- 常量 ----------------
GRAPHQL_URL = "https://wikit.unitreaty.org/apiv1/graphql"
WIKI = "lostmedia"  # 目标 wiki
PAGE_SIZE = 10      # 每页条数

# ---------------- 工具函数 ----------------

def escape_gql_string(s: str) -> str:
    """手动转义 GraphQL 字符串，保留原始中文"""
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'

def build_url(page_slug: str, wiki: str = WIKI) -> str:
    """根据 page slug 构建可访问的链接"""
    domain_map = {
        "lostmedia": "https://lostmediawiki.cn"
    }
    base = domain_map.get(wiki, f"https://{wiki}.wikidot.com")
    return f"{base}/{page_slug}"

async def graphql_query(query: str) -> dict:
    """发送 GraphQL 请求并返回 data 部分"""
    payload = {"query": query}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(GRAPHQL_URL, json=payload, timeout=15) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"GraphQL 请求失败，状态码：{resp.status}，响应：{text[:500]}")
                    return None
                data = await resp.json()
                if "errors" in data:
                    logger.error(f"GraphQL 返回错误: {json.dumps(data['errors'], ensure_ascii=False)[:500]}")
                    return None
                return data.get("data")
    except Exception as e:
        logger.error(f"GraphQL 请求异常: {e}")
        return None


# ---------------- 插件主类 ----------------

@register("astrbot_plugin_lostmedia", "H_W", "失传媒体插件 - Wikit GraphQL 重写版", "2.0.0")
class LostmediaPlugin(Star):

    def __init__(self, context: Context):
        super().__init__(context)

    # ============================================
    #  /help
    # ============================================
    @filter.command("help")
    async def help(self, event: AstrMessageEvent):
        """显示插件帮助信息"""
        help_text = (
            "🔍 失传媒体插件 v2.0（Wikit GraphQL API）\n"
            "----------\n"
            "/sr <关键词> [页码]\n"
            "  按标题搜索条目（支持分页）\n\n"
            "/tag <标签> [页码]\n"
            "  按标签搜索条目\n\n"
            "/tagrank [数量]\n"
            "  标签使用量排行榜（默认 10）\n\n"
            "/jr [页码]\n"
            "  今日新增页面\n\n"
            "/lmcy\n"
            "  当前成员数\n\n"
            "/help\n"
            "  显示本帮助"
        )
        yield event.plain_result(help_text)

    # ============================================
    #  /sr <关键词> [页码]  —— 标题搜索
    # ============================================
    @filter.command("sr")
    async def sr(self, event: AstrMessageEvent):
        """
        按标题关键词搜索 lostmedia 条目。
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

        # 构建 GraphQL 查询
        q_keyword = escape_gql_string(keyword)
        query = f"""
        {{
            articles(wiki: ["{WIKI}"], titleKeyword: {q_keyword}, page: {page}, pageSize: {PAGE_SIZE}) {{
                nodes {{
                    title
                    url
                    author
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
            yield event.plain_result("搜索服务暂时不可用，请稍后再试。")
            return

        articles_data = data.get("articles")
        if not articles_data:
            yield event.plain_result("搜索服务返回异常，请稍后再试。")
            return

        nodes = articles_data.get("nodes", [])
        page_info = articles_data.get("pageInfo", {})
        total = page_info.get("total", 0)
        cur_page = page_info.get("page", page)
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE) if total else 1
        has_next = page_info.get("hasNextPage", False)

        if total == 0 or not nodes:
            yield event.plain_result(f"未找到标题包含「{keyword}」的条目。")
            return

        lines = [f"🔍 标题搜索「{keyword}」共 {total} 条（第 {cur_page}/{total_pages} 页）:",
                 "----------"]
        for i, item in enumerate(nodes, start=1):
            title = item.get("title", "无标题")
            url = item.get("url", "")
            author = item.get("author", "未知")
            # 美化显示
            display_url = url.replace("http://lostmedia.wikidot.com", "https://lostmediawiki.cn") if url else ""
            lines.append(f"{i}. {title}")
            if display_url:
                lines.append(f"   🔗 {display_url}")
            lines.append(f"   ✍️ {author}")
            if i < len(nodes):
                lines.append("")

        # 分页导航
        if total_pages > 1:
            lines.append("")
            lines.append("📖 翻页:")
            nav_parts = []
            if cur_page > 1:
                nav_parts.append(f"上一页: /sr {keyword} {cur_page - 1}")
            if has_next:
                nav_parts.append(f"下一页: /sr {keyword} {cur_page + 1}")
            if nav_parts:
                lines.append("  " + "  |  ".join(nav_parts))
            lines.append(f"  跳转: /sr {keyword} <页码>")

        yield event.plain_result("\n".join(lines))

    # ============================================
    #  /tag <标签> [页码]  —— 按标签搜索
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

        lines = [f"🏷️ 标签「{tag_name}」共 {total} 条（第 {cur_page}/{total_pages} 页）:",
                 "----------"]
        for i, item in enumerate(nodes, start=1):
            title = item.get("title", "无标题")
            url = item.get("url", "")
            author = item.get("author", "未知")
            tags = item.get("tags", [])
            display_url = url.replace("http://lostmedia.wikidot.com", "https://lostmediawiki.cn") if url else ""
            tag_str = ", ".join(tags) if tags else "（无标签）"
            lines.append(f"{i}. {title}")
            if display_url:
                lines.append(f"   🔗 {display_url}")
            lines.append(f"   页面创建者： {author}  🏷️ {tag_str}")
            if i < len(nodes):
                lines.append("")

        # 分页导航
        if total_pages > 1:
            lines.append("")
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
    #  /tagrank [数量]  —— 标签排行榜
    # ============================================
    @filter.command("tagrank")
    async def tagrank(self, event: AstrMessageEvent):
        """
        显示 lostmedia 维基的标签使用量排行榜。
        用法: /tagrank [数量]
        """
        message = event.message_str.strip()
        args = message.split()

        limit = 10
        if len(args) > 1:
            try:
                limit = int(args[1])
                if limit < 1:
                    limit = 1
                if limit > 50:
                    limit = 50
            except ValueError:
                yield event.plain_result("数量应为正整数（1~50）。")
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

        ranking = data.get("tagRanking", [])
        if not ranking:
            yield event.plain_result("暂无标签数据。")
            return

        # 截取前 limit 条
        ranking = ranking[:limit]

        lines = [f"🏆 Lostmedia 标签排行榜（Top {len(ranking)}）:",
                 "----------"]
        for item in ranking:
            rank = item.get("rank", "?")
            name = item.get("name", "未知")
            value = item.get("value", 0)
            lines.append(f"  #{rank:<4} {name:<20}  {value} 次")

        lines.append("")
        lines.append(f"💡 使用 /tag <标签名> 查看该标签下的条目")

        yield event.plain_result("\n".join(lines))

    # ============================================
    #  /jr [页码]  —— 今日新增页面
    # ============================================
    @filter.command("jr")
    async def jr(self, event: AstrMessageEvent):
        """
        显示 lostmedia 维基今日新增的页面。
        用法: /jr [页码]
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

        # 获取今天的日期（UTC+8）
        tz = timezone(timedelta(hours=8))
        today = datetime.now(tz).strftime("%Y-%m-%d")

        query = f"""
        {{
            articles(wiki: ["{WIKI}"], createdFrom: "{today}", page: {page}, pageSize: {PAGE_SIZE}) {{
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
            yield event.plain_result(f"📅 {today} 没有新增页面。")
            return

        lines = [f"📅 {today} 新增 {total} 条（第 {cur_page}/{total_pages} 页）:",
                 "----------"]
        for i, item in enumerate(nodes, start=1):
            title = item.get("title", "无标题")
            url = item.get("url", "")
            author = item.get("author", "未知")
            created_at = item.get("created_at", "")
            display_url = url.replace("http://lostmedia.wikidot.com", "https://lostmediawiki.cn") if url else ""
            # 提取时间部分
            time_str = ""
            if created_at:
                try:
                    dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    time_str = dt.astimezone(tz).strftime("%H:%M")
                except:
                    time_str = created_at
            lines.append(f"{i}. {title}")
            if display_url:
                lines.append(f"   🔗 {display_url}")
            lines.append(f"   页面创建者： {author}  🕐 {time_str}")
            if i < len(nodes):
                lines.append("")

        # 分页导航
        if total_pages > 1:
            lines.append("")
            lines.append("📖 翻页:")
            nav_parts = []
            if cur_page > 1:
                nav_parts.append(f"上一页: /jr {cur_page - 1}")
            if has_next:
                nav_parts.append(f"下一页: /jr {cur_page + 1}")
            if nav_parts:
                lines.append("  " + "  |  ".join(nav_parts))
            lines.append(f"  跳转: /jr <页码>")

        yield event.plain_result("\n".join(lines))

    # ============================================
    #  /lmcy  —— 成员数（仍然用旧 API）
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
                        yield event.plain_result(f"📊 当前失传媒体中文维基成员数：{total}")
                    else:
                        yield event.plain_result("未能获取成员数信息。")
        except Exception as e:
            logger.error(f"请求成员数 API 失败: {e}")
            yield event.plain_result("发生错误，请稍后再试。")
