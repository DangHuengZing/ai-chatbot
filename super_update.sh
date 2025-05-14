#!/bin/bash
# super_update.sh

PROJECT_DIR="$HOME/ai_project"
VENV_ACTIVATE_PATH="${PROJECT_DIR}/venv/bin/activate"
GUNICORN_CAPTURE_LOG_FILE="${PROJECT_DIR}/gunicorn_stdout_stderr.log"
GUNICORN_ERROR_LOG_FILE="${PROJECT_DIR}/gunicorn_error.log"
GUNICORN_ACCESS_LOG_FILE="${PROJECT_DIR}/gunicorn_access.log"

GUNICORN_APP="ai_site.wsgi:application"
GUNICORN_BIND_IP="127.0.0.1"
GUNICORN_BIND_PORT="8001"
GUNICORN_BIND_ADDRESS="${GUNICORN_BIND_IP}:${GUNICORN_BIND_PORT}"
GUNICORN_WORKER_CLASS="sync"
GUNICORN_WORKERS=3
GUNICORN_TIMEOUT=180
GUNICORN_LOG_LEVEL="debug"

echo "进入项目目录: $PROJECT_DIR"
cd "$PROJECT_DIR" || { echo "❌ 无法进入项目目录 $PROJECT_DIR"; exit 1; }
echo "当前目录: $(pwd)"

echo "🔄 正在从 GitHub 拉取最新代码..."
git reset --hard HEAD
git fetch origin
git reset --hard origin/main
echo "✅ 代码同步完成"

echo "🛑 停止可能正在运行的 Gunicorn 服务..."
PIDS_LSOF=$(lsof -t -i:"$GUNICORN_BIND_PORT" || true)
if [ -n "$PIDS_LSOF" ]; then
    echo "发现占用端口 $GUNICORN_BIND_PORT 的进程: $PIDS_LSOF. 尝试 kill -9..."
    kill -9 $PIDS_LSOF || echo "kill -9 失败或部分失败"
    sleep 3
fi

echo "🔍 进一步清理可能残留的 gunicorn 进程..."
ps aux | grep gunicorn | grep -v grep | awk '{print $2}' | xargs -r kill -9 || echo "未找到残留 gunicorn 进程"
sleep 3

PIDS_FINAL=$(lsof -t -i:"$GUNICORN_BIND_PORT" || true)
if [ -n "$PIDS_FINAL" ]; then
    echo "❌ 错误：端口 $GUNICORN_BIND_PORT 仍被占用，无法继续启动 Gunicorn。当前占用进程: $PIDS_FINAL"
    exit 1
fi
echo "✅ 端口 $GUNICORN_BIND_PORT 已成功释放。"

echo "🚀 启动新的 Gunicorn 进程..."
if [ -f "$VENV_ACTIVATE_PATH" ]; then
    source "$VENV_ACTIVATE_PATH"
else
    echo "❌ 错误：虚拟环境激活脚本未找到: $VENV_ACTIVATE_PATH"
    exit 1
fi

echo "执行：nohup gunicorn --bind ${GUNICORN_BIND_ADDRESS} --workers ${GUNICORN_WORKERS} --timeout ${GUNICORN_TIMEOUT} --worker-class ${GUNICORN_WORKER_CLASS} --log-level ${GUNICORN_LOG_LEVEL} --access-logfile ${GUNICORN_ACCESS_LOG_FILE} --error-logfile ${GUNICORN_ERROR_LOG_FILE} > ${GUNICORN_CAPTURE_LOG_FILE} 2>&1 &"
nohup gunicorn ${GUNICORN_APP} \
    --bind ${GUNICORN_BIND_ADDRESS} \
    --workers ${GUNICORN_WORKERS} \
    --timeout ${GUNICORN_TIMEOUT} \
    --worker-class ${GUNICORN_WORKER_CLASS} \
    --log-level ${GUNICORN_LOG_LEVEL} \
    --access-logfile ${GUNICORN_ACCESS_LOG_FILE} \
    --error-logfile ${GUNICORN_ERROR_LOG_FILE} > ${GUNICORN_CAPTURE_LOG_FILE} 2>&1 &

echo "⏳ 等待 Gunicorn 启动 (3s)..."
sleep 3

if lsof -Pi TCP:"${GUNICORN_BIND_PORT}" -sTCP:LISTEN -t > /dev/null ; then
    echo "✅ 部署完成！Gunicorn 启动成功！"
else
    echo "❌ Gunicorn 启动失败。查看日志文件：${GUNICORN_ERROR_LOG_FILE} 和 ${GUNICORN_CAPTURE_LOG_FILE}"
fi
