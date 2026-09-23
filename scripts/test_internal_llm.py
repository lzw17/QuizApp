# -*- coding: utf-8 -*-
"""端到端验证：用应用自身的 LLM 客户端（明文 HTTP 内网网关）跑一次真实调用。"""
import os
import sys
import time

os.chdir("/www/wwwroot/quizapp/backend")
sys.path.insert(0, "/www/wwwroot/quizapp/backend")

from app.config import settings
from app.services.ai_engine import get_llm

print("BASE_URL   =", settings.llm_base_url)
print("MODEL      =", settings.llm_model)
print("MAX_TOKENS =", settings.LLM_MAX_TOKENS)
print("TIMEOUT    =", settings.LLM_TIMEOUT_SECONDS)
print("KEY        =", (settings.llm_api_key[:8] + "***") if settings.llm_api_key else "(空)")

llm = get_llm(temperature=0.3)
prompt = '请只输出一个 JSON 数组，不要任何解释、不要代码块标记：[{"content":"1+1=?","answer":"2","explanation":"基础运算"}]'

t0 = time.time()
resp = llm.invoke(prompt)
elapsed = time.time() - t0

content = resp.content
print("\n>>> 调用成功，耗时 %.1fs" % elapsed)
print("finish_reason =", (resp.response_metadata or {}).get("finish_reason"))
print("content 长度  =", len(content) if content else 0)
print("content 预览  =", repr(content)[:400])
print("JSON 可解析   =", content is not None and '[' in (content or ''))
