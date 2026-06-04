import aiohttp
import json

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

@register("astrbot_plugin_lostmedia", "YourName", "失传媒体成员与条目查询", "1.0.0")
class LostmediaPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    # ---- 查询成员数 ----
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

    # ---- 搜索条目 ----
    @filter.command("sr")
    async def sr(self, event: AstrMessageEvent):
        """搜索失传媒体中文维基条目，支持分页。用法: /sr <关键词> [页码]"""
        # 获取用户输入
        message = event.message_str.strip()
        # 去除指令前缀后解析参数
        args = message.split(maxsplit=2)  # 如 "/sr 香港 2" 或 "/sr 香港"
        if len(args) < 2:
            yield event.plain_result("请提供搜索关键词。用法: /sr <关键词> [页码]")
            return

        keyword = args[1]
        try:
            page = int(args[2]) if len(args) > 2 else 1
        except ValueError:
            yield event.plain_result("页码应为数字。")
            return

        # GraphQL 请求
        graphql_url = "https://wikit.unitreaty.org/wikidot/search-graph"
        # 使用 GraphQL 变量防止注入
        query = """
        query Search($q: String!, $page: Int, $limit: Int) {
          search(wiki:"lostmedia", q:$q, page:$page, limit:$limit) {
            query
            total_results
            total_pages
            current_page
            results {
              title
              url
              lastmod
            }
          }
        }
        """
        variables = {
            "q": keyword,
            "page": page,
            "limit": 5
        }
        payload = {
            "query": query,
            "variables": variables
        }

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

        # 解析结果
        search_data = data.get("data", {}).get("search")
        if not search_data:
            yield event.plain_result("未获取到搜索结果。")
            return

        total_results = search_data.get("total_results", 0)
        total_pages = search_data.get("total_pages", 0)
        cur_page = search_data.get("current_page", page)
        results = search_data.get("results", [])

        if total_results == 0:
            yield event.plain_result(f"未找到与“{keyword}”相关的条目。")
            return

        # 格式化回复
        lines = [
            f"🔍 找到 {total_results} 条相关条目（第 {cur_page}/{total_pages} 页）:"
        ]
        for i, item in enumerate(results, start=1):
            title = item.get("title", "无标题")
            url = item.get("url", "")
            lines.append(f"{i}. {title}")
            if url:
                lines.append(f"   {url}")

        # 分页提示
        if total_pages > 1:
            if cur_page < total_pages:
                lines.append(f"\n📖 翻页命令:\n下一页: /sr {keyword} {cur_page + 1}")
            if cur_page > 1:
                lines.append(f"上一页: /sr {keyword} {cur_page - 1}")
            lines.append(f"跳转: /sr {keyword} <页码>")

        yield event.plain_result("\n".join(lines))
