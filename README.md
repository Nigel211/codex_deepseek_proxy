# codex_proxy

OpenAI Responses API ↔ DeepSeek Chat API 流式转发代理。让 Codex IDE / Codex CLI 通过 cc-switch 接入 DeepSeek 模型，支持完整的工具调用（Function Calling）。

## 功能

- 将 Codex 发出的 OpenAI Responses API 请求翻译为 DeepSeek Chat Completions API
- **完整支持 Function Calling**：工具定义透传、并行工具调用合并、tool 消息排序
- 将 DeepSeek 的 SSE 流式响应翻译回 Responses API 语义事件（含 function_call 事件）
- 自动修复消息顺序：Codex 注入的系统消息（如审批通知）会被重排，确保 tool 消息紧跟 assistant 消息
- 禁用思考模式：避免 DeepSeek v4-pro 的 `reasoning_content` 回传兼容问题
- 支持 cc-switch 模型选择（请求中的 model 字段优先）
- API Key 优先级：系统环境变量 > `.env` 文件 > 首次交互输入

## 环境要求

- Python >= 3.9
- DeepSeek API Key（[获取地址](https://platform.deepseek.com/api_keys)）

## 安装

```bash
git clone https://github.com/<your-username>/codex_proxy.git
cd codex_proxy
pip install -r requirements.txt
```

## 使用

```bash
python codex_proxy.py
```

首次运行如果没有配置 API Key，会在命令行引导你输入（输入时内容被遮蔽），自动保存到同目录 `.env` 文件。

启动后输出：

```
codex_proxy starting ...
   Endpoint: http://127.0.0.1:5000
   Model:    deepseek-v4-pro
   Key:      .env
   Debug:    OFF
   Routes:   /responses, /v1/responses, /v1/chat/completions
```

## 配置

所有配置通过环境变量或 `.env` 文件设置（环境变量优先级更高）。

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `DEEPSEEK_API_KEY` | **是** | - | DeepSeek API 密钥 |
| `DEEPSEEK_MODEL` | 否 | `deepseek-v4-pro` | 模型名称，cc-switch 中指定的模型会覆盖此值 |
| `DEEPSEEK_URL` | 否 | `https://api.deepseek.com/v1/chat/completions` | DeepSeek API 地址 |
| `DEEPSEEK_DEBUG` | 否 | `0` | 设为 `1` 开启请求日志，输出到 `proxy_debug.log` |

### API Key 设置方式（按优先级）

1. **系统环境变量**（推荐）：`export DEEPSEEK_API_KEY=sk-xxx`
2. **`.env` 文件**：在脚本同目录创建 `.env`，写入 `DEEPSEEK_API_KEY=sk-xxx`
3. **交互输入**：首次启动时提示输入，自动保存到 `.env`

## cc-switch 配置

在 cc-switch 中将模型路由地址设为：

```
http://127.0.0.1:5000
```

代理注册了三个路由，cc-switch 会自动适配：

- `/responses`
- `/v1/responses`
- `/v1/chat/completions`

## 架构

```
Codex IDE/CLI          cc-switch            codex_proxy           DeepSeek API
─────────────          ─────────            ────────────          ────────────
Responses API ────→  路由转发  ────→  格式转换 (Responses→Chat)  ────→  /v1/chat/completions
SSE Stream    ←────   透传     ←────  格式转换 (Chat→Responses)   ←────  SSE Stream
```

本代理完整实现了 OpenAI Responses API 的 SSE 语义事件流，支持文本和函数调用两种输出：

**纯文本响应：**
```
response.created → response.in_progress → response.output_item.added
→ response.content_part.added → response.output_text.delta (×N)
→ response.output_text.done → response.content_part.done
→ response.output_item.done → response.completed
```

**函数调用响应：**
```
response.created → response.in_progress
→ response.output_item.added (type: function_call)
→ response.function_call_arguments.delta (×N)
→ response.function_call_arguments.done
→ response.output_item.done → response.completed
```

## 工具调用兼容性

代理处理了 DeepSeek Chat Completions API 与 OpenAI Responses API 之间的以下差异：

| 问题 | 处理方式 |
|------|----------|
| 工具定义格式不同 | 将 Responses API 扁平格式转为 Chat API 嵌套 `function` 格式，清除 `strict` 和 `additionalProperties` 字段 |
| 并行工具调用 | 将 Codex 的多个连续 `function_call` 项合并为单个 assistant 消息（含多个 `tool_calls`） |
| 消息顺序 | DeepSeek 要求 tool 消息紧跟对应的 assistant 消息；代理自动将 Codex 插入的 system 消息移到 assistant 之前 |
| 思考模式 | 默认禁用（`thinking: {type: "disabled"}`），避免 `reasoning_content` 无法通过 Responses API 回传 |

## 常见问题

**Q: 启动后 Codex 无响应？**

检查 `DEEPSEEK_API_KEY` 是否正确设置。开启 `DEEPSEEK_DEBUG=1` 后查看 `proxy_debug.log`。

**Q: 如何更换模型？**

在 cc-switch 中更改模型名，代理会自动透传。或设置 `DEEPSEEK_MODEL=deepseek-chat` 作为默认。

**Q: 工具调用报 400 错误？**

检查 `proxy_debug.log` 中的错误详情。常见原因：DeepSeek 账户余额不足、模型不支持工具调用、或请求体过大。

**Q: 是否需要安装 Python？**

是，需要 Python 3.9 及以上。依赖安装后启动代理即可。

## License

MIT
