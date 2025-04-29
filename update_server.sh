#!/bin/bash
set -e

echo "🔄 正在从 GitHub 拉取最新代码..."
git pull origin main

echo "🛑 关闭占用端口的进程..."
PORT=8001
PID=$(lsof -ti :$PORT)
if [ -n "$PID" ]; then
  kill -9 $PID
  echo "✅ 已关闭进程 $PID"
else
  echo "ℹ️ 无需关闭，端口空闲"
fi

echo "🚀 重启 Gunicorn 服务..."
gunicorn ai_site.wsgi:application --bind 127.0.0.1:8001 --worker-class gevent

echo "🎉 更新完成！服务器正常运行中..."
