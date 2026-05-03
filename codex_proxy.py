# codex_proxy.py — OpenAI Responses API ↔ DeepSeek Chat API 流式转发
import sys
import os
import json
import uuid
import getpass

from flask import Flask, request, Response
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def _load_dotenv():
    """加载 .env 文件到 os.environ（不覆盖已有的系统环境变量）"""
    env_file = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(env_file):
        return
    # 记录加载前系统环境变量中是否已有 KEY
    had_key = "DEEPSEEK_API_KEY" in os.environ
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip("\"'")
            if key and key not in os.environ:
                os.environ[key] = val
    # 标记 KEY 来源：系统 env 已在加载前存在 → "sys"，否则 ".env"
    if "DEEPSEEK_API_KEY" in os.environ:
        os.environ["_DEEPSEEK_KEY_SOURCE"] = "sys" if had_key else "dotenv"

def _ensure_api_key():
    """确保 DEEPSEEK_API_KEY 已设置：系统环境变量 > .env > 交互输入"""
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if key:
        src = os.environ.get("_DEEPSEEK_KEY_SOURCE", "")
        if src == "sys":
            return key, "系统环境变量"
        return key, ".env"

    print("=" * 60)
    print("  未检测到 DEEPSEEK_API_KEY")
    print("=" * 60)
    print()
    print("  从 https://platform.deepseek.com/api_keys 获取 API Key")
    print()
    print("  你也可以设置系统环境变量 DEEPSEEK_API_KEY 后重启")
    print()

    try:
        key = getpass.getpass("  请输入你的 DeepSeek API Key: ").strip()
    except (EOFError, KeyboardInterrupt):
        key = ""

    if not key:
        print()
        print("  ERROR: 未输入 API Key，程序退出。")
        print()
        print("  支持以下方式设置 API Key（按优先级排列）:")
        print("    1. 系统环境变量: DEEPSEEK_API_KEY=sk-your-key")
        print("    2. 脚本同目录 .env 文件: DEEPSEEK_API_KEY=sk-your-key")
        print()
        input("  按 Enter 退出...")
        sys.exit(1)

    # 保存到 .env
    env_file = os.path.join(BASE_DIR, ".env")
    existing = {}
    if os.path.exists(env_file):
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                existing[k.strip()] = line
    existing["DEEPSEEK_API_KEY"] = f"DEEPSEEK_API_KEY={key}"

    with open(env_file, "w", encoding="utf-8") as f:
        for line in existing.values():
            f.write(line + "\n")
        if "DEEPSEEK_MODEL" not in existing:
            f.write("DEEPSEEK_MODEL=deepseek-v4-pro\n")

    os.environ["DEEPSEEK_API_KEY"] = key
    print()
    print(f"  API Key 已保存到: {env_file}")
    print()
    return key, ".env (已保存)"

_load_dotenv()

DEBUG_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "proxy_debug.log")

app = Flask(__name__)

# ===================== 配置 =====================
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro").strip()
DEEPSEEK_URL = os.environ.get("DEEPSEEK_URL", "https://api.deepseek.com/v1/chat/completions").strip()
DEEPSEEK_DEBUG = os.environ.get("DEEPSEEK_DEBUG", "0").strip() in ("1", "true", "True", "yes")
# =================================================


def extract_messages(data: dict) -> list:
    """从 Responses API 请求中提取 messages 列表"""
    # DeepSeek 不支持 "developer" 角色，映射为 "system"
    ROLE_MAP = {"developer": "system"}

    if "input" in data:
        inp = data["input"]
        if isinstance(inp, str):
            return [{"role": "user", "content": inp}]
        if isinstance(inp, list):
            messages = []

            # 先加入 instructions（system prompt）
            if "instructions" in data and data["instructions"]:
                messages.append({"role": "system", "content": data["instructions"]})

            for item in inp:
                if not isinstance(item, dict):
                    continue
                # Responses API 的 input 项有 type: "message"
                if item.get("type", "message") != "message":
                    continue

                role = item.get("role", "user")
                role = ROLE_MAP.get(role, role)  # developer → system
                content = item.get("content", "")
                if isinstance(content, list):
                    # Content 可能是 "input_text" 或 "output_text" 或 "text"
                    texts = [
                        c.get("text", "")
                        for c in content
                        if isinstance(c, dict)
                        and c.get("type") in ("text", "input_text", "output_text")
                        and c.get("text", "").strip()
                    ]
                    content = "\n".join(texts)
                if isinstance(content, str):
                    content = content.strip()
                if not content:
                    continue  # 跳过空消息
                messages.append({"role": role, "content": content})
            return messages
    if "instructions" in data:
        return [{"role": "system", "content": data["instructions"]}]
    if "messages" in data:
        return data["messages"]
    return []


