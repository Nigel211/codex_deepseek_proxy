@echo off
REM codex_deepseek_proxy - 启动脚本
REM 将 OpenAI Responses API 转换为 DeepSeek Chat Completions API
REM 让 Codex Desktop 可以通过 cc-switch 使用 DeepSeek

cd /d "D:\codex_deepseek_proxy"
echo Starting codex_deepseek_proxy ...
echo   Endpoint: http://127.0.0.1:5000
echo   Log:      proxy_debug.log
echo.
"C:\Users\Daniel Deng\AppData\Local\Python\bin\python.exe" codex_proxy.py
if errorlevel 1 (
    echo.
    echo 启动失败！请检查：
    echo   1. .env 文件中的 DEEPSEEK_API_KEY 是否正确
    echo   2. 端口 5000 是否被占用
    pause
)
