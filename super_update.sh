#!/bin/bash
# super_update.sh

# 进入项目目录
cd ~/ai_project || exit

echo "🔄 正在从 GitHub 拉取最新代码..."
git reset --hard HEAD
git pull origin main

# 杀掉占用 8001 端口的进程
echo "🛑 查找并关闭占用端口 8001 的进程..."
PIDS=$(lsof -t -i:8001)
if [ -n "$PIDS" ]; then
    echo "Killing PIDS: $PIDS" # Added for more verbose logging
    kill -9 "$PIDS" # Ensure PIDS is quoted if it can contain multiple space-separated pids
    echo "✅ 已关闭进程: $PIDS"
else
    echo "✅ 没有占用端口 8001 的进程"
fi

# 启动 gunicorn 后台运行
echo "🚀 启动新的 Gunicorn 进程..."
source ~/ai_project/venv/bin/activate
# 明确设置 --timeout (例如 180 秒) 和 --workers (例如 3)
nohup gunicorn ai_site.wsgi:application \
    --bind 127.0.0.1:8001 \
    --workers 3 \
    --timeout 180 \
    --worker-class sync > gunicorn.log 2>&1 &

echo "✅ 部署完成！Gunicorn 后台运行中！日志在 gunicorn.log"
echo "Gunicorn command used: nohup gunicorn ai_site.wsgi:application --bind 127.0.0.1:8001 --workers 3 --timeout 180 --worker-class sync > gunicorn.log 2>&1 &"
