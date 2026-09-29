"""
AI 出题引擎
使用 OpenAI 兼容模型 + LangChain，双 Agent 并行生成直白题和逻辑题
"""
import json
import asyncio
import logging
from typing import List, Optional
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from ..config import settings
from ..schemas.question import QuestionCreate

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────
#  OpenAI 兼容模型客户端
# ──────────────────────────────────────────

# 按 temperature 复用客户端。此前每次调用都新建 ChatOpenAI（底层是 httpx/AsyncOpenAI），
# 且从不关闭——单个任务最多 100 个文本块 × 2 次生成 + 标签分类，会持续累积连接与
# 文件描述符（1G 机器上尤其危险）。复用后客户端数量恒定（≤ temperature 取值数）。
_LLM_CLIENTS: dict = {}


def get_llm(temperature: float = 0.7) -> ChatOpenAI:
    client = _LLM_CLIENTS.get(temperature)
    if client is None:
        client = ChatOpenAI(
            model=settings.llm_model,
            openai_api_key=settings.llm_api_key,
            openai_api_base=settings.llm_base_url,
            temperature=temperature,
            max_tokens=settings.LLM_MAX_TOKENS,
            timeout=settings.LLM_TIMEOUT_SECONDS,
            max_retries=settings.LLM_MAX_RETRIES,
        )
        _LLM_CLIENTS[temperature] = client
    return client


async def close_llm_clients() -> None:
    """释放复用的 LLM 客户端（进程退出时调用；幂等）。"""
    clients = list(_LLM_CLIENTS.values())
    _LLM_CLIENTS.clear()
    for client in clients:
        try:
            await client.async_client.close()
        except Exception:  # noqa: BLE001 - 关闭失败不应影响进程退出
            logger.debug("关闭 LLM 客户端失败", exc_info=True)


# ──────────────────────────────────────────
#  Prompt 模板
# ──────────────────────────────────────────

DIRECT_PROMPT = ChatPromptTemplate.from_template("""
你是一位专业出题专家，擅长从资料中提炼基础概念进行考查。

请根据以下文档内容，生成 {num} 道**直白型**题目（考查基本定义、概念、事实）。

要求：
1. 题型从以下随机选择：单选题(single)、多选题(multi)、判断题(judge)
2. 单选题和多选题必须有 A、B、C、D 四个选项；判断题选项为 [A:正确, B:错误]
3. 难度分布：简单(1-2) 40%、中等(3) 40%、困难(4-5) 20%
4. 每题必须包含详细的答案解析
5. 输出严格的 JSON 数组，不要任何其他文字

输出格式示例：
[
  {{
    "type": "single",
    "content": "题目内容",
    "options": [{{"key": "A", "text": "选项A"}}, {{"key": "B", "text": "选项B"}}, {{"key": "C", "text": "选项C"}}, {{"key": "D", "text": "选项D"}}],
    "answer": "A",
    "explanation": "详细解析...",
    "tags": ["知识点1", "知识点2"],
    "difficulty": 2
  }}
]

文档内容：
{context}
""")

LOGIC_PROMPT = ChatPromptTemplate.from_template("""
你是一位专业出题专家，擅长设计需要逻辑推理和综合理解的题目。

请根据以下文档内容，生成 {num} 道**逻辑推理型**题目（考查理解、应用、分析能力）。

要求：
1. 题型从以下随机选择：单选题(single)、多选题(multi)、判断题(judge)
2. 单选题和多选题必须有 A、B、C、D 四个选项；判断题选项为 [A:正确, B:错误]
3. 难度偏中高：中等(3) 40%、困难(4-5) 60%
4. 题目要有一定的迷惑性，考查深度理解
5. 输出严格的 JSON 数组，不要任何其他文字

输出格式与直白题相同：
[
  {{
    "type": "multi",
    "content": "题目内容（需要综合理解）",
    "options": [{{"key": "A", "text": "选项A"}}, {{"key": "B", "text": "选项B"}}, {{"key": "C", "text": "选项C"}}, {{"key": "D", "text": "选项D"}}],
    "answer": "AB",
    "explanation": "详细解析（说明为什么选这些）...",
    "tags": ["知识点1", "知识点2"],
    "difficulty": 4
  }}
]

文档内容：
{context}
""")


# ──────────────────────────────────────────
#  题目解析
# ──────────────────────────────────────────

