import aiohttp
import json
import re
import shlex
from urllib.parse import urlencode

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

# ---------------- 工具函数 ----------------
def escape_gql_string(s: str) -> str:
    """手动转义 GraphQL 字符串，保留原始中文"""
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'

def highlight_content(content: str, keyword: str, context_chars=30):
    """
    从 content 中截取包含 keyword 的片段，
    将第一个匹配的关键词用【】括起来，并替换 \n 为空格。
    返回带引号和可能省略号的文本。
    """
    if not content or not keyword:
        return ""

    # 替换换行符
    clean = content.replace('\n', ' ').replace('\r', ' ')
    # 转义特殊正则字符
    pattern = re.escape(keyword)
    match = re.search(pattern, clean, re.IGNORECASE)
    if not match:
        # 未找到关键词，直接返回开头的片段
        snippet = clean[:context_chars]
        if len(clean) > context_chars:
            snippet += "..."
        return f'“{snippet}”'

    start = match.start()
    end = match.end()
    left = max(0, start - context_chars)
    right = min(len(clean), end + context_chars)
    snippet = clean[left:right]

    # 在新的片段中定位关键词（忽略大小写）
    kw_index = snippet.lower().find(keyword.lower())
    if kw_index != -1:
        snippet = (
            snippet[:kw_index]
            + "【"
            + snippet[kw_index:kw_index + len(keyword)]
            + "】"
            + snippet[kw_index + len(keyword):]
        )

    if left > 0:
        snippet = "..." + snippet
    if right < len(clean):
        snippet += "..."

    return f'“{snippet}”'

