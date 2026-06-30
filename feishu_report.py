#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lark / Feishu Automatic Daily & Weekly Report Generator
Supports Windows / macOS / Linux
Supports any OpenAI-compatible AI model (DeepSeek, OpenAI, Claude, Qwen, etc.)

Usage:
    python feishu_report.py --mode daily
    python feishu_report.py --mode weekly
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
import urllib.error
from datetime import datetime, timedelta


# ============================================================
# Detect lark-cli executable path
# ============================================================
import shutil
import platform

def get_lark_cli():
    """Find lark-cli executable, prefer .cmd on Windows."""
    if platform.system() == "Windows":
        cmd_path = shutil.which("lark-cli.cmd")
        if cmd_path:
            return cmd_path
        npm_path = os.path.expandvars(r"%APPDATA%\npm\lark-cli.cmd")
        if os.path.exists(npm_path):
            return npm_path
    return shutil.which("lark-cli") or "lark-cli"

LARK_CLI = get_lark_cli()


def get_lark_direct_cmd() -> list:
    """
    Windows 上 .cmd 包装器会把参数传给 cmd.exe，cmd.exe 遇到 JSON 双引号就解析乱。
    这里读取 .cmd 文件，找到底层的 .exe 或 .js，直接用 Python CreateProcess 调用，
    JSON 参数完整传递，完全不经过 cmd.exe。
    非 Windows 或找不到底层二进制时，退回使用 LARK_CLI。
    """
    if platform.system() != "Windows" or not LARK_CLI.endswith(".cmd"):
        return [LARK_CLI]

    npm_dir = os.path.dirname(LARK_CLI)

    try:
        with open(LARK_CLI, "r", encoding="utf-8", errors="ignore") as f:
            cmd_text = f.read()

        # 情况1：底层是 Go 编译的 .exe（larksuite/cli 默认）
        for line in cmd_text.splitlines():
            if ".exe" in line.lower():
                m = re.search(r'"(%~?dp0[^"]*\.exe)"', line, re.IGNORECASE)
                if m:
                    raw = m.group(1).replace("%~dp0", npm_dir + os.sep).replace("%dp0%", npm_dir + os.sep)
                    exe = os.path.normpath(raw)
                    if os.path.exists(exe):
                        return [exe]

        # 情况2：底层是 Node.js 脚本
        node = shutil.which("node")
        if node:
            for line in cmd_text.splitlines():
                if ".js" in line:
                    m = re.search(r'"(%~?dp0[^"]*\.js)"', line, re.IGNORECASE)
                    if m:
                        raw = m.group(1).replace("%~dp0", npm_dir + os.sep).replace("%dp0%", npm_dir + os.sep)
                        js = os.path.normpath(raw)
                        if os.path.exists(js):
                            return [node, js]
    except Exception:
        pass

    # 兜底：扫描 npm 包内常见路径的 Go 二进制
    pkg_bin = os.path.join(npm_dir, "node_modules", "@larksuite", "cli", "bin")
    for name in ["lark-cli-windows-amd64.exe", "lark-cli-windows-386.exe",
                 "lark-cli-win.exe", "lark-cli.exe"]:
        for directory in [npm_dir, pkg_bin]:
            candidate = os.path.join(directory, name)
            if os.path.exists(candidate):
                return [candidate]

    return [LARK_CLI]  # 找不到就退回 .cmd（可能 JSON 仍然失败）

LARK_DIRECT = get_lark_direct_cmd()


# ============================================================
# Load config
# ============================================================
def load_config():
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    if not os.path.exists(config_path):
        print("Error: config.json not found. Please copy config.example.json and fill in your settings.")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# Run lark-cli command, return parsed JSON
