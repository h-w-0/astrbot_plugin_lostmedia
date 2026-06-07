# 失传媒体插件 `astrbot_plugin_lostmedia`

> 基于 [Wikit GraphQL API](https://wikkit.wikidot.com/graphql) 的 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 插件，用于查询失传媒体中文维基（lostmedia.wikidot.com）的条目信息。

---

## ✨ 功能一览

| 命令 | 说明 |
|------|------|
| `/sr <关键词> [页码]` | **按标题搜索** — 只匹配条目标题，返回标题 + 链接 + 作者，支持分页 |
| `/tag <标签> [页码]` | **按标签搜索** — 查找包含指定标签的所有条目，支持分页 |
| `/tagrank [数量]` | **标签排行榜** — 显示 lostmedia 维基的标签使用量排行，默认 Top 10 |
| `/jr [页码]` | **今日新增** — 展示当天（UTC+8）新建的页面 |
| `/lmcy` | **成员数** — 查询失传媒体中文维基当前注册成员数 |
| `/help` | **帮助** — 显示所有可用命令 |
