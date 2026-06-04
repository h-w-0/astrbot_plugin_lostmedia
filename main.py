import aiohttp
import json
import re

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

def escape_gql_string(s: str) -> str:
    """手动转义 GraphQL 字符串，保留原始中文"""
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'

def highlight_content(content: str, keyword: str, context_chars=30):
    """
    从 content 中截取包含 keyword 的片段，
    将第一个匹配的关键词用【】括起来，并替换 \n 为空格。
    返回带省略号的文本（如果截断）。
    """
    if not content or not keyword:
        return ""

    # 替换换行符
    clean = content.replace('\n', ' ').replace('\r', ' ')
    # 转义关键词中的特殊正则字符
    pattern = re.escape(keyword)
    match = re.search(pattern, clean, re.IGNORECASE)
    if not match:
        # 如果没找到，直接返回前 context_chars 字符
        snippet = clean[:context_chars]
        if len(clean) > context_chars:
            snippet += "..."
        return f'“{snippet}”'

    start = match.start()
    end = match.end()
    # 计算截取的范围
    left = max(0, start - context_chars)
    right = min(len(clean), end + context_chars)
    snippet = clean[left:right]

    # 在新的片段中定位关键词的位置（因为左边截断后位置改变）
    kw_index = snippet.lower().find(keyword.lower())
    if kw_index != -1:
        snippet = (
            snippet[:kw_index]
            + "【"
            + snippet[kw_index:kw_index + len(keyword)]
            + "】"
            + snippet[kw_index + len(keyword):]
        )

    # 添加省略号
    if left > 0:
        snippet = "..." + snippet
    if right < len(clean):
        snippet += "..."

    return f'“{snippet}”'

@register("astrbot_plugin_lostmedia", "YourName", "失传媒体成员与条目查询", "1.0.0")
class LostmediaPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

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
            logger.error(f"请求 API 失败: {e}")
            yield event.plain_result("发生错误，请稍后再试。")

    # ---------- /sr ----------
    @filter.command("sr")
    async def sr(self, event: AstrMessageEvent):
        """搜索失传媒体中文维基条目，支持分页。用法: /sr <关键词> [页码]"""
        message = event.message_str.strip()
        args = message.split(maxsplit=2)

        if len(args) < 2:
            yield event.plain_result("请提供搜索关键词。用法: /sr <关键词> [页码]")
            return

        keyword = args[1]
        try:
            page = int(args[2]) if len(args) > 2 else 1
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
            # 如果有错误，输出调试信息
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

        # 格式化每条结果
        lines = [f"🔍 找到 {total_results} 条相关条目（第 {cur_page}/{total_pages} 页）:"]
        for i, item in enumerate(results, start=1):、
            if i > 1:
                lines.append("")
            title = item.get("title", "无标题")
            url = item.get("url", "")
            content = item.get("content", "")

            # 替换域名
            display_url = url.replace("http://lostmedia.wikidot.com", "https://lostmediawiki.cn")

            # 生成高亮片段
            highlighted = highlight_content(content, keyword) if content else ""

            lines.append(f"{i}. {title}")
            if display_url:
                lines.append(f"   {display_url}")
            if highlighted:
                lines.append(f"   {highlighted}")

        # 分页提示
        if total_pages > 1:
            if cur_page < total_pages:
                lines.append(f"\n📖 下一页: /sr {keyword} {cur_page + 1}")
            if cur_page > 1:
                lines.append(f"上一页: /sr {keyword} {cur_page - 1}")
            lines.append(f"跳转: /sr {keyword} <页码>")

        yield event.plain_result("\n".join(lines))
