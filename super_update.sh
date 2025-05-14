#!/bin/bash
# super_update.sh

PROJECT_DIR="$HOME/ai_project" 
VENV_ACTIVATE_PATH="${PROJECT_DIR}/venv/bin/activate"
GUNICORN_CAPTURE_LOG_FILE="${PROJECT_DIR}/gunicorn_stdout_stderr.log" # 更明确的文件名
GUNICORN_ERROR_LOG_FILE="${PROJECT_DIR}/gunicorn_error.log"   # Gunicorn error log (应包含Django日志)
GUNICORN_ACCESS_LOG_FILE="${PROJECT_DIR}/gunicorn_access.log" # Gunicorn access log

GUNICORN_APP="ai_site.wsgi:application"
GUNICORN_BIND_IP="127.0.0.1"
GUNICORN_BIND_PORT="8001"
GUNICORN_BIND_ADDRESS="${GUNICORN_BIND_IP}:${GUNICORN_BIND_PORT}"
GUNICORN_WORKER_CLASS="sync"
GUNICORN_WORKERS=3 
GUNICORN_TIMEOUT=180 
GUNICORN_LOG_LEVEL="debug" # 确保Gunicorn日志级别为debug

# --- Helper function to check port ---
is_port_in_use() {
    if lsof -t -i:"$1" > /dev/null; then
        return 0 # In use
    else
        return 1 # Not in use
    fi
}

echo "尝试进入项目目录: $PROJECT_DIR"
cd "$PROJECT_DIR" || { echo "❌ 错误：无法进入项目目录 $PROJECT_DIR"; exit 1; }
echo "当前目录: $(pwd)"

echo "🔄 正在从 GitHub 拉取最新代码..."
current_branch=$(git rev-parse --abbrev-ref HEAD)
if [ "$current_branch" != "main" ]; then
    echo "⚠️ 当前不在 main 分支，正在切换到 main 分支..."
    git checkout main || { echo "❌ 切换到 main 分支失败"; exit 1; }
fi
echo "重置本地更改 (git reset --hard HEAD)..."
git reset --hard HEAD
echo "获取远程更新 (git fetch origin)..."
git fetch origin
echo "强制本地 main 分支与 origin/main 同步 (git reset --hard origin/main)..."
git reset --hard origin/main 
if [ $? -ne 0 ]; then
    echo "❌ Git 同步失败! 请检查您的 Git 配置和网络连接。"
fi
echo "✅ 代码同步完成。"

echo "🛑 停止可能正在运行的 Gunicorn 服务..."
echo "提示：如果脚本无法自动停止服务，您可能需要手动操作，例如："
echo "  sudo systemctl stop your-gunicorn-service.service  (如果使用 systemd)"
echo "  sudo supervisorctl stop your-gunicorn-program   (如果使用 supervisor)"
echo "  或者使用 'ps aux | grep gunicorn' 和 'kill -9 <PID>' 手动查找并杀死主进程。"
# read -p "按 Enter 继续自动查杀尝试，或按 Ctrl+C 中止并手动停止服务..." # 可以取消注释这行以暂停

PIDS_LSOF=$(lsof -t -i:"$GUNICORN_BIND_PORT" || true)
if [ -n "$PIDS_LSOF" ]; then
    echo "发现占用端口 $GUNICORN_BIND_PORT 的进程: $PIDS_LSOF. 尝试 kill -9..."
    # shellcheck disable=SC2046 # We want word splitting for PIDS
    kill -9 $PIDS_LSOF || echo "kill -9 可能失败 (进程可能已不存在)"
    sleep 3
fi

PIDS_AFTER_KILL=$(lsof -t -i:"$GUNICORN_BIND_PORT" || true)
if [ -n "$PIDS_AFTER_KILL" ]; then
    echo "⚠️ kill -9 后端口仍被占用: $PIDS_AFTER_KILL. 尝试 pkill..."
    PGREP_PATTERN_APP="gunicorn.*${GUNICORN_APP}"
    PGREP_PATTERN_BIND="gunicorn.*${GUNICORN_BIND_ADDRESS}"
    pkill -9 -f "${PGREP_PATTERN_APP}" || echo "pkill (app) 未找到进程或失败"
    sleep 1
    pkill -9 -f "${PGREP_PATTERN_BIND}" || echo "pkill (bind) 未找到进程或失败"
    sleep 3
    
    PIDS_FINAL=$(lsof -t -i:"$GUNICORN_BIND_PORT" || true)
    if [ -n "$PIDS_FINAL" ]; then
        echo "❌ 错误：无法自动释放端口 $GUNICORN_BIND_PORT。当前占用进程: $PIDS_FINAL"
        echo "请务必手动停止所有相关的 Gunicorn 进程，然后重新运行此脚本的Gunicorn启动部分，或手动启动Gunicorn。"
        exit 1
    fi
fi
echo "✅ 端口 $GUNICORN_BIND_PORT 似乎已空闲或已被清理。"

echo "🚀 启动新的 Gunicorn 进程..."
if [ -f "$VENV_ACTIVATE_PATH" ]; then
    source "$VENV_ACTIVATE_PATH"
else
    echo "❌ 错误：虚拟环境激活脚本未找到: $VENV_ACTIVATE_PATH"
    exit 1
fi

GUNICORN_CMD_ARGS=" ${GUNICORN_APP} \
    --bind ${GUNICORN_BIND_ADDRESS} \
    --worker-class ${GUNICORN_WORKER_CLASS} \
    --timeout ${GUNICORN_TIMEOUT} \
    --workers ${GUNICORN_WORKERS} \
    --log-level ${GUNICORN_LOG_LEVEL} \
    --access-logfile \"${GUNICORN_ACCESS_LOG_FILE}\" \
    --error-logfile \"${GUNICORN_ERROR_LOG_FILE}\"" # Gunicorn自身的错误日志

echo "执行 Gunicorn 命令: nohup gunicorn $GUNICORN_CMD_ARGS > \"$GUNICORN_CAPTURE_LOG_FILE\" 2>&1 &"
nohup gunicorn $GUNICORN_CMD_ARGS > "$GUNICORN_CAPTURE_LOG_FILE" 2>&1 &

echo "⏳ 等待 Gunicorn 启动 (5秒)..."
sleep 5 

if lsof -Pi TCP:"${GUNICORN_BIND_PORT}" -sTCP:LISTEN -t > /dev/null ; then
    echo "✅ 部署完成！Gunicorn 应该已在后台运行！"
    echo "Gunicorn 监听在: http://${GUNICORN_BIND_ADDRESS}"
    echo "Gunicorn 访问日志: ${GUNICORN_ACCESS_LOG_FILE}"
    echo "Gunicorn 错误日志 (应包含Django应用日志): ${GUNICORN_ERROR_LOG_FILE}"
    echo "Gunicorn stdout/stderr 捕获日志: ${GUNICORN_CAPTURE_LOG_FILE}"
    echo "请使用 'tail -f ${GUNICORN_ERROR_LOG_FILE}' 和 'tail -f ${GUNICORN_CAPTURE_LOG_FILE}' 查看日志。"
else
    echo "❌ 错误：Gunicorn 似乎没有成功启动或监听端口 ${GUNICORN_BIND_PORT}。"
    echo "请检查日志文件: ${GUNICORN_ERROR_LOG_FILE} 和 ${GUNICORN_CAPTURE_LOG_FILE}"
fi
