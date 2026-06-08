"""AI 分析器 - 支持多个后端，优先选免费方案

优先级（自动选择）：
1. Gemini API（GEMINI_API_KEY，完全免费：1500次/天）
2. Anthropic SDK（ANTHROPIC_API_KEY，付费）
3. Claude Code CLI（本地，使用 claude 命令额度）
4. 无 AI（直接输出原始内容）

Gemini 免费申请：https://aistudio.google.com/app/apikey
"""
import os
import json
import logging
import subprocess
import time

# 清除 SOCKS 代理变量，防止 google-genai/httpx 报错
for _k in ("ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)

logger = logging.getLogger(__name__)

MAX_BATCH_SIZE = 10  # 减小批次，避免 Gemini 长响应解析问题


def _build_prompt(items: list[dict]) -> str:
    lines = ["你是具身智能/机器人领域顶级研究员，请精读以下论文摘要并提炼关键信息。\n禁止泛泛而谈，每个字段必须来自原文具体内容。\n"]
    for i, item in enumerate(items):
        title = item.get("title", "")
        summary = item.get("summary", "")[:800]
        intro = item.get("intro", "")[:800]
        body = f"摘要: {summary}"
        if intro:
            body += f"\n    引言: {intro}"
        lines.append(f"[{i}] 标题: {title}\n    {body}")

    lines.append("""
请输出 JSON 数组（只输出数组）：
[
  {
    "index": 0,
    "direction": "研究方向标签，从以下选一个：VLA基础/VLA+强化学习/VLA+世界模型/VLA+3D感知/数据采集与标注/灵巧操作/人形机器人/具身导航/多模态感知/其他",
    "problem": "现有方法具体存在什么问题？写出具体场景和原因，如：现有VLA在遮挡场景下因缺乏注意力机制导致操作失败率高。禁止写"X是挑战"类废话",
    "method": "方法名称+核心机制+与现有方法的本质区别，如：提出Gaze2Act，将人类注视点条件化输入VLA，首次引入眼动数据指导注意力",
    "result": "原文的具体实验结果（基准名称+数字），无数字则写关键定性结论，禁止编造",
    "summary": "核心创新是X，解决了Y，意义是Z（一句话，要有信息量）",
    "relevance": 5
  }
]
relevance 评分（严格执行）:
5 = 直接研究 VLA、具身智能、人形/四足机器人操作、机器人学习
4 = 机器人操作/灵巧手/强化学习用于机器人控制/运动/导航/sim-to-real
3 = 具身AI基础技术（3D感知、世界模型）且明确与机器人相关
2 = 通用强化学习无机器人场景、通用NLP、非机器人视觉
1 = 完全无关
注意：1)内容详实；2)效果只写原文有的数据，无数字写"原文未提供具体指标"；3)纯游戏/理论RL打2分；4)禁止套话（禁用"对研究者来说""提供新思路"等），总结须体现该论文独特贡献""")

    return "\n".join(lines)


def _parse_ai_response(response: str, items: list[dict]) -> list[dict]:
    try:
        # 去掉 markdown 代码块包装（```json ... ```）
        text = response.strip()
        if "```" in text:
            import re
            text = re.sub(r"```(?:json)?\s*", "", text).strip()

        # 找第一个 JSON 数组起点
        import re as _re_inner
        m = _re_inner.search(r'\[\s*\{', text)
        if not m:
            logger.warning(f"AI 响应未找到 JSON 数组，原文: {text[:300]}")
            return items
        start = m.start()

        # 从 start 到结尾整体解析（处理截断情况）
        parsed = None
        # 先尝试完整解析
        for end_pos in [len(text), text.rfind("]") + 1]:
            if end_pos <= start:
                continue
            try:
                parsed = json.loads(text[start:end_pos])
                break
            except json.JSONDecodeError:
                pass

        if parsed is None:
            logger.warning("AI 响应 JSON 数组结构异常，跳过本批次")
            return items
        index_map = {r["index"]: r for r in parsed if "index" in r}

        for i, item in enumerate(items):
            if i in index_map:
                r = index_map[i]
                parts = []
                if r.get("direction"):
                    item["direction"] = r["direction"]
                if r.get("problem") and r["problem"] != "无":
                    parts.append(f"**问题**: {r['problem']}")
                if r.get("method"):
                    parts.append(f"**方法**: {r['method']}")
                if r.get("result") and r["result"] != "无":
                    parts.append(f"**效果**: {r['result']}")
                if r.get("summary"):
                    parts.append(f"**总结**: {r['summary']}")
                item["ai_analysis"] = "\n".join(parts)
                item["relevance"] = r.get("relevance", 3)
    except Exception as e:
        logger.warning(f"AI 响应解析失败: {e}")

    return items



# ─── Groq ────────────────────────────────────────────────────────────────────

def analyze_with_groq(items: list[dict], max_tokens: int) -> list[dict]:
    """使用 Groq API（免费：500,000 tokens/天，无需绑卡）
    申请：https://console.groq.com
    """
    try:
        from groq import Groq
    except ImportError:
        logger.warning("groq 未安装：pip install groq")
        return items

    client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))
    for start in range(0, len(items), MAX_BATCH_SIZE):
        batch = items[start: start + MAX_BATCH_SIZE]
        prompt = _build_prompt(batch)
        try:
            chat = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=6000,
                temperature=0.1,
            )
            text = chat.choices[0].message.content or ""
            items[start: start + MAX_BATCH_SIZE] = _parse_ai_response(text, batch)
            time.sleep(1)
        except Exception as e:
            logger.warning(f"Groq 批次 {start} 失败: {e}")
    return items

