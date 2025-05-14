#!/bin/bash
# super_update.sh

PROJECT_DIR="$HOME/ai_project" 
VENV_ACTIVATE_PATH="${PROJECT_DIR}/venv/bin/activate"
GUNICORN_CAPTURE_LOG_FILE="${PROJECT_DIR}/gunicorn_capture.log" # Gunicorn stdout/stderr
GUNICORN_ERROR_LOG_FILE="${PROJECT_DIR}/gunicorn_error.log"   # Gunicorn error log
GUNICORN_ACCESS_LOG_FILE="${PROJECT_DIR}/gunicorn_access.log" # Gunicorn access log

GUNICORN_APP="ai_site.wsgi:application"
GUNICORN_BIND_IP="127.0.0.1"
GUNICORN_BIND_PORT="8001"
GUNICORN_BIND_ADDRESS="${GUNICORN_BIND_IP}:${GUNICORN_BIND_PORT}"
GUNICORN_WORKER_CLASS="sync"
GUNICORN_WORKERS=3 
GUNICORN_TIMEOUT=180 
GUNICORN_LOG_LEVEL="debug" # 设置Gunicorn日志级别为debug

# 进入项目目录
echo "尝试进入项目目录: $PROJECT_DIR"
cd "$PROJECT_DIR" || { echo "错误：无法进入项目目录 $PROJECT_DIR"; exit 1; }
echo "当前目录: $(pwd)"

echo "🔄 正在从 GitHub 拉取最新代码..."
git reset --hard HEAD
git pull origin main --no-rebase 
if [ $? -ne 0 ]; then
    echo "❌ Git pull 失败!"
fi

# --- 增强的进程查杀逻辑 ---
echo "🛑 查找并关闭占用端口 ${GUNICORN_BIND_PORT} 的进程..."
MAX_KILL_ATTEMPTS=3 
ATTEMPT_COUNT=0
PORT_FREED=false

# Helper function to check port
is_port_in_use() {
    if lsof -t -i:"$1" > /dev/null; then
        return 0 # In use
    else
        return 1 # Not in use
    fi
}
# Helper function to kill PIDs
kill_pids() {
    local pids_to_kill="$1"
    if [ -n "$pids_to_kill" ]; then
        echo "尝试发送 SIGKILL 给 PIDs: $pids_to_kill"
        # shellcheck disable=SC2086
        if kill -9 $pids_to_kill > /dev/null 2>&1; then
            echo "✅ SIGKILL 已发送。"
        else
            echo "⚠️ SIGKILL 发送失败 (可能进程已不存在或权限问题)。"
        fi
        sleep 2 
    fi
}

while [ $ATTEMPT_COUNT -lt $MAX_KILL_ATTEMPTS ]; do
    PIDS=$(lsof -t -i:"$GUNICORN_BIND_PORT") 
    if [ -n "$PIDS" ]; then
        echo "发现占用端口的进程: $PIDS。尝试关闭 (尝试次数: $((ATTEMPT_COUNT+1))/$MAX_KILL_ATTEMPTS)..."
        kill_pids "$PIDS"
    else
        echo "✅ 端口 ${GUNICORN_BIND_PORT} 当前没有被占用。"
        PORT_FREED=true
        break 
    fi
    ATTEMPT_COUNT=$((ATTEMPT_COUNT+1))
done

if ! $PORT_FREED; then
    echo "⚠️ 通过端口查杀后，端口 ${GUNICORN_BIND_PORT} 仍然可能被占用。尝试使用 pkill 强制关闭相关 Gunicorn 进程..."
    PGREP_PATTERN_APP="gunicorn.*${GUNICORN_APP}"
    PGREP_PATTERN_BIND="gunicorn.*${GUNICORN_BIND_ADDRESS}"
    
    echo "尝试 pkill -9 -f \"${PGREP_PATTERN_APP}\""
    pkill -9 -f "${PGREP_PATTERN_APP}"
    sleep 1
    echo "尝试 pkill -9 -f \"${PGREP_PATTERN_BIND}\""
    pkill -9 -f "${PGREP_PATTERN_BIND}"
    sleep 3 

    if is_port_in_use "$GUNICORN_BIND_PORT"; then
        PIDS_FINAL_CHECK=$(lsof -t -i:"$GUNICORN_BIND_PORT")
        echo "❌ 错误：所有尝试均失败后，端口 $GUNICORN_BIND_PORT 仍然被进程 $PIDS_FINAL_CHECK 占用。"
        echo "请手动诊断:"
        echo "  ps aux | grep gunicorn | grep '${GUNICORN_APP}'"
        echo "  lsof -i:${GUNICORN_BIND_PORT}"
        echo "  sudo netstat -tulnp | grep ':${GUNICORN_BIND_PORT}'"
        exit 1
    else
        echo "✅ 通过 pkill 后，端口 ${GUNICORN_BIND_PORT} 已成功释放。"
    fi
fi
# --- 进程查杀逻辑结束 ---

echo "🚀 启动新的 Gunicorn 进程..."
if [ -f "$VENV_ACTIVATE_PATH" ]; then
    source "$VENV_ACTIVATE_PATH"
else
    echo "❌ 错误：虚拟环境激活脚本未找到: $VENV_ACTIVATE_PATH"
    exit 1
fi

GUNICORN_CMD="gunicorn ${GUNICORN_APP} \
    --bind ${GUNICORN_BIND_ADDRESS} \
    --worker-class ${GUNICORN_WORKER_CLASS} \
    --timeout ${GUNICORN_TIMEOUT} \
    --workers ${GUNICORN_WORKERS} \
    --log-level ${GUNICORN_LOG_LEVEL} \
    --access-logfile ${GUNICORN_ACCESS_LOG_FILE} \
    --error-logfile ${GUNICORN_ERROR_LOG_FILE}" # Gunicorn自身的错误日志

echo "执行 Gunicorn 命令: $GUNICORN_CMD"
# Django的logger输出 (INFO, DEBUG等) 默认到stderr, Gunicorn会将stderr重定向到 --error-logfile
# 如果想把所有stdout/stderr（包括Django的print）也捕获，可以保留 > "$GUNICORN_CAPTURE_LOG_FILE" 2>&1
nohup $GUNICORN_CMD > "$GUNICORN_CAPTURE_LOG_FILE" 2>&1 &

echo "⏳ 等待 Gunicorn 启动 (5秒)..."
sleep 5 

if lsof -Pi TCP:"${GUNICORN_BIND_PORT}" -sTCP:LISTEN -t > /dev/null ; then
    echo "✅ 部署完成！Gunicorn 应该已在后台运行！"
    echo "Gunicorn 监听在: http://${GUNICORN_BIND_ADDRESS}"
    echo "Gunicorn 访问日志: ${GUNICORN_ACCESS_LOG_FILE}"
    echo "Gunicorn 错误日志 (包含Django日志): ${GUNICORN_ERROR_LOG_FILE}"
    echo "Gunicorn stdout/stderr 捕获日志: ${GUNICORN_CAPTURE_LOG_FILE}"
else
    echo "❌ 错误：Gunicorn 似乎没有成功启动或监听端口 ${GUNICORN_BIND_PORT}。"
    echo "请检查日志文件: ${GUNICORN_ERROR_LOG_FILE} 和 ${GUNICORN_CAPTURE_LOG_FILE}"
fi