# ============================================================
def run_lark_cli(args: list) -> dict:
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            tmp_path = tmp.name

        cmd = [LARK_CLI] + args
        with open(tmp_path, "wb") as out:
            subprocess.run(cmd, stdout=out, stderr=subprocess.DEVNULL, shell=True)
        with open(tmp_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read().strip()
            if not text:
                return {"ok": False}
            return json.loads(text)
    except Exception:
        return {"ok": False}
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


# ============================================================
# Fetch all group chats (auto-paginate)
# ============================================================
def fetch_all_chats() -> list:
    chats = []
    page_token = None
    while True:
        args = ["im", "+chat-list", "--page-size", "50"]
        if page_token:
            args += ["--page-token", page_token]
        result = run_lark_cli(args)
        if not result.get("ok"):
            break
        chats.extend(result["data"].get("chats", []))
        if result["data"].get("has_more"):
            page_token = result["data"]["page_token"]
        else:
            break
    return chats


# ============================================================
# Fetch all direct message (P2P) chats with real users
# ============================================================
def fetch_p2p_chats() -> list:
    result = run_lark_cli(["im", "+chat-list", "--types", "p2p", "--page-size", "50"])
    if not result.get("ok"):
        return []
    return [
        c for c in result["data"].get("chats", [])
        if c.get("p2p_target_type") == "user"
    ]


# ============================================================
# Fetch Lark system bot notifications (doc @mentions, permission requests, etc.)
# Bot chat IDs are auto-discovered from P2P chat list by bot name keywords
# ============================================================
def fetch_system_bot_messages(start_time: datetime, end_time: datetime,
                               my_open_id: str) -> list:
    """
    Reads messages from system bots like "云文档助手" / "Drive Assistant"
    that contain doc @mentions, permission requests, and permission changes.
    No extra permissions needed — uses existing im:message scope.
    """
    # Keywords to identify relevant system bots
    DOC_BOT_KEYWORDS = [
        "云文档", "drive", "doc", "文档助手", "多维表格", "bitable",
        "wiki", "sheet", "spreadsheet"
    ]

    result = run_lark_cli(["im", "+chat-list", "--types", "p2p", "--page-size", "50"])
    if not result.get("ok"):
        return []

    bot_chats = [
        c for c in result["data"].get("chats", [])
        if c.get("p2p_target_type") == "bot"
        and any(kw in c.get("name", "").lower() for kw in DOC_BOT_KEYWORDS)
    ]

    messages = []
    for chat in bot_chats:
        chat_name = chat.get("name", "System Bot")
        msgs_result = run_lark_cli([
            "im", "+chat-messages-list",
            "--chat-id", chat["chat_id"],
            "--page-size", "50"
        ])
        if not msgs_result.get("ok"):
            continue

        for msg in msgs_result["data"].get("messages", []):
            try:
                msg_time = datetime.strptime(msg["create_time"], "%Y-%m-%d %H:%M")
            except Exception:
                continue

            if msg_time < start_time or msg_time > end_time:
                continue
            if msg.get("deleted"):
                continue

            # Only keep messages that mention me
            mentions = msg.get("mentions", [])
            at_me = any(m.get("id") == my_open_id for m in mentions)
            if not at_me:
                continue

            import re
            content_raw = msg.get("content", "")
            content_clean = re.sub(r"<[^>]+>", "", content_raw)
            content_clean = content_clean.replace("\n", " ").replace("\r", "").strip()
            if len(content_clean) > 200:
                content_clean = content_clean[:200] + "..."

            if content_clean:
                messages.append(
                    f"[{chat_name}] {msg['create_time']} {content_clean}"
                )

    return messages


# ============================================================
# Fetch messages from a chat within the time range
# max_messages 控制每个群最多拉多少条（时间跨度越长应越大）
# ============================================================
def fetch_messages(chat_id: str, start_time: datetime, end_time: datetime,
                   my_open_id: str, is_p2p: bool = False,
                   max_messages: int = 50) -> list:
    messages = []
    page_token = None

    while len(messages) < max_messages:
        args = ["im", "+chat-messages-list", "--chat-id", chat_id, "--page-size", "50"]
        if page_token:
            args += ["--page-token", page_token]

        result = run_lark_cli(args)
        if not result.get("ok"):
            break

        page_data = result.get("data", {})
        found_in_page = 0
        for msg in page_data.get("messages", []):
            try:
                msg_time = datetime.strptime(msg["create_time"], "%Y-%m-%d %H:%M")
            except Exception:
                continue

            if msg_time < start_time or msg_time > end_time:
                continue
            if msg.get("deleted"):
                continue
            if msg.get("msg_type") in ["system", "image", "file", "sticker"]:
                continue

            if not is_p2p:
                mentions = msg.get("mentions", [])
                at_me = any(m.get("id") == my_open_id for m in mentions)
                at_all = "@_all" in msg.get("content", "") or "@all" in msg.get("content", "")
                if not at_me and not at_all:
                    continue

            messages.append(msg)
            found_in_page += 1

        # 没有更多分页，或这一页没有符合时间范围的消息（说明已超出范围），停止
        if not page_data.get("has_more") or found_in_page == 0:
            break
        page_token = page_data.get("page_token")
        if not page_token:
            break

    return messages[:max_messages]


# ============================================================
# Format a message as a text line
# ============================================================
def format_message(msg: dict, chat_name: str, my_open_id: str) -> str:
    sender = msg.get("sender", {}).get("name") or "System"
    time_str = msg.get("create_time", "")
    content = msg.get("content", "")
    content = re.sub(r"<[^>]+>", "", content)
    content = content.replace("\n", " ").replace("\r", "").strip()
    if len(content) > 200:
        content = content[:200] + "..."

    tag = "[Me]" if msg.get("sender", {}).get("id") == my_open_id else f"[{sender}]"
    return f"[{chat_name}] {time_str} {tag} {content}"


# ============================================================
# Fetch document activities (requires search:docs:read permission)
# ============================================================
def fetch_doc_activities(start_time: datetime, end_time: datetime) -> list:
    """
    Fetches within the time range:
    1. Documents I edited or created
    2. Documents I commented on

    Requires: search:docs:read permission
    Skipped automatically if permission is not granted.
    """
    results = []
    date_str = start_time.strftime("%Y-%m-%d")

    # Documents I edited
    print("  · Fetching documents I edited...")
    edited = run_lark_cli([
        "drive", "+search",
        "--edited-since", date_str,
        "--page-size", "20"
    ])
    if edited.get("ok"):
        for doc in edited.get("data", {}).get("items", []):
            title = doc.get("title") or "Untitled"
            url = doc.get("url") or ""
            results.append(f"[Doc-Edited] {title} {url}")
    elif "missing_scope" in str(edited.get("error", {})):
        print("  ⚠️  Document permission not granted (search:docs:read). Skipping doc monitoring.")
        return []

    # Documents I commented on
    print("  · Fetching documents I commented on...")
    commented = run_lark_cli([
        "drive", "+search",
        "--commented-since", date_str,
        "--page-size", "20"
    ])
    if commented.get("ok"):
        for doc in commented.get("data", {}).get("items", []):
            title = doc.get("title") or "Untitled"
            url = doc.get("url") or ""
            entry = f"[Doc-Commented] {title} {url}"
            if entry not in results:
                results.append(entry)

    return results


# ============================================================
# Call AI to generate the report
# Supports any OpenAI-compatible API
# ============================================================
def call_ai(messages_text: str, doc_text: str, mode: str, config: dict,
            total_count: int = 0, time_desc: str = "",
            duration_days: int = 1) -> str:
    ai_cfg = config.get("ai", {})
    api_key = ai_cfg.get("api_key", "")
    base_url = ai_cfg.get("base_url", "https://api.deepseek.com")
    model = ai_cfg.get("model", "deepseek-chat")

    # token 上限：日报1500 / 周报4000 / 长查询（>30天）8000
    if duration_days > 30:
        max_tokens = ai_cfg.get("max_tokens_longquery", 8000)
    elif mode == "weekly":
        max_tokens = ai_cfg.get("max_tokens_weekly", 4000)
    else:
        max_tokens = ai_cfg.get("max_tokens", 1500)

    if not api_key:
        return "AI API key not configured. Skipping AI generation."

    lines = [l for l in messages_text.strip().split("\n") if l.strip()]
    total = total_count or len(lines)

    # 采样上限：日报200 / 周报400 / 长查询600
    limit = 200 if mode == "daily" else (600 if duration_days > 30 else 400)
    if len(lines) > limit:
        if mode == "daily":
            sampled = lines[-limit:]
            sample_desc = f"最新 {limit} 条"
        else:
            step = len(lines) / limit
            indices = [int(i * step) for i in range(limit)]
            sampled = [lines[i] for i in indices]
            sample_desc = f"均匀采样 {limit} 条（覆盖完整时间段）"
        messages_text = "\n".join(sampled)
        messages_text = (f"【说明】总消息数 {total} 条，时间范围：{time_desc}，"
                         f"以下为{sample_desc}\n\n") + messages_text
    elif time_desc:
        messages_text = f"【说明】时间范围：{time_desc}，共 {total} 条消息\n\n" + messages_text

    doc_section = f"\n\nDocument Activity:\n{doc_text}" if doc_text else ""

    # ── 长时间查询（>30天）：按月份/主题分类，不限单条字数 ──
    if duration_days > 30:
        prompt = f"""你是一个工作助手。以下是 {time_desc} 的飞书消息记录（从 {total} 条均匀采样），请生成一份完整的工作总结。

注意：这是一段较长时间的回顾，请覆盖整个时间段，不要只聚焦最近的内容。

严格按以下JSON格式输出，不输出任何其他内容，不要加markdown代码块：
{{"overview":"综合概括这段时间的工作重点和主要成果，不限字数","period_highlights":"按时间段或主题列出主要工作，格式：· X月/主题名：主要内容，用\\n分隔，尽量列出所有重要事项","key_actions":"重要的执行事项和决策，每条格式：· 内容，用\\n分隔","my_participation":"整个时期参与的主要项目、讨论和工作","leave_records":[{{"person":"姓名","period":"时间","reason":"原因"}}]}}

要求：全部中文，内容要详实，覆盖整个时间段，不要省略重要工作。

消息记录：
{messages_text}{doc_section}"""

    elif mode == "weekly":
        prompt = f"""你是一个工作助手。请根据以下飞书群聊、私信和文档通知记录，生成工作周报。

严格按以下JSON格式输出，不输出任何其他内容，不要加markdown代码块：
{{"overview":"3-5句话总结本周工作","group_highlights":"各群重点，每条格式：· 群名：内容，用\\n分隔","dm_highlights":"私信重点，没有填暂无","doc_activity":"文档通知，没有填暂无","action_items":"与我相关的待跟进，格式：· 谁@我：内容，没有填暂无","my_participation":"本周参与了哪些重要讨论","leave_records":[{{"person":"请假人姓名","period":"请假时间如6月30日上半天","reason":"原因，没有可留空字符串"}}]}}

要求：每条不超过60字，全部中文。leave_records 从消息中提取所有请假申请，没有则填 []。

消息记录：
{messages_text}{doc_section}"""

    else:  # daily
        prompt = f"""你是一个工作助手。请根据以下飞书群聊、私信和文档通知记录，生成工作日报。

严格按以下JSON格式输出，不输出任何其他内容，不要加markdown代码块：
{{"overview":"2-3句话总结今天主要在做什么","group_highlights":"各群重点，每条格式：· 群名：内容，用\\n分隔","doc_activity":"文档通知，没有填暂无","action_items":"与我相关的待跟进，格式：· 谁@我：内容，没有填暂无","my_participation":"今天参与了哪些讨论","leave_records":[{{"person":"请假人姓名","period":"请假时间如6月30日上半天","reason":"原因，没有可留空字符串"}}]}}

要求：每条不超过50字，全部中文。leave_records 从消息中提取所有请假申请，没有则填 []。

消息记录：
{messages_text}{doc_section}"""

    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens
    }, ensure_ascii=False).encode("utf-8")

    url = base_url.rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        url, data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        return f"AI call failed (HTTP {e.code}): {e.read().decode('utf-8', errors='ignore')}"
    except Exception as e:
        return f"AI call failed: {e}"