# ─── Gemini ──────────────────────────────────────────────────────────────────

# 模型降级顺序：lite → flash → 1.5-flash
_GEMINI_FALLBACK_MODELS = [
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
]


def _call_gemini(client, model: str, prompt: str, max_tokens: int) -> str:
    """单次 Gemini 调用，失败时透传异常"""
    from google.genai import types
    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            temperature=0.1,
        ),
    )
    return resp.text or ""


def analyze_with_gemini(items: list[dict], model: str, max_tokens: int) -> list[dict]:
    """使用 Google Gemini API（免费：1500 次/天）
    当指定模型配额耗尽时自动降级到其他免费模型。
    """
    try:
        from google import genai
    except ImportError:
        logger.warning("google-genai 未安装，跳过 Gemini 分析")
        return items

    api_key = os.environ.get("GEMINI_API_KEY", "")
    client = genai.Client(api_key=api_key)

    # 构建降级列表：指定模型优先，其次按 fallback 顺序
    model_queue = [model] + [m for m in _GEMINI_FALLBACK_MODELS if m != model]

    for start in range(0, len(items), MAX_BATCH_SIZE):
        batch = items[start: start + MAX_BATCH_SIZE]
        prompt = _build_prompt(batch)
        success = False

        for try_model in model_queue:
            try:
                text = _call_gemini(client, try_model, prompt, max_tokens)
                items[start: start + MAX_BATCH_SIZE] = _parse_ai_response(text, batch)
                if try_model != model:
                    logger.info(f"已降级到 {try_model}")
                time.sleep(10)  # gemini-2.5-flash，10s 间隔
                success = True
                break
            except Exception as e:
                err = str(e)
                if "429" in err or "RESOURCE_EXHAUSTED" in err:
                    logger.warning(f"  {try_model} 配额耗尽，尝试下一个模型")
                    time.sleep(2)
                else:
                    logger.warning(f"  {try_model} 失败: {err[:100]}")
                    break

        if not success:
            logger.warning(f"批次 {start} 所有 Gemini 模型均失败，跳过")

    return items


# ─── Anthropic ───────────────────────────────────────────────────────────────

def analyze_with_anthropic(items: list[dict], model: str, max_tokens: int) -> list[dict]:
    """使用 Anthropic SDK（需要 ANTHROPIC_API_KEY）"""
    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic 未安装，跳过")
        return items

    client = anthropic.Anthropic()
    for start in range(0, len(items), MAX_BATCH_SIZE):
        batch = items[start: start + MAX_BATCH_SIZE]
        prompt = _build_prompt(batch)
        try:
            msg = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            items[start: start + MAX_BATCH_SIZE] = _parse_ai_response(
                msg.content[0].text, batch
            )
            time.sleep(0.5)
        except Exception as e:
            logger.warning(f"Anthropic 批次 {start} 失败: {e}")

    return items


# ─── Claude CLI ──────────────────────────────────────────────────────────────

def _fix_tables(text: str) -> str:
    """去掉表格行之间的空行，修复 markdown 表格渲染"""
    lines = text.splitlines()
    result = []
    for i, line in enumerate(lines):
        if line.strip() == "" and result:
            prev = result[-1].strip()
            next_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
            # 跳过夹在两个表格行之间的空行
            if (prev.startswith("|") or prev.startswith("|-")) and \
               (next_line.startswith("|") or next_line.startswith("|-")):
                continue
        result.append(line)
    return "\n".join(result)


