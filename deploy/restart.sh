#!/bin/bash
# 智题学习笔记 - 后端统一重启脚本（服务器端副本，部署在 /www/wwwroot/quizapp/restart.sh）
# 用法: sudo bash /www/wwwroot/quizapp/restart.sh
#
# 现状（2026-09-23 起）：
#   - API 由 systemd 托管：quizapp-api.service
#   - 出题 worker 由 systemd 托管：quizapp-worker.service
#   两者都是 Restart=always，崩溃会自愈。
#
# 历史说明：早期 API 由宝塔「python环境管理器」以 nohup 拉起（父进程 init），
#   既没有服务名，宝塔面板的 RestartProject 也可能出现"只停不起"，
#   因此改为 systemd 托管。
#   本脚本保留为统一入口，systemd 单元都未安装时自动回退到手工拉起。
set -u

PY=/www/server/pyporject_evn/versions/3.11.16/bin/python3.11
APP_DIR=/www/wwwroot/quizapp/backend
LOG_DIR=/www/wwwlogs/python/quizapp-backend
API_LOG="$LOG_DIR/error.log"
WORKER_LOG="$LOG_DIR/worker.log"
HEALTH_URL=http://127.0.0.1:8000/health
HEALTH_WAIT_SECONDS=45
BODY=""
HTTP_STATUS="000"

health_body_is_ok() {
  case "$1" in
    *'"status":"ok"'*) ;;
    *) return 1 ;;
  esac
  case "$1" in
    *'"database":"ok"'*) ;;
    *) return 1 ;;
  esac
  case "$1" in
    *'"queue":"ok"'*) return 0 ;;
    *) return 1 ;;
  esac
}

wait_for_health() {
  local attempt=0
  local raw=""
  while [ "$attempt" -lt "$HEALTH_WAIT_SECONDS" ]; do
    attempt=$((attempt + 1))
    if raw=$(curl -sS -m 5 -w '\n%{http_code}' "$HEALTH_URL" 2>/dev/null); then
      HTTP_STATUS="${raw##*$'\n'}"
      BODY="${raw%$'\n'*}"
      if [ "$HTTP_STATUS" = "200" ] && health_body_is_ok "$BODY"; then
        return 0
      fi
    else
      HTTP_STATUS="000"
      BODY=""
    fi
    sleep 1
  done
  return 1
}

show_processes() {
  ps -eo pid,user,lstart,cmd \
    | grep -E 'uvicorn app[.]main|arq app[.]worker' \
    | grep -v grep || true
}

sync_baota_pid_file() {
  if [ -w /www/server/python_project/vhost/pids/quizapp-backend.pid ]; then
    systemctl show quizapp-api -p MainPID --value \
      > /www/server/python_project/vhost/pids/quizapp-backend.pid 2>/dev/null || true
  fi
}

API_UNIT_INSTALLED=0
WORKER_UNIT_INSTALLED=0
if command -v systemctl >/dev/null 2>&1; then
  if systemctl cat quizapp-api.service >/dev/null 2>&1; then
    API_UNIT_INSTALLED=1
  fi
  if systemctl cat quizapp-worker.service >/dev/null 2>&1; then
    WORKER_UNIT_INSTALLED=1
  fi
fi

if [ "$API_UNIT_INSTALLED" -eq 1 ] && [ "$WORKER_UNIT_INSTALLED" -eq 1 ]; then
  echo ">>> 重启 quizapp-worker..."
  if ! systemctl restart quizapp-worker; then
    echo ">>> Worker 重启失败！"
    journalctl -u quizapp-worker -n 60 --no-pager
    exit 1
  fi

  echo ">>> 重启 quizapp-api..."
  if ! systemctl restart quizapp-api; then
    echo ">>> API 重启失败！"
    journalctl -u quizapp-api -n 60 --no-pager
    exit 1
  fi

  # 留出导入应用和连接 Redis/MySQL 的时间，避免只看到 systemd 的瞬时 active。
  sleep 3
  if ! systemctl is-active --quiet quizapp-worker \
    || ! systemctl is-active --quiet quizapp-api; then
    echo ">>> API 或 Worker 未保持运行状态！"
    systemctl --no-pager --full status quizapp-api quizapp-worker || true
    exit 1
  fi

  echo ">>> API 与 Worker 已重启，等待完整健康检查..."
  if wait_for_health; then
    echo ">>> 健康检查通过（HTTP $HTTP_STATUS）: $BODY"
    echo ">>> 当前进程："
    show_processes
    sync_baota_pid_file
    exit 0
  fi

  echo ">>> 健康检查失败（最后状态 HTTP $HTTP_STATUS）: ${BODY:-无响应}"
  systemctl --no-pager --full status quizapp-api quizapp-worker || true
  echo ">>> API 最近日志："
  journalctl -u quizapp-api -n 60 --no-pager
  echo ">>> Worker 最近日志："
  journalctl -u quizapp-worker -n 60 --no-pager
  exit 1
fi

if [ "$API_UNIT_INSTALLED" -ne "$WORKER_UNIT_INSTALLED" ]; then
  echo ">>> 部署不完整：quizapp-api 与 quizapp-worker 必须同时安装为 systemd 服务。"
  echo ">>> 为避免重复进程，本次不会回退到手工启动。"
  exit 1
fi

echo ">>> 未安装 systemd 服务，回退到手工拉起 API 与 Worker..."
echo ">>> 停止旧 API 与 Worker 进程..."
pkill -f 'uvicorn app[.]main' 2>/dev/null || true
pkill -f 'arq app[.]worker' 2>/dev/null || true
sleep 2

echo ">>> 启动 Worker 与 API..."
cd "$APP_DIR" || exit 1
mkdir -p "$LOG_DIR"
chown www:www "$LOG_DIR"
sudo -u www bash -c "setsid $PY -m arq app.worker.WorkerSettings >> $WORKER_LOG 2>&1 < /dev/null &"
sudo -u www bash -c "setsid $PY -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips=127.0.0.1 >> $API_LOG 2>&1 < /dev/null &"

if wait_for_health; then
  echo ">>> 健康检查通过（HTTP $HTTP_STATUS）: $BODY"
  echo ">>> 当前进程："
  show_processes
  exit 0
fi

echo ">>> 健康检查失败（最后状态 HTTP $HTTP_STATUS）: ${BODY:-无响应}"
echo ">>> API 最近日志："
tail -60 "$API_LOG" 2>/dev/null || true
echo ">>> Worker 最近日志："
tail -60 "$WORKER_LOG" 2>/dev/null || true
exit 1
