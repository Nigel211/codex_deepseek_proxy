# codex_proxy

OpenAI Responses API ↔ DeepSeek Chat API 流式转发代理。让 Codex IDE / Codex CLI 通过 cc-switch 接入 DeepSeek 模型。

## 功能

- 将 Codex 发出的 OpenAI Responses API 请求翻译为 DeepSeek Chat Completions API
- 将 DeepSeek 的 SSE 流式响应翻译回 Responses API 语义事件
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

本代理完整实现了 OpenAI Responses API 的 SSE 语义事件流：

```
response.created → response.in_progress → response.output_item.added
→ response.content_part.added → response.output_text.delta (×N)
→ response.output_text.done → response.content_part.done
→ response.output_item.done → response.completed
```

## 常见问题

**Q: 启动后 Codex 无响应？**

检查 `DEEPSEEK_API_KEY` 是否正确设置。开启 `DEEPSEEK_DEBUG=1` 后查看 `proxy_debug.log`。

**Q: 如何更换模型？**

在 cc-switch 中更改模型名，代理会自动透传。或设置 `DEEPSEEK_MODEL=deepseek-chat` 作为默认。

**Q: 是否需要安装 Python？**

是，需要 Python 3.9 及以上。依赖安装后启动代理即可。

## License

MIT