# ---------------- 插件主类 ----------------
@register("astrbot_plugin_lostmedia", "YourName", "失传媒体成员与条目查询", "1.0.0")
class LostmediaPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
# ---------- /help ----------
    @filter.command("help")
    async def help(self, event: AstrMessageEvent):
        """显示插件帮助信息"""
        help_text = (
            "🔍 失传媒体插件帮助：\n"
            "/lmcy  — 查询失传媒体中文维基当前成员数\n"
            "/sr <关键词>  — 模糊搜索条目标题 \n"
            "/srall <关键词> [页码]  — 全文搜索条目内容\n"
            "/help  — 显示本帮助"
        )
        yield event.plain_result(help_text)

    # ---------- /lmcy ----------
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
                        yield event.plain_result(f"当前失传媒体中文维基成员数：{total}")
                    else:
                        yield event.plain_result("未能获取成员数信息。")
        except Exception as e:
            logger.error(f"请求成员数 API 失败: {e}")
            yield event.plain_result("发生错误，请稍后再试。")

    # ---------- /sr（语义搜索）----------
    @filter.command("sr")
    async def sr(self, event: AstrMessageEvent):
        """
        语义搜索失传媒体中文维基条目，返回标题、链接和标签。
        支持双引号包裹带空格的关键词。
        用法: /sr <关键词>
        """
        message = event.message_str.strip()
        try:
            args = shlex.split(message)
        except ValueError:
            args = message.split()

        if len(args) < 2:
            yield event.plain_result("请提供搜索关键词。用法: /sr <关键词>")
            return

        keyword = args[1]
        # 该 API 不支持分页，此处忽略多余参数

        params = urlencode({"wiki": "lostmedia", "q": keyword})
        api_url = f"https://wikit.unitreaty.org/semantic-search/api/search?{params}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url) as resp:
                    if resp.status != 200:
                        yield event.plain_result(f"语义搜索请求失败，状态码：{resp.status}")
                        return
                    data = await resp.json()
        except Exception as e:
            logger.error(f"语义搜索请求出错: {e}")
            yield event.plain_result("搜索服务暂时不可用，请稍后再试。")
            return

        if data.get("status") != "success":
            yield event.plain_result("语义搜索失败，请稍后再试。")
            return

        total_returned = data.get("total_returned", 0)
        results = data.get("results", [])

        if not results:
            yield event.plain_result(f"未找到与“{keyword}”相关的条目。")
            return

        lines = [f"🔍 语义模糊搜索找到 {total_returned} 条相关条目:"]
        for i, item in enumerate(results, start=1):
            if i > 1:
                lines.append("")   # 条目间空一行
            title = item.get("title", "无标题")
            url = item.get("url", "")
            tags = item.get("tags", [])
            tag_str = ", ".join(tags) if tags else ""

            lines.append(f"{i}. {title}")
            if url:
                srall_url = url.replace("http://lostmedia.wikidot.com", "https://lostmediawiki.cn")
                lines.append(f"   {srall_url}")
            if tag_str:
                lines.append(f"   🏷️ {tag_str}")

        yield event.plain_result("\n".join(lines))

    # ---------- /srall（GraphQL 详细搜索，原 /sr）----------
    @filter.command("srall")
    async def srall(self, event: AstrMessageEvent):
        """
        搜索失传媒体中文维基条目 (GraphQL 全文搜索)，支持分页和内容高亮。
        用法: /srall <关键词> [页码]
        """
        message = event.message_str.strip()
        try:
            args = shlex.split(message)
        except ValueError:
            args = message.split()

        if len(args) < 2:
            yield event.plain_result("请提供搜索关键词。用法: /srall <关键词> [页码]")
            return

        keyword = args[1]
        page = 1
        if len(args) > 2:
            try:
                page = int(args[2])
            except ValueError:
                yield event.plain_result("页码应为数字。")
                return

        # 构建 GraphQL 查询（内联参数）
        q_str = escape_gql_string(keyword)
        query = (
            f"query {{ search(wiki:\"lostmedia\", q:{q_str}, page:{page}, limit:5) {{ "
            "query total_results total_pages current_page "
            "results { title url content lastmod } "
            "} } }"
        )

        payload = {"query": query}
        graphql_url = "https://wikit.unitreaty.org/wikidot/search-graph"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(graphql_url, json=payload) as resp:
                    if resp.status != 200:
                        yield event.plain_result(f"搜索失败，状态码：{resp.status}")
                        return
                    data = await resp.json()
        except Exception as e:
            logger.error(f"GraphQL 请求出错: {e}")
            yield event.plain_result("搜索服务暂时不可用，请稍后再试。")
            return

        search_data = data.get("data", {}).get("search")
        if not search_data:
            debug_info = json.dumps(data, ensure_ascii=False, indent=2)[:600]
            yield event.plain_result(f"未获取到搜索结果。\n调试：{debug_info}")
            return

        total_results = search_data.get("total_results", 0)
        total_pages = search_data.get("total_pages", 0)
        cur_page = search_data.get("current_page", page)
        results = search_data.get("results", [])

        if total_results == 0:
            yield event.plain_result(f"未找到与“{keyword}”相关的条目。")
            return

        lines = [f"🔍 全文搜索找到 {total_results} 条相关条目（第 {cur_page}/{total_pages} 页）:"]
        for i, item in enumerate(results, start=1):
            if i > 1:
                lines.append("")   # 条目间空一行
            title = item.get("title", "无标题")
            raw_url = item.get("url", "")
            # 替换域名为 https://lostmediawiki.cn
            display_url = raw_url.replace("http://lostmedia.wikidot.com", "https://lostmediawiki.cn")
            content = item.get("content", "")
            highlighted = highlight_content(content, keyword) if content else ""

            lines.append(f"{i}. {title}")
            if display_url:
                lines.append(f"   {display_url}")
            if highlighted:
                lines.append(f"   {highlighted}")

        # 分页提示
        if total_pages > 1:
            if cur_page < total_pages:
                lines.append(f"\n📖 下一页: /srall {keyword} {cur_page + 1}")
            if cur_page > 1:
                lines.append(f"上一页: /srall {keyword} {cur_page - 1}")
            lines.append(f"跳转: /srall {keyword} <页码>")

        yield event.plain_result("\n".join(lines))