# ---- CORS ----
@app.after_request
def add_cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    return resp


# ---- 路由处理 ----
def _make_response():
    """处理 /responses 系列请求的核心逻辑"""
    if request.method == "OPTIONS":
        return Response()

    req_data = request.get_json(silent=True) or {}
    messages = extract_messages(req_data)
    # cc-switch 传来的 model 优先，否则用默认配置
    effective_model = req_data.get("model") or DEEPSEEK_MODEL
    response_id = f"resp_{uuid.uuid4().hex[:12]}"
    item_id = f"item_{uuid.uuid4().hex[:12]}"

    if DEEPSEEK_DEBUG:
        debug_path = request.path
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(f"\n--- [{__import__('datetime').datetime.now()}] PATH={debug_path} ---\n")
            f.write(f"Request body:\n{json.dumps(req_data, indent=2, ensure_ascii=False)}\n")
            f.write(f"Messages:\n{json.dumps(messages, indent=2, ensure_ascii=False)}\n")

    def generate():
        # 健康检查
        if not messages:
            yield "event: response.completed\n"
            yield (
                "data: "
                + json.dumps({
                    "type": "response.completed",
                    "response": {
                        "id": response_id, "object": "response",
                        "status": "completed", "model": effective_model,
                        "output": [], "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                    },
                }, ensure_ascii=False)
                + "\n\n"
            )
            return

        # response.created
        yield "event: response.created\n"
        yield (
            "data: "
            + json.dumps({
                "type": "response.created",
                "response": {
                    "id": response_id, "object": "response",
                    "status": "in_progress", "model": effective_model,
                    "output": [], "usage": None,
                },
            }, ensure_ascii=False)
            + "\n\n"
        )

        # response.in_progress
        yield "event: response.in_progress\n"
        yield (
            "data: "
            + json.dumps({
                "type": "response.in_progress",
                "response": {
                    "id": response_id, "object": "response",
                    "status": "in_progress", "model": effective_model,
                    "output": [], "usage": None,
                },
            }, ensure_ascii=False)
            + "\n\n"
        )

        # response.output_item.added
        yield "event: response.output_item.added\n"
        yield (
            "data: "
            + json.dumps({
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {
                    "id": item_id, "type": "message",
                    "status": "in_progress", "role": "assistant",
                    "content": [],
                },
            }, ensure_ascii=False)
            + "\n\n"
        )

        # response.content_part.added
        yield "event: response.content_part.added\n"
        yield (
            "data: "
            + json.dumps({
                "type": "response.content_part.added",
                "item_id": item_id,
                "output_index": 0,
                "content_index": 0,
                "part": {"type": "text", "text": ""},
            }, ensure_ascii=False)
            + "\n\n"
        )

        # 调用 DeepSeek
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": effective_model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        full_text = ""
        input_tokens = 0
        output_tokens = 0
        seq = 0
        try:
            with requests.post(
                DEEPSEEK_URL, headers=headers, json=payload,
                stream=True, timeout=120,
            ) as upstream:
                upstream.raise_for_status()
                for line in upstream.iter_lines():
                    if not line:
                        continue
                    line = line.decode("utf-8")
                    if not line.startswith("data: "):
                        continue
                    raw = line[6:].strip()
                    if raw == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    # 捕获 token 用量（stream_options.include_usage）
                    usage = chunk.get("usage")
                    if usage:
                        input_tokens = usage.get("prompt_tokens", 0)
                        output_tokens = usage.get("completion_tokens", 0)

                    if "error" in chunk:
                        err = chunk["error"]
                        raise Exception(f"DeepSeek API error: {err.get('message', str(err))}")

                    if "choices" not in chunk or not chunk["choices"]:
                        continue
                    delta = chunk["choices"][0].get("delta", {}).get("content", "")
                    if not delta:
                        continue
                    full_text += delta
                    seq += 1

                    yield "event: response.output_text.delta\n"
                    yield (
                        "data: "
                        + json.dumps({
                            "type": "response.output_text.delta",
                            "delta": delta,
                            "item_id": item_id,
                            "output_index": 0,
                            "content_index": 0,
                            "sequence_number": seq,
                        }, ensure_ascii=False)
                        + "\n\n"
                    )

            # response.output_text.done
            yield "event: response.output_text.done\n"
            yield (
                "data: "
                + json.dumps({
                    "type": "response.output_text.done",
                    "text": full_text, "item_id": item_id,
                    "output_index": 0, "content_index": 0,
                }, ensure_ascii=False)
                + "\n\n"
            )

            # response.content_part.done
            yield "event: response.content_part.done\n"
            yield (
                "data: "
                + json.dumps({
                    "type": "response.content_part.done",
                    "item_id": item_id,
                    "output_index": 0,
                    "content_index": 0,
                    "part": {"type": "text", "text": full_text},
                }, ensure_ascii=False)
                + "\n\n"
            )

            # response.output_item.done
            yield "event: response.output_item.done\n"
            yield (
                "data: "
                + json.dumps({
                    "type": "response.output_item.done",
                    "output_index": 0,
                    "item": {
                        "id": item_id, "type": "message",
                        "status": "completed", "role": "assistant",
                        "content": [{"type": "text", "text": full_text}],
                    },
                }, ensure_ascii=False)
                + "\n\n"
            )

            # response.completed
            yield "event: response.completed\n"
            yield (
                "data: "
                + json.dumps({
                    "type": "response.completed",
                    "response": {
                        "id": response_id, "object": "response",
                        "status": "completed", "model": effective_model,
                        "output": [{
                            "id": item_id, "type": "message",
                            "status": "completed", "role": "assistant",
                            "content": [{"type": "text", "text": full_text}],
                        }],
                        "usage": {
                            "input_tokens": input_tokens or max(1, len(json.dumps(messages)) // 4),
                            "output_tokens": output_tokens or max(1, len(full_text) // 4),
                            "total_tokens": (input_tokens + output_tokens) or max(1, len(json.dumps(messages)) // 4 + len(full_text) // 4),
                        },
                    },
                }, ensure_ascii=False)
                + "\n\n"
            )

        except requests.exceptions.HTTPError as e:
            body = e.response.text[:500] if e.response is not None else "(no body)"
            err_msg = f"DeepSeek API {e.response.status_code}: {body}"
            if DEEPSEEK_DEBUG:
                with open(DEBUG_LOG, "a", encoding="utf-8") as f:
                    f.write(f"ERROR: {err_msg}\n")
            yield "event: response.failed\n"
            yield "data: " + json.dumps({
                "type": "response.failed",
                "response": {
                    "id": response_id, "object": "response",
                    "status": "failed", "model": effective_model,
                    "error": {"message": err_msg, "type": "upstream_error"},
                    "output": [], "usage": None,
                },
            }, ensure_ascii=False) + "\n\n"

        except requests.exceptions.RequestException as e:
            yield "event: response.failed\n"
            yield "data: " + json.dumps({
                "type": "response.failed",
                "response": {
                    "id": response_id, "object": "response",
                    "status": "failed", "model": effective_model,
                    "error": {"message": str(e), "type": "upstream_error"},
                    "output": [], "usage": None,
                },
            }, ensure_ascii=False) + "\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---- 注册路由 ----
app.add_url_rule("/responses", "responses", _make_response, methods=["POST", "OPTIONS"])
app.add_url_rule("/v1/responses", "v1_responses", _make_response, methods=["POST", "OPTIONS"])
app.add_url_rule("/v1/chat/completions", "v1_chat", _make_response, methods=["POST", "OPTIONS"])


if __name__ == "__main__":
    key, source = _ensure_api_key()
    if not key:
        sys.exit(1)
    globals()["DEEPSEEK_API_KEY"] = key

    from waitress import serve
    print("codex_proxy starting ...")
    print(f"   Endpoint: http://127.0.0.1:5000")
    print(f"   Model:    {DEEPSEEK_MODEL}")
    print(f"   Key:      {source}")
    print(f"   Debug:    {'ON' if DEEPSEEK_DEBUG else 'OFF'}")
    print(f"   Routes:   /responses, /v1/responses, /v1/chat/completions")
    serve(app, host="127.0.0.1", port=5000, threads=4)
