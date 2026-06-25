"""
题目去重工具
基于 Jaccard 相似度，避免生成重复题目
"""
import re
from typing import List


def _tokenize(text: str) -> set:
    """简单分词：按字符级别 + 保留中文词"""
    text = re.sub(r"[^\w\u4e00-\u9fff]", "", text.lower())
    # 中文按字符，英文按词
    tokens = set()
    for char in text:
        tokens.add(char)
    return tokens


def jaccard_similarity(text_a: str, text_b: str) -> float:
    """计算两段文本的 Jaccard 相似度"""
    set_a = _tokenize(text_a)
    set_b = _tokenize(text_b)
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union


def deduplicate_questions(questions: List[dict], threshold: float = 0.7) -> List[dict]:
    """
    输入题目列表（dict，含 content 字段），
    返回去重后的列表（Jaccard 相似度 >= threshold 则视为重复，保留先出现的）
    """
    kept = []
    for q in questions:
        content = q.get("content", "")
        is_dup = False
        for existing in kept:
            if jaccard_similarity(content, existing.get("content", "")) >= threshold:
                is_dup = True
                break
        if not is_dup:
            kept.append(q)
    return kept