def _build_prompt_single(item: dict) -> str:
    title = item.get("title", "")
    summary = item.get("summary", "")[:1000]
    intro = item.get("intro", "")[:1000]
    content = f"标题：{title}\n\n摘要：{summary}"
    if intro:
        content += f"\n\n引言：{intro}"
    return f"""你是具身智能/机器人领域的顶级研究员。请精读以下论文内容，用中文写一份深度分析。

{content}

---

请按以下格式输出（直接输出，不要加任何前缀）：

relevance: <1-5的整数>
direction: <从以下选一个：VLA基础/VLA+强化学习/VLA+世界模型/VLA+3D感知/数据采集与标注/灵巧操作/人形机器人/具身导航/多模态感知/其他>

<分析正文>

relevance 评分标准：
5 = 直接研究 VLA、具身智能、人形/四足机器人操作、机器人学习
4 = 机器人操作/灵巧手/强化学习用于机器人/导航/sim-to-real
3 = 具身AI基础技术且明确与机器人相关
2 = 通用强化学习无机器人场景、通用NLP、非机器人视觉
1 = 完全无关

分析正文格式：
这篇论文解决的是**<核心问题，加粗>**。

---

**根本矛盾**：<现有方法为什么不够用，一句话>

| 现有方法 | 问题所在 |
|---|---|
| <方法1> | <具体缺陷> |

---

**他们的解法 <方法名>**：

1. <核心机制1>
2. <核心机制2>

---

**效果**：<原文中的实验结果，必须包含具体数字/基准名称，如"在 LIBERO-90 上成功率 87.3%，比基线提升 12pp"；若原文无具体指标则写"论文未提供定量结果">

---

**一句话概括**：<体现该论文独特贡献，禁止套话>

要求：每个字段来自原文，禁止编造数据；若与机器人完全无关，relevance 填 1，正文只写一行说明原因。"""


def analyze_with_claude_cli(items: list[dict]) -> list[dict]:
    """使用本地 claude CLI，每篇单独调用，输出叙述式分析"""
    for i, item in enumerate(items):
        prompt = _build_prompt_single(item)
        try:
            result = subprocess.run(
                ["claude", "-p", prompt, "--output-format", "text"],
                capture_output=True,
                text=True,
                timeout=180,
            )
            if result.returncode != 0:
                logger.warning(f"claude CLI 错误 [{i}]: {result.stderr[:200]}")
                continue

            text = result.stdout.strip()
            lines = text.splitlines()
            relevance = 3
            direction = ""
            body_start = 0
            for j, line in enumerate(lines[:4]):
                if line.startswith("relevance:"):
                    try:
                        relevance = int(line.split(":")[1].strip())
                    except ValueError:
                        pass
                    body_start = j + 1
                elif line.startswith("direction:"):
                    direction = line.split(":", 1)[1].strip()
                    body_start = j + 1

            body = _fix_tables("\n".join(lines[body_start:]).strip())
            item["relevance"] = relevance
            if direction:
                item["direction"] = direction
            item["ai_analysis"] = body
            logger.info(f"  [{i+1}/{len(items)}] 完成: relevance={relevance}")

        except FileNotFoundError:
            logger.warning("未找到 claude CLI")
            break
        except subprocess.TimeoutExpired:
            logger.warning(f"claude CLI 超时 [{i+1}/{len(items)}]，跳过")

    return items


# ─── 主入口 ──────────────────────────────────────────────────────────────────

def analyze(items: list[dict], ai_config: dict) -> list[dict]:
    """自动选择最优 AI 后端（优先免费）"""
    if not items:
        return items

    gemini_model = ai_config.get("gemini_model", "gemini-2.0-flash-lite")
    claude_model = ai_config.get("model", "claude-haiku-4-5-20251001")
    max_tokens = ai_config.get("max_tokens", 1024)

    # 1. Groq（免费，无需绑卡，优先）
    if os.environ.get("GROQ_API_KEY"):
        logger.info("使用 Groq API 分析 (llama-3.3-70b，免费)")
        return analyze_with_groq(items, max_tokens)

    # 2. Gemini（需绑卡，备用）
    if os.environ.get("GEMINI_API_KEY"):
        logger.info(f"使用 Gemini API 分析 ({gemini_model})")
        return analyze_with_gemini(items, gemini_model, max_tokens)

    # 3. Anthropic API
    if os.environ.get("ANTHROPIC_API_KEY"):
        logger.info(f"使用 Anthropic SDK 分析 ({claude_model})")
        return analyze_with_anthropic(items, claude_model, max_tokens)

    # 4. 本地 claude CLI
    try:
        r = subprocess.run(["claude", "--version"], capture_output=True, timeout=5)
        if r.returncode == 0:
            logger.info("使用 Claude Code CLI 分析")
            return analyze_with_claude_cli(items)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    logger.info("未配置任何 AI 后端，输出原始内容")
    return items
