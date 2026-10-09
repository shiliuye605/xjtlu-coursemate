@echo off
chcp 65001 >nul
cd /d %~dp0
echo 启动离线演示模式（无需 API Key）...
start "MockLLM (演示模型)" cmd /c "python tests\mock_llm.py"
timeout /t 2 >nul
call start.bat
