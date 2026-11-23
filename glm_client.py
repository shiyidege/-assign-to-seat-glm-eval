import json
import os
import re
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional


DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions"


def get_api_key() -> str:
    key = os.environ.get("GLM_API_KEY", "").strip()
    if not key:
        raise RuntimeError("请先设置环境变量 GLM_API_KEY")
    return key


def extract_json_block(text: str) -> Any:
    """从模型文本输出中稳健提取 JSON 对象。"""
    if not text:
        raise ValueError("模型返回内容为空")
    cleaned = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned, re.IGNORECASE)
    if m:
        candidate = m.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(cleaned[start : end + 1])
    raise ValueError(f"无法解析 JSON，原始内容前 300 字符: {cleaned[:300]}")


def extract_python_block(text: str) -> str:
    """从模型文本输出中提取 Python 代码块。"""
    if not text:
        raise ValueError("模型返回内容为空")
    m = re.search(r"```(?:python)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return text.strip()


def call_glm(
    messages: List[Dict[str, str]],
    model: str = "glm-5",
    temperature: float = 0.0,
    max_tokens: int = 4096,
    thinking: bool = True,
    timeout: int = 180,
    retries: int = 2,
) -> Dict[str, Any]:
    url = os.environ.get("GLM_BASE_URL", DEFAULT_BASE_URL)
    api_key = get_api_key()
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "thinking": {"type": "enabled" if thinking else "disabled"},
    }
    data_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        t0 = time.perf_counter()
        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                elapsed = time.perf_counter() - t0
                obj = json.loads(raw)
                msg = obj["choices"][0]["message"]
                return {
                    "model_returned": obj.get("model", model),
                    "content": msg.get("content", "") or "",
                    "reasoning_content": msg.get("reasoning_content", "") or "",
                    "usage": obj.get("usage", {}),
                    "elapsed_s": round(elapsed, 3),
                }
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, socket.timeout, KeyError, json.JSONDecodeError) as e:
            last_err = e
            if attempt < retries:
                wait_s = 3 * (attempt + 1)
                if isinstance(e, urllib.error.HTTPError) and e.code == 429:
                    wait_s = 6 * (attempt + 1)
                time.sleep(wait_s)
                continue
            if isinstance(e, urllib.error.HTTPError):
                err_body = e.read().decode("utf-8", errors="ignore")
                raise RuntimeError(f"GLM API HTTP {e.code}: {err_body[:500]}") from e
            raise RuntimeError(f"GLM API 调用失败: {e}") from e
    raise RuntimeError(f"GLM API 多次重试后失败: {last_err}")
