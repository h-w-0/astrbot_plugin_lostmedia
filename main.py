import aiohttp
import json

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

@register("astrbot_plugin_lostmedia", "YourName", "失传媒体成员与条目查询", "1.0.0")
class LostmediaPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    # ---------- 成员数查询 ----------
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

    # ---------- 条目搜索 ----------
    @filter.command("sr")
    async def sr(self, event: AstrMessageEvent):
        """搜索失传媒体中文维基条目，支持分页。用法: /sr <关键词> [页码]"""
        message = event.message_str.strip()
        args = message.split(maxsplit=2)  # 处理指令和参数

        if len(args) < 2:
            yield event.plain_result("请提供搜索关键词。用法: /sr <关键词> [页码]")
            return

        keyword = args[1]
        try:
            page = int(args[2]) if len(args) > 2 else 1
        except ValueError:
            yield event.plain_result("页码应为数字。")
            return

        # ---- 关键修改：直接内联参数到 GraphQL 查询 ----
        # 使用 json.dumps 安全地转义关键词，避免注入
        q_escaped = json.dumps(keyword)  # 生成带双引号的字符串，如 "北京"
        query = f"""
        query {{
          search(wiki:"lostmedia", q:{q_escaped}, page:{page}, limit:5) {{
            query
            total_results
            total_pages
            current_page
            results {{
              title
              url
              lastmod
            }}
          }}
        }}
        """
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

        # 打印完整返回数据，方便排查（上线后可注释掉）
        logger.debug(f"搜索 API 返回: {data}")

        search_data = data.get("data", {}).get("search")
        if not search_data:
            yield event.plain_result("未获取到搜索结果，请检查 API 是否正常。")
            return

        total_results = search_data.get("total_results", 0)
        total_pages = search_data.get("total_pages", 0)
        cur_page = search_data.get("current_page", page)
        results = search_data.get("results", [])

        if total_results == 0:
            yield event.plain_result(f"未找到与“{keyword}”相关的条目。")
            return

        # 格式化结果
        lines = [f"🔍 找到 {total_results} 条相关条目（第 {cur_page}/{total_pages} 页）:"]
        for i, item in enumerate(results, start=1):
            title = item.get("title", "无标题")
            url = item.get("url", "")
            lines.append(f"{i}. {title}")
            if url:
                lines.append(f"   {url}")

        # 分页提示
        if total_pages > 1:
            if cur_page < total_pages:
                lines.append(f"\n📖 下一页: /sr {keyword} {cur_page + 1}")
            if cur_page > 1:
                lines.append(f"上一页: /sr {keyword} {cur_page - 1}")
            lines.append(f"跳转: /sr {keyword} <页码>")

        yield event.plain_result("\n".join(lines))
