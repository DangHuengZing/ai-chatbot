#!/bin/bash
# super_update.sh

# 使用 $HOME 来确保路径正确解析，或者直接使用绝对路径
PROJECT_DIR="$HOME/ai_project" 
# 如果您的项目不在 /root/ai_project，请相应修改上面的路径
# 例如，如果脚本本身就在项目根目录，并且总是从那里运行，也可以用 PROJECT_DIR=$(pwd)
# 但为了通用性，使用 $HOME/ai_project 或绝对路径更好

VENV_ACTIVATE_PATH="${PROJECT_DIR}/venv/bin/activate"
GUNICORN_LOG_FILE="${PROJECT_DIR}/gunicorn.log"
GUNICORN_APP="ai_site.wsgi:application"
GUNICORN_BIND="127.0.0.1:8001"
GUNICORN_WORKER_CLASS="sync"
GUNICORN_WORKERS=3 # 根据您的服务器配置调整
GUNICORN_TIMEOUT=180 # 3分钟，根据需要调整

# 进入项目目录
echo "尝试进入项目目录: $PROJECT_DIR"
cd "$PROJECT_DIR" || { echo "错误：无法进入项目目录 $PROJECT_DIR"; exit 1; }
echo "当前目录: $(pwd)"

echo "🔄 正在从 GitHub 拉取最新代码..."
git reset --hard HEAD
git pull origin main
if [ $? -ne 0 ]; then
    echo "❌ Git pull 失败!"
    # exit 1 
fi

# --- 增强的进程查杀逻辑 ---
echo "🛑 查找并关闭占用端口 ${GUNICORN_BIND##*:} 的进程..."
MAX_KILL_ATTEMPTS=3 
ATTEMPT_COUNT=0
PORT_FREED=false

while [ $ATTEMPT_COUNT -lt $MAX_KILL_ATTEMPTS ]; do
    PIDS=$(lsof -t -i:"${GUNICORN_BIND##*:}") 
    if [ -n "$PIDS" ]; then
        echo "发现占用端口的进程: $PIDS。尝试关闭 (尝试次数: $((ATTEMPT_COUNT+1))/$MAX_KILL_ATTEMPTS)..."
        # shellcheck disable=SC2046 
        if kill -9 $PIDS > /dev/null 2>&1; then
            echo "✅ 已发送 kill -9 命令给进程: $PIDS"
        else
            echo "⚠️ 发送 kill -9 命令给 $PIDS 失败 (可能进程已不存在或权限问题)"
        fi
        sleep 3 
    else
        echo "✅ 端口 ${GUNICORN_BIND##*:} 当前没有被占用。"
        PORT_FREED=true
        break 
    fi
    ATTEMPT_COUNT=$((ATTEMPT_COUNT+1))
done

if ! $PORT_FREED; then
    echo "⚠️ 通过端口查杀后，端口 ${GUNICORN_BIND##*:} 仍然可能被占用。尝试使用 pkill 强制关闭相关 Gunicorn 进程..."
    PGREP_PATTERN="gunicorn.*${GUNICORN_APP}.*${GUNICORN_BIND}"
    echo "使用 pkill -9 -f \"${PGREP_PATTERN}\" 尝试关闭..."
    if pkill -9 -f "${PGREP_PATTERN}"; then
        echo "✅ 已通过 pkill 发送 SIGKILL 信号给匹配的 Gunicorn 进程。"
        sleep 5 
    else
        echo "ℹ️ pkill 未找到匹配 '${PGREP_PATTERN}' 的进程，或者发送信号失败。"
    fi

    PIDS_AFTER_PKILL=$(lsof -t -i:"${GUNICORN_BIND##*:}")
    if [ -n "$PIDS_AFTER_PKILL" ]; then
        echo "❌ 错误：在使用 pkill 后，端口 ${GUNICORN_BIND##*:} 仍然被进程 $PIDS_AFTER_PKILL 占用。"
        echo "请手动检查并关闭这些进程: ps aux | grep gunicorn ; lsof -i:${GUNICORN_BIND##*:}"
        exit 1
    else
        echo "✅ 通过 pkill 后，端口 ${GUNICORN_BIND##*:} 已释放。"
    fi
fi
# --- 进程查杀逻辑结束 ---

# 激活虚拟环境并启动 Gunicorn
echo "🚀 启动新的 Gunicorn 进程..."
if [ -f "$VENV_ACTIVATE_PATH" ]; then
    # shellcheck source=/dev/null
    source "$VENV_ACTIVATE_PATH"
else
    echo "❌ 错误：虚拟环境激活脚本未找到: $VENV_ACTIVATE_PATH"
    exit 1
fi

GUNICORN_CMD="gunicorn ${GUNICORN_APP} --bind ${GUNICORN_BIND} --worker-class ${GUNICORN_WORKER_CLASS} --timeout ${GUNICORN_TIMEOUT} --workers ${GUNICORN_WORKERS}"

echo "执行 Gunicorn 命令: $GUNICORN_CMD"
nohup $GUNICORN_CMD > "$GUNICORN_LOG_FILE" 2>&1 &

echo "⏳ 等待 Gunicorn 启动 (5秒)..."
sleep 5 

if lsof -Pi TCP:"${GUNICORN_BIND##*:}" -sTCP:LISTEN -t > /dev/null ; then
    echo "✅ 部署完成！Gunicorn 应该已在后台运行！日志在 $GUNICORN_LOG_FILE"
    echo "Gunicorn 监听在: http://${GUNICORN_BIND}"
else
    echo "❌ 错误：Gunicorn 似乎没有成功启动或监听端口 ${GUNICORN_BIND##*:}。"
    echo "请检查日志文件: $GUNICORN_LOG_FILE"
fi
