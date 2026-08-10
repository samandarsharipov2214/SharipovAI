"""Qwen Coder API client for Self-Healing Agent."""
from __future__ import annotations
import json
import os
import urllib.request
from typing import Any

QWEN_API_URL = os.getenv("QWEN_API_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen-plus")

def ask_qwen(prompt: str, system: str = "You are a senior Python developer. Write clean, safe code.") -> str:
    api_key = os.environ["DASHSCOPE_API_KEY"]
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    data = json.dumps({
        "model": QWEN_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 4096,
    }).encode()
    req = urllib.request.Request(QWEN_API_URL, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read())
    return result["choices"][0]["message"]["content"]

def generate_fix(error_log: str, failing_test: str, source_code: str) -> str:
    prompt = f"""Fix the failing test in the project SharipovAI.
Error log:
{error_log}

Failing test:
{failing_test}

Relevant source code:
{source_code}

Return ONLY a unified diff (diff --git ...) without any explanations."""
    return ask_qwen(prompt, system="You are a senior Python developer. Write minimal, safe patches.")
