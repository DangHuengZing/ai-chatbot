#!/bin/bash

echo "🔄 正在从GitHub拉取最新代码..."
git pull origin main

echo "🛑 杀死占用8001端口的进程..."
lsof -i:8001 | awk 'NR>1 {print $2}' | xargs kill -9

echo "🚀 重新启动Gunicorn服务器..."
gunicorn ai_site.wsgi:application --bind 127.0.0.1:8001 --worker-class gevent

echo "✅ 更新完成！服务器已重启！"
