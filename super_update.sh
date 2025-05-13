#!/bin/bash
# super_update.sh

# 进入项目目录
cd ~/ai_project || { echo "错误：无法进入项目目录 ~/ai_project"; exit 1; }

echo "🔄 正在从 GitHub 拉取最新代码..."
git reset --hard HEAD
git pull origin main
if [ $? -ne 0 ]; then
    echo "❌ Git pull 失败!"
    # exit 1 # 可以选择在这里退出，或者继续尝试重启服务
fi

# 查找并关闭占用端口 8001 的进程
MAX_KILL_ATTEMPTS=5
ATTEMPT_COUNT=0
echo "🛑 查找并关闭占用端口 8001 的进程..."
while [ $ATTEMPT_COUNT -lt $MAX_KILL_ATTEMPTS ]; do
    PIDS=$(lsof -t -i:8001)
    if [ -n "$PIDS" ]; then
        echo "发现占用端口 8001 的进程: $PIDS。尝试关闭 (尝试次数: $((ATTEMPT_COUNT+1))/$MAX_KILL_ATTEMPTS)..."
        # 使用 xargs 来处理可能存在的多个 PID
        # shellcheck disable=SC2046 # PIDS is intentionally split here
        if kill -9 $PIDS > /dev/null 2>&1; then
            echo "✅ 已发送 kill -9 命令给进程: $PIDS"
        else
            echo "⚠️ 发送 kill -9 命令失败 (可能进程已不存在或权限问题)"
        fi
        sleep 2 # 等待进程关闭
    else
        echo "✅ 端口 8001 当前没有被占用。"
        break # 退出循环
    fi
    ATTEMPT_COUNT=$((ATTEMPT_COUNT+1))
done

# 再次检查端口是否已释放
PIDS_AFTER_KILL=$(lsof -t -i:8001)
if [ -n "$PIDS_AFTER_KILL" ]; then
    echo "❌ 错误：无法关闭占用端口 8001 的进程: $PIDS_AFTER_KILL。请手动检查并关闭这些进程。"
    exit 1
fi

# 激活虚拟环境并启动 Gunicorn
echo "🚀 启动新的 Gunicorn 进程..."
if [ -f ~/ai_project/venv/bin/activate ]; then
    # shellcheck source=/dev/null
    source ~/ai_project/venv/bin/activate
else
    echo "❌ 错误：虚拟环境激活脚本未找到: ~/ai_project/venv/bin/activate"
    exit 1
fi

# 确保您已在 Gunicorn 命令中加入了 --timeout 参数
# 例如 --timeout 180 (3分钟)
GUNICORN_CMD="gunicorn ai_site.wsgi:application --bind 127.0.0.1:8001 --worker-class sync --timeout 180 --workers 3" # 假设您需要3个worker

echo "执行 Gunicorn 命令: $GUNICORN_CMD"
nohup $GUNICORN_CMD > gunicorn.log 2>&1 &

# 等待几秒钟让 Gunicorn 启动
sleep 5 

# 检查 Gunicorn 是否成功启动并监听端口
if lsof -t -i:8001 > /dev/null; then
    echo "✅ 部署完成！Gunicorn 应该已在后台运行！日志在 gunicorn.log"
else
    echo "❌ 错误：Gunicorn 似乎没有成功启动或监听端口 8001。请检查 gunicorn.log。"
fi
