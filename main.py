import re
import urllib.request
import asyncio
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

@register("wikidot_rank", "YourName", "查询 Wikidot 用户排名", "1.0.0")
class WikidotRank(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    async def _fetch(self, url: str, timeout: int = 10) -> str:
        """异步执行同步的 urllib 请求，避免阻塞事件循环"""
        loop = asyncio.get_running_loop()
        def _sync_fetch():
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return resp.read().decode('utf-8', errors='ignore')
        return await loop.run_in_executor(None, _sync_fetch)

    @filter.command("user")
    async def user_rank(self, event: AstrMessageEvent):
        # 提取参数
        msg = event.message_str.strip()
        parts = msg.split(maxsplit=1)
        if len(parts) < 2:
            yield event.plain_result("使用方法：/user <Wikidot用户名>\n示例：/user H_W")
            return
        username = parts[1].strip()
        if not username:
            yield event.plain_result("请提供有效的用户名。")
            return

        url = f"https://wikit.unitreaty.org/wikidot/rank?user={username}"
        try:
            html = await self._fetch(url)
        except Exception as e:
            logger.error(f"请求 {url} 失败: {e}")
            yield event.plain_result("网络请求失败，请检查网络或稍后重试。")
            return

        # 解析 HTML
        body_match = re.search(r'<body>(.*?)</body>', html, re.DOTALL | re.IGNORECASE)
        if not body_match:
            yield event.plain_result("未找到排名信息，该用户可能不存在。")
            return
        body = body_match.group(1)

        # <br> 转成换行，再去掉所有 HTML 标签
        body = re.sub(r'<br\s*/?>', '\n', body, flags=re.IGNORECASE)
        text = re.sub(r'<[^>]+>', '', body)
        text = text.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')

        # 按行处理，过滤空行
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        if not lines:
            yield event.plain_result(f"用户 '{username}' 暂无排名记录。")
            return

        result = '\n'.join(lines)
        yield event.plain_result(result)
