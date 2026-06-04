import re
import asyncio
import requests
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

@register("wikidot_rank", "YourName", "查询 Wikidot 用户排名", "1.0.0")
class WikidotRank(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    async def _fetch(self, url: str, timeout: int = 10) -> str:
        loop = asyncio.get_running_loop()
        def _sync_fetch():
            resp = requests.get(url, timeout=timeout)
            resp.encoding = 'utf-8'
            return resp.text
        return await loop.run_in_executor(None, _sync_fetch)

    @filter.command("user")
    async def user_rank(self, event: AstrMessageEvent):
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
            yield event.plain_result(f"网络请求失败: {e}")
            return

        body_match = re.search(r'<body>(.*?)</body>', html, re.DOTALL | re.IGNORECASE)
        if not body_match:
            yield event.plain_result("未找到排名信息，该用户可能不存在。")
            return
        body = body_match.group(1)

        body = re.sub(r'<br\s*/?>', '\n', body, flags=re.IGNORECASE)
        text = re.sub(r'<[^>]+>', '', body)
        text = text.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')

        lines = [line.strip() for line in text.split('\n') if line.strip()]
        if not lines:
            yield event.plain_result(f"用户 '{username}' 暂无排名记录。")
            return

        result = '\n'.join(lines)
        yield event.plain_result(result)