# ============================================================
# Send report to Lark/Feishu via bot (line by line)
# ============================================================
def send_to_feishu(text: str, my_open_id: str):
    """Send the full report as a plain text message.

    Windows cmd.exe 无法在命令行参数中传递真实换行符（\n 会被当成命令结束）。
    这里把换行符替换为安全字符，lark-cli 会把 \\n 透传给飞书 API，
    飞书文本消息渲染时识别 \\n 为换行。
    """
    # 去掉 markdown 加粗符号（纯文本消息不渲染 **），换行转 \\n
    text_safe = text.replace("**", "").replace("\n", "\\n")

    try:
        cmd = [LARK_CLI, "im", "+messages-send",
               "--user-id", my_open_id,
               "--text", text_safe,
               "--as", "bot"]
        result_bytes = subprocess.run(cmd, capture_output=True, shell=True)
        stdout = result_bytes.stdout.decode("utf-8", errors="replace").strip()
        try:
            stderr = result_bytes.stderr.decode("utf-8").strip()
        except UnicodeDecodeError:
            stderr = result_bytes.stderr.decode("gbk", errors="replace").strip()

        result_text = stdout or stderr
        result = json.loads(result_text) if result_text else {}
        if result.get("ok"):
            return True
        err_msg = result.get("error", {}).get("message", "")
        if stderr and not err_msg:
            err_msg = stderr[:200]
        print(f"  Send failed: {err_msg or 'unknown error'}")
        return False
    except Exception as e:
        print(f"  Send error: {e}")
        return False


