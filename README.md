# 飞书 / Lark 自动日报周报生成工具

> 基于 [lark-cli](https://github.com/larksuite/cli) + AI 大模型，自动抓取飞书/Lark 群聊、私信和文档通知，生成结构化工作日报和周报，以消息卡片形式推送到你的私信，并自动创建待跟进任务。

**同时支持飞书（国内）和 Lark（海外）。**

---

## ✨ 功能特性

- **全自动抓取**：自动拉取所有群组（只保留 @你 和 @所有人 的消息）、当天/本周活跃私信、云文档助手通知（文档 @你、权限申请、权限变更）
- **AI 结构化总结**：将原始消息整理为【工作概览】【各群重点】【待跟进事项】【请假情况】等模块
- **消息卡片推送**：以飞书卡片格式发送，比纯文本更清晰；发送失败时自动降级为纯文本，保证消息必达
- **自动创建任务**：解析【待跟进事项】，自动在飞书任务中创建对应条目，截止日期为次日
- **日报 + 周报 + 自定义查询**：每天 18:30 发日报，每周日 15:00 发周报；也支持指定任意时间范围生成报告（比如"过去三个月做了什么"）
- **动态采样策略**：根据时间跨度自动调整抓取量和 AI 总结详细度，长周期查询（如半年总结）会按阶段/主题分类，不会因为太长而丢失早期内容
- **跨平台**：Windows / macOS / Linux 一套 Python 代码搞定
- **AI 模型自由选择**：支持云端 API（DeepSeek、OpenAI、Claude、通义千问等）和本地模型（Ollama），满足不同隐私需求

---

## 📋 效果预览

日报以飞书消息卡片形式发送：

```
[日报] 2026-06-30  生成于 18:30
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【工作概览】
今天主要跟进数据处理流程优化，处理第三方接口迁移通知，并与同事沟通内容审核策略的召回问题。

【各群重点】
· 技术支持群：同事A通知某接口即将下线，需检查相关代码并迁移
· 项目协作组：同事B建议切换到备选方案
· 团队日常群：同事C明天上午请假体检

【待跟进事项】
· 同事B@我：将配置项改为新命名规范
· 同事D@我：确认审核策略覆盖方案

【我的参与】
与同事D讨论策略生效问题；在项目组确认接口迁移方案

【请假情况】
| 请假人 | 请假周期 | 备注 |
|--------|----------|------|
| 同事C | 7月1日上午 | 体检 |
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
共 29 条消息 | 15 个群组
```

同时自动在飞书「任务」中创建待跟进条目，截止日期为次日，无需手动誊抄。

---

## 🚀 快速开始

### 第一步：环境准备

需要以下环境：
- Python 3.8+
- Node.js 16+（用于安装 lark-cli）

```bash
# 安装 lark-cli
npm install -g @larksuite/cli

# 安装 lark-cli skills（必需）
npx -y skills add https://open.feishu.cn --skill -y
```

> **国内网络提示**：如果 npm 安装超时，使用淘宝镜像：
> ```bash
> npm install -g @larksuite/cli --registry=https://registry.npmmirror.com
> ```

### 第二步：配置飞书 / Lark 应用

```bash
# 初始化应用凭证（命令会输出一个 URL，在浏览器中打开完成授权）
lark-cli config init --new

# 登录（命令会输出一个 URL，在浏览器中打开完成授权）
lark-cli auth login --recommend

# 验证登录状态
lark-cli auth status
```

登录成功后，在 `auth status` 输出中找到你的 `openId`（格式 `ou_xxx`），后面配置需要用到。

> **Token 有效期**：飞书 user 身份 token 有效期通常为 7 天，需要定期刷新：
> ```bash
> lark-cli auth login --recommend
> ```
> Windows 用户运行 `setup_windows.ps1` 后会自动设置每周一的刷新提醒。

### 第三步：配置本工具

```bash
cp config.example.json config.json
```

编辑 `config.json`：

```json
{
  "lark": {
    "my_open_id": "ou_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
  },
  "ai": {
    "api_key": "sk-xxxxxxxx",
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-chat",
    "max_tokens": 1500,
    "max_tokens_weekly": 4000,
    "max_tokens_longquery": 8000
  },
  "features": {
    "enable_docs": false,
    "auto_create_tasks": true
  }
}
```

### 第四步：测试运行

```bash
# 测试日报
python feishu_report.py --mode daily

# 测试周报
python feishu_report.py --mode weekly

# 自定义时间范围（比如查询过去一个季度）
python feishu_report.py --start "2026-04-01 00:00" --end "2026-06-30 23:59"
```

### 第五步：设置定时任务

**Windows（一键配置）：**
```powershell
powershell -ExecutionPolicy Bypass -File setup_windows.ps1
```

会自动配置三个定时任务：
- 每天 18:30 发送日报
- 每周日 15:00 发送周报
- 每周一 09:00 弹窗提醒刷新 Token

**macOS / Linux：**
```bash
chmod +x setup_unix.sh && ./setup_unix.sh
```

> **Windows 用户注意**：任务计划程序需要在你的用户登录状态下才能正常调用 npm 全局命令（lark-cli）。如果发现任务执行失败，先排查电脑是否处于睡眠/关机状态，或手动运行下面命令测试：
> ```powershell
> Start-ScheduledTask -TaskName "FeishuDailyReport"
> Get-ScheduledTaskInfo -TaskName "FeishuDailyReport"
> ```

---

## 🤖 AI 模型配置

### 云端 API（推荐新手）

修改 `config.json` 中的 `ai` 字段即可切换模型，无需改代码：

| 平台 | base_url | model | 备注 |
|------|----------|-------|------|
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` | 国内可用，性价比高 |
| OpenAI | `https://api.openai.com` | `gpt-4o-mini` | 需要科学上网 |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-turbo` | 国内可用 |
| Kimi | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` | 国内可用 |
| Claude（兼容代理） | `https://api.anthropic.com/v1` | `claude-3-5-haiku-20241022` | 需要科学上网 |
| 豆包 | `https://ark.cn-beijing.volces.com/api/v3` | `doubao-pro-32k` | 国内可用 |

### 本地模型（隐私保护模式）

如果你对数据隐私有要求，不希望消息内容发送到任何云端，可以用 [Ollama](https://ollama.com) 在本地部署模型，数据全程不出本机。

**安装 Ollama 并拉取模型：**

```bash
# macOS / Linux
curl -fsSL https://ollama.com/install.sh | sh

# Windows：下载安装包 https://ollama.com/download

# 拉取中文效果较好的模型
ollama pull qwen2.5

# 低配机器可用更小的模型
ollama pull qwen2.5:7b
```

**修改 config.json：**

```json
{
  "ai": {
    "api_key": "ollama",
    "base_url": "http://localhost:11434",
    "model": "qwen2.5",
    "max_tokens": 1500
  }
}
```

> Ollama 兼容 OpenAI API 协议，脚本会自动补全 `/v1` 路径，无需任何代码修改。

**其他本地模型方案：**

| 方案 | base_url | 说明 |
|------|----------|------|
| Ollama | `http://localhost:11434` | 最简单，推荐 |
| LM Studio | `http://localhost:1234/v1` | 有图形界面，适合不熟悉命令行的用户 |
| vLLM | `http://localhost:8000/v1` | 高性能，适合服务器部署 |

---

## ⚙️ 功能配置

`config.json` 中 `features` 字段控制各功能开关：

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `enable_docs` | `false` | 文档监控（我编辑/评论的文档），需企业管理员审批 `search:docs:read` 权限 |
| `auto_create_tasks` | `true` | 自动将【待跟进事项】创建为飞书任务，负责人为你自己，截止日期为次日 |

---

## 📊 报告时间范围与采样策略

| 模式 | 默认时间范围 | 发送时间 |
|------|-------------|----------|
| 日报 | 前一天 18:30 ~ 今天 18:30 | 每天 18:30 |
| 周报 | 上周五 00:00 ~ 本周五 00:00 | 每周日 15:00 |
| 自定义 | `--start` / `--end` 指定 | 手动运行 |

为避免长周期查询时消息过多超出 AI 上下文限制，脚本会根据时间跨度自动调整：

| 时间跨度 | 单群最大抓取条数 | AI 总结策略 |
|----------|----------------|------------|
| ≤ 1 天 | 50 条 | 标准日报格式 |
| ≤ 7 天 | 100 条 | 标准周报格式 |
| ≤ 30 天 | 200 条 | 标准格式，采样覆盖全周期 |
| > 30 天 | 500 条 | 按阶段/主题分类总结，适合季度/半年总结 |

超过采样上限时，日报取最新消息，周报及以上按时间均匀采样，确保不会因为消息太多而只看到最近几天的内容。

---

## 🔐 权限说明

首次登录时会自动申请所需权限，核心权限列表：

| 权限 | 用途 |
|------|------|
| `im:message` | 读取消息 |
| `im:chat:read` | 读取群列表 |
| `im:message.p2p_msg:get_as_user` | 读取私信 |
| `task:task:write` | 创建任务 |
| `offline_access` | 支持 Token 刷新 |
| `search:docs:read` | 文档监控（可选，需管理员审批） |

---

## 📁 文件结构

```
feishu-daily-report/
├── feishu_report.py      # 主脚本（跨平台，Windows/macOS/Linux）
├── config.example.json   # 配置模板
├── config.json           # 你的配置（已加入 .gitignore，不会提交）
├── setup_windows.ps1     # Windows 一键配置定时任务
├── setup_unix.sh         # macOS/Linux 一键配置定时任务
├── .gitignore
└── README.md
```

---

## ❓ 常见问题

**Q: Windows 上提示找不到 lark-cli？**
脚本会自动探测 `%APPDATA%\npm\lark-cli.cmd` 路径。如果你用了自定义 npm 全局目录，请确认 `lark-cli` 在系统 PATH 中：`where.exe lark-cli`。

**Q: 卡片发送失败怎么办？**
脚本内置了降级机制：如果卡片格式发送失败，会自动改用纯文本格式重试，确保你不会错过报告。

**Q: 文档监控一直显示未启用？**
这是正常的——`search:docs:read` 权限需要企业飞书管理员审批。审批通过前，脚本仍会通过「云文档助手」机器人通知抓取文档相关的 @你、权限申请等信息，不影响基础使用。

**Q: 想看过去半年的工作总结怎么办？**
直接用 `--start` / `--end` 自定义查询：
```bash
python feishu_report.py --start "2026-01-01 00:00" --end "2026-06-30 23:59"
```
脚本会自动识别长周期，按阶段/主题生成详细总结，而不是简单的日报格式。

---

## 🤝 Contributing

欢迎提 PR 和 Issue！特别欢迎：

- 支持更多 AI 平台和本地模型
- 文档监控功能完善（待权限开放后测试）
- 报告格式 / 卡片样式优化
- Lark（海外版）实际环境测试反馈

---

## 📄 License

MIT