def _parse_llm_output(raw: str) -> List[dict]:
    """从 LLM 输出中提取 JSON 数组，容错处理"""
    raw = raw.strip()
    # 去掉 markdown 代码块
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])

    # 找到第一个 [ 和最后一个 ]
    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end == -1:
        logger.warning("LLM 输出中未找到 JSON 数组（响应长度=%s）", len(raw))
        return []
    try:
        return json.loads(raw[start:end + 1])
    except json.JSONDecodeError as e:
        logger.warning(
            "LLM JSON 解析失败（位置=%s，响应长度=%s）",
            e.pos,
            len(raw),
        )
        return []


def _normalize_question(q: dict, bank_id: int, order_index: int) -> Optional[dict]:
    """标准化并验证题目字段"""
    if not isinstance(q, dict):
        return None
    try:
        validated = QuestionCreate(
            bank_id=bank_id,
            type=q.get("type", "single"),
            content=q.get("content", ""),
            options=q.get("options") or [],
            answer=q.get("answer", ""),
            explanation=q.get("explanation") or "",
            tags=q.get("tags") or [],
            difficulty=q.get("difficulty", 3),
        )
    except (TypeError, ValueError) as exc:
        logger.warning(
            "Skipping invalid generated question (%s)",
            type(exc).__name__,
        )
        return None

    normalized = validated.model_dump(exclude={"bank_id"})
    normalized["bank_id"] = bank_id
    normalized["order_index"] = order_index
    return normalized


# ──────────────────────────────────────────
#  核心生成函数
# ──────────────────────────────────────────

async def generate_from_chunk(
    chunk: str,
    bank_id: int,
    start_index: int,
    num_direct: int = 3,
    num_logic: int = 2,
) -> List[dict]:
    """
    对单个文本块调用双 Agent 并行出题
    返回标准化后的题目列表
    """
    llm = get_llm(temperature=0.8)
    parser = StrOutputParser()

    direct_chain = DIRECT_PROMPT | llm | parser
    logic_chain = LOGIC_PROMPT | llm | parser

    # 并行调用两个 Agent。return_exceptions=True 已保证单个失败不影响另一个，
    # 因此这里无需再包一层 try/except（旧代码的 except 永远不会触发）。
    direct_raw, logic_raw = await asyncio.gather(
        direct_chain.ainvoke({"context": chunk, "num": num_direct}),
        logic_chain.ainvoke({"context": chunk, "num": num_logic}),
        return_exceptions=True,
    )
    for raw, label in ((direct_raw, "直白题"), (logic_raw, "逻辑题")):
        if isinstance(raw, BaseException):
            logger.warning("%s LLM 调用失败（%s）", label, type(raw).__name__)

    all_raw = []
    if not isinstance(direct_raw, Exception):
        all_raw.extend(_parse_llm_output(direct_raw))
    if not isinstance(logic_raw, Exception):
        all_raw.extend(_parse_llm_output(logic_raw))

    # 标准化
    normalized = []
    for i, q in enumerate(all_raw):
        norm = _normalize_question(q, bank_id, start_index + i)
        if norm:
            normalized.append(norm)

    return normalized


# ──────────────────────────────────────────
#  知识点分类（可选的后处理步骤）
# ──────────────────────────────────────────

async def classify_questions_tags(questions: List[dict]) -> List[dict]:
    """
    批量补全/规范化知识点标签
    对已有 tags 的题目不做处理
    """
    needs_tag = [q for q in questions if not q.get("tags")]
    if not needs_tag:
        return questions

    llm = get_llm(temperature=0.3)
    batch_content = "\n".join(
        f"{i+1}. {q['content']}" for i, q in enumerate(needs_tag)
    )

    prompt = f"""
请为以下题目分别提供 1-3 个知识点标签（中文，简洁）。
输出格式：严格 JSON 数组，每项为字符串列表，如 [["标签1","标签2"], ["标签3"]]
不要任何其他文字。

题目列表：
{batch_content}
"""
    try:
        raw = await llm.ainvoke(prompt)
        # Reuse the tolerant parser so fenced JSON responses do not silently
        # discard otherwise valid tag classifications.
        tag_list = _parse_llm_output(raw.content)
        for i, q in enumerate(needs_tag):
            if i < len(tag_list):
                tags = tag_list[i] if isinstance(tag_list[i], list) else [tag_list[i]]
                q["tags"] = [str(tag).strip() for tag in tags if str(tag).strip()][:3]
    except Exception as e:
        logger.warning("标签分类失败（%s）", type(e).__name__)

    return questions
