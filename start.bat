@echo off
chcp 65001 >nul
cd /d %~dp0
if not exist ".venv\" (
  echo [首次运行] 正在创建虚拟环境并安装依赖，约 1-2 分钟...
  python -m venv .venv
  call .venv\Scripts\activate.bat
  python -m pip install -r requirements.txt -q
) else (
  call .venv\Scripts\activate.bat
)
echo 正在启动 西浦课件通 XJTLU CourseMate ...
start "" http://127.0.0.1:8000
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