# ============================================================
# Main
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="Lark/Feishu Automatic Daily & Weekly Report Generator"
    )
    parser.add_argument("--mode", choices=["daily", "weekly"], default="daily",
                        help="报告模式：daily=日报，weekly=周报")
    parser.add_argument("--start", default=None,
                        help="自定义起始时间，格式：'2026-06-28 09:00'（指定后覆盖默认时间范围）")
    parser.add_argument("--end", default=None,
                        help="自定义结束时间，格式：'2026-06-29 18:30'（指定后覆盖默认时间范围）")
    args = parser.parse_args()

    config = load_config()
    my_open_id = config["lark"]["my_open_id"]
    enable_docs = config.get("features", {}).get("enable_docs", False)
    now = datetime.now()

    # ── 时间范围计算 ──
    if args.start and args.end:
        # 自定义时间范围（--start / --end 优先级最高）
        try:
            start_time = datetime.strptime(args.start, "%Y-%m-%d %H:%M")
            end_time   = datetime.strptime(args.end,   "%Y-%m-%d %H:%M")
        except ValueError:
            print("❌ 时间格式错误，请使用 'YYYY-MM-DD HH:MM'，例如：--start '2026-06-28 09:00'")
            sys.exit(1)
        report_title = (f"[查询] {start_time.strftime('%Y-%m-%d %H:%M')}"
                        f" ~ {end_time.strftime('%Y-%m-%d %H:%M')}  生成于 {now.strftime('%H:%M')}")

    elif args.mode == "daily":
        # 日报：前一天 18:30 → 今天 18:30（定时任务 18:30 触发时正好覆盖过去24h）
        report_end = now.replace(hour=18, minute=30, second=0, microsecond=0)
        if now < report_end:          # 提前手动跑时，结束时间用当前时间
            report_end = now
        start_time = report_end - timedelta(hours=24)
        end_time   = report_end
        report_title = f"[日报] {now.strftime('%Y-%m-%d')}  生成于 {now.strftime('%H:%M')}"

    else:  # weekly
        # 周报：上周五 00:00 → 本周五 00:00（周日 15:30 触发）
        # weekday(): 周一=0 … 周五=4 … 周日=6
        days_since_fri = (now.weekday() - 4) % 7   # 距离最近已过去的周五天数
        if days_since_fri == 0:
            days_since_fri = 7          # 今天就是周五，取上一个周五
        this_fri = (now - timedelta(days=days_since_fri)).replace(
            hour=0, minute=0, second=0, microsecond=0)
        last_fri = this_fri - timedelta(days=7)
        start_time = last_fri
        end_time   = this_fri
        report_title = (f"[周报] {start_time.strftime('%m-%d')}"
                        f" ~ {end_time.strftime('%m-%d')}  生成于 {now.strftime('%H:%M')}")

    # 根据时间跨度决定每个群拉多少条（跨度越长抓越多，否则长期查询只能看到最近几天）
    duration_days = max(1, (end_time - start_time).days)
    if duration_days <= 1:
        max_msgs_per_chat = 50
    elif duration_days <= 7:
        max_msgs_per_chat = 100
    elif duration_days <= 30:
        max_msgs_per_chat = 200
    else:
        max_msgs_per_chat = 500   # 长时间查询，尽量多拉（半年约 180 天）

    time_desc = f"{start_time.strftime('%Y-%m-%d %H:%M')} ~ {end_time.strftime('%Y-%m-%d %H:%M')}（{duration_days}天）"
    print(f"模式: {args.mode} | {time_desc} | 每群最多抓 {max_msgs_per_chat} 条")

    # Fetch group messages
    print("\n拉取群列表中...")
    all_chats = fetch_all_chats()
    print(f"共找到 {len(all_chats)} 个群")

    raw_messages = []

    print("\n抓取群消息（仅@我和@所有人）...")
    for chat in all_chats:
        chat_name = chat.get("name") or "Unnamed Group"
        print(f"  · {chat_name}")
        msgs = fetch_messages(chat["chat_id"], start_time, end_time, my_open_id,
                              is_p2p=False, max_messages=max_msgs_per_chat)
        for msg in msgs:
            raw_messages.append(format_message(msg, chat_name, my_open_id))

    # Fetch DMs
    print("\n抓取私信中...")
    p2p_chats = fetch_p2p_chats()
    for chat in p2p_chats:
        chat_name = chat.get("name") or "Unknown Contact"
        msgs = fetch_messages(chat["chat_id"], start_time, end_time, my_open_id,
                              is_p2p=True, max_messages=max_msgs_per_chat)
        if msgs:
            print(f"  · 私信: {chat_name} ({len(msgs)}条)")
            for msg in msgs:
                raw_messages.append(format_message(msg, f"DM-{chat_name}", my_open_id))

    # Fetch system bot notifications (doc @mentions, permission requests)
    print("\n抓取文档通知中...")
    bot_messages = fetch_system_bot_messages(start_time, end_time, my_open_id)
    if bot_messages:
        print(f"  发现 {len(bot_messages)} 条文档通知")
        raw_messages.extend(bot_messages)
    else:
        print("  今日暂无文档通知")

    print(f"\n共抓取 {len(raw_messages)} 条消息")

    # Fetch document activities (requires search:docs:read, controlled by config)
    doc_activities = []
    if enable_docs:
        print("\nFetching document activities...")
        doc_activities = fetch_doc_activities(start_time, end_time)
        print(f"Total document activities: {len(doc_activities)}")
    else:
        print("\n文档监控未启用（在 config.json 中设置 features.enable_docs: true 开启）")

    # Generate report with AI
    print("\nAI 生成报告中...")
    messages_text = "\n".join(raw_messages) if raw_messages else "No relevant messages today."
    doc_text = "\n".join(doc_activities) if doc_activities else ""
    ai_summary = call_ai(messages_text, doc_text, args.mode, config,
                         total_count=len(raw_messages), time_desc=time_desc,
                         duration_days=duration_days)
    print("AI 生成完成")

    # Assemble report
    divider = "=" * 32
    footer = f"共 {len(raw_messages)} 条消息 | {len(all_chats)} 个群组"
    if doc_activities:
        footer += f" | 文档通知: {len(doc_activities)} 条"
    report = f"{report_title}\n{divider}\n{ai_summary}\n{divider}\n{footer}"

    # Parse AI JSON and send as card
    print("\n构建消息卡片并发送...")

    try:
        # fix: lstrip/rstrip按字符集删除，用re.sub才能删子字符串
        ai_text = re.sub(r"^```(?:json)?\s*", "", ai_summary.strip())
        ai_text = re.sub(r"\s*```$", "", ai_text).strip()
        data = json.loads(ai_text)
    except Exception:
        data = {"overview": ai_summary}

    is_weekly = (args.mode == "weekly")
    elements = []

    def add_section(label, value):
        if value and str(value).strip() not in ("", "暂无"):
            elements.append({"tag": "markdown", "content": f"**{label}**\n{value}"})
            elements.append({"tag": "hr"})

    if duration_days > 30:
        # 长查询：专属字段
        add_section(f"【{time_desc} 工作概览】", data.get("overview", ""))
        add_section("【各阶段工作重点】", data.get("period_highlights", ""))
        add_section("【重要执行事项】", data.get("key_actions", ""))
        add_section("【参与的主要项目】", data.get("my_participation", ""))
    else:
        add_section("【工作概览】" if not is_weekly else "【本周工作概览】", data.get("overview", ""))
        add_section("【各群重点】", data.get("group_highlights", ""))
        if is_weekly:
            add_section("【私信重点】", data.get("dm_highlights", ""))
        add_section("【文档通知】", data.get("doc_activity", ""))
        add_section("【待跟进事项】", data.get("action_items", ""))
        add_section("【我的参与】" if not is_weekly else "【本周参与度】", data.get("my_participation", ""))

    # 【请假情况】表格（飞书 card v2.0，只保留确定支持的属性）
    leave_records = data.get("leave_records", [])
    if isinstance(leave_records, list) and leave_records:
        elements.append({"tag": "markdown", "content": "**【请假情况】**"})
        elements.append({
            "tag": "table",
            "columns": [
                {"name": "person", "display_name": "请假人",   "width": "auto"},
                {"name": "period", "display_name": "请假周期", "width": "auto"},
                {"name": "reason", "display_name": "备注",     "width": "auto"},
            ],
            "rows": [
                {
                    "person": str(r.get("person", "")),
                    "period": str(r.get("period", "")),
                    "reason": str(r.get("reason", "")),
                }
                for r in leave_records
            ]
        })
        elements.append({"tag": "hr"})

    # Footer（text_size / text_color 是无效属性，去掉；用 italic 降低视觉权重）
    elements.append({"tag": "markdown", "content": f"_{footer}_"})

    card = {
        "schema": "2.0",
        "header": {"title": {"tag": "plain_text", "content": report_title}, "template": "blue"},
        "body": {"direction": "vertical", "elements": elements}
    }

    card_json = json.dumps(card, ensure_ascii=False)

    # ── 发送 card：优先直接调底层二进制，绕开 .cmd → cmd.exe 链路 ──
    # .cmd 包装器把参数传给 cmd.exe，cmd.exe 遇到 JSON 双引号就解析乱（'108'报错根因）。
    # get_lark_direct_cmd() 读取 .cmd 内容找底层 .exe/.js；找到则直接 CreateProcess，
    # 找不到则退回 .cmd + shell=True（此时 JSON 仍可能乱，但至少尝试一次）。
    using_direct = not (len(LARK_DIRECT) == 1 and str(LARK_DIRECT[0]).endswith(".cmd"))

    card_sent = False
    try:
        result_bytes = subprocess.run(
            LARK_DIRECT + [
                "im", "+messages-send",
                "--user-id", my_open_id,
                "--msg-type", "interactive",
                "--content", card_json,
                "--as", "bot",
            ],
            capture_output=True,
            shell=(not using_direct)   # 直接二进制不需要 shell；.cmd 需要
        )
        out = result_bytes.stdout.decode("utf-8", errors="replace").strip()
        try:
            err = result_bytes.stderr.decode("utf-8").strip()
        except UnicodeDecodeError:
            err = result_bytes.stderr.decode("gbk", errors="replace").strip()

        try:
            res = json.loads(out) if out else {}
        except Exception:
            res = {}

        if res.get("ok"):
            card_sent = True
            print("✅ 报告发送成功！（card 格式）")
        else:
            diag = err or out or str(res)
            print(f"  card 发送失败: {diag[:300]}")
    except Exception as e:
        print(f"  card 发送异常: {e}")

    # ── 方案2：降级为纯文本（保底方案）──
    if not card_sent:
        print("  → 退回文本格式发送...")
        sections = [
            ("【工作概览】" if not is_weekly else "【本周工作概览】", "overview"),
            ("【各群重点】", "group_highlights"),
            ("【文档通知】", "doc_activity"),
            ("【待跟进事项】", "action_items"),
            ("【我的参与】" if not is_weekly else "【本周参与度】", "my_participation"),
        ]
        if is_weekly:
            sections.insert(2, ("【私信重点】", "dm_highlights"))
        text_parts = [report_title]
        for label, key in sections:
            val = str(data.get(key, "")).strip()
            if val and val != "暂无":
                text_parts.append(f"{label}: {val}")
        text_parts.append(footer)
        fallback_text = "\n".join(text_parts)

        if send_to_feishu(fallback_text, my_open_id):
            print("✅ 报告发送成功！（文本格式）")
        else:
            print("❌ 发送失败，原始AI输出：")
            print(ai_summary)


if __name__ == "__main__":
    main()
