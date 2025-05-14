#!/bin/bash

PROJECT_DIR="$HOME/ai_project"

echo "进入项目目录: $PROJECT_DIR"
cd "$PROJECT_DIR" || { echo "❌ 无法进入项目目录"; exit 1; }

echo "🔄 拉取 GitHub 最新代码..."
git reset --hard HEAD
git fetch origin
git reset --hard origin/main
echo "✅ Git 同步完成"

echo "🔁 重启 Gunicorn systemd 服务..."
sudo systemctl daemon-reexec
sudo systemctl daemon-reload
sudo systemctl restart gunicorn

echo "⏳ 等待 Gunicorn 启动 (3s)..."
sleep 3

if systemctl is-active --quiet gunicorn; then
    echo "✅ Gunicorn 已成功重启！"
else
    echo "❌ Gunicorn 启动失败，请运行 sudo journalctl -u gunicorn -e 查看日志"
fi
