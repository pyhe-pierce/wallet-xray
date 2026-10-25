# 💸 Wallet X-Ray 钱包体检

![Wallet X-Ray](assets/social-preview.png)

**你用 AI 做的 app，平时每天花你多少钱？最坏的一天能被刷掉多少钱？**

这是一个给 Claude / AI 编程助手用的 skill。它不只查"数据会不会泄露"，更查"钱会不会漏"。
它会找出你代码里所有花钱的地方（大模型、生图、语音、邮件、短信、地图、存储），然后给你三个数字和一张修复清单。

[English](README.md)

## 为什么做这个

普通安全检查问的是"别人能不能偷我的数据"。
真正让独立开发者睡不着的是"别人能不能刷爆我的账单"。

- 有团队把旧的 Google Maps key 写在网页里，后来同一个项目开了 Gemini，这个 key 就自动能调 Gemini 了。**48 小时被刷 $82,314。**
- 有人用示例模板导出的项目里，key 用的是 `VITE_` 开头的环境变量，构建时被打包进了前端 JS。**40 分钟被刷约 $6,000。**

这两件事都不算"数据泄露"，但钱是实打实没了。

## 你会得到什么

1. **每个活跃用户每月成本**：按轻度 / 普通 / 重度三档，根据你代码里真实的 prompt 估算
2. **最坏情况每小时烧多少钱**：最弱的那个接口 × 最大 token × 最大请求数
3. **利润率**：售价 − 支付手续费 − AI 成本 − 你替免费用户付的钱
4. **修复前后对比**：最坏每小时成本修前修后各多少，每个限额都标明是"已确认 / 估算 / 无上限"，不拿假设当事实

还有：
- 🔴 / 🟡 / 🟢 问题清单，**按"修一分钟能省多少钱"排序**
- **不用写代码、今天就能做的设置**：消费上限、关闭自动充值、key 限制（只列你实际用到的平台）
- **能直接抄的修复代码**（Next.js + Supabase）：key 挪到服务器、每人每日限额（一个 SQL 函数）、`max_tokens`、模型白名单、webhook 验签
- **实时价格**：每次去官方页面查当天价格，不靠过时的记忆

## 安装

```bash
npx skills add pyhe-pierce/wallet-xray
```

Claude Code 插件方式：
```
/plugin marketplace add pyhe-pierce/wallet-xray
/plugin install wallet-xray@wallet-xray
```

手动：把 `skills/wallet-xray` 文件夹复制到 `~/.claude/skills/`。

## 使用

在项目里直接说：

> "帮我做一次钱包体检"
> "这个 app 会不会被刷爆账单？"
> "每个用户大概花我多少钱？"

也可以单独跑扫描脚本（只需要 Python 3）：

```bash
python3 skills/wallet-xray/scripts/scan.py 你的项目路径
```

## 在真实开源项目上测过

发布前在 8 个公开的 AI app 上跑过扫描，每一条结果都人工核对过。这一轮发现并修掉了：直接用 `fetch()` 调 Replicate 漏报、限流检测区分大小写、辅助函数没继承调用它的路由的保护、用户自带 key 的项目被误算成你的账单。

修完之后：真漏洞全部标红，这些项目上没有红色误报。比如：
- Google 官方 `gemini-image-editing-nextjs-quickstart`：生图接口没登录没限流，原样部署的话谁都能用你的 key 生图
- Google 官方 `starter-applets`：`VITE_GEMINI_API_KEY` 会被打包进前端 JS
- `vercel-labs/gemini-chatbot`：要登录但没有每人限额，免费账号就能无限调用

## 说在前面

- 扫描脚本靠关键词匹配，**会有误报，也可能漏掉**。skill 会让 AI 逐个打开文件确认后再报告，但这是体检，不是保险。
- 成本数字是基于假设的估算，用来判断数量级（是 $5 还是 $5,000），不能代替平台后台的账单。
- 只用来检查**你自己的** app。

## License

MIT © Pierce He
