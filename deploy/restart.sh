#!/bin/bash
# 智题学习笔记 - 后端服务重启脚本（服务器端副本，部署在 /www/wwwroot/quizapp/restart.sh）
# 用法: sudo bash /www/wwwroot/quizapp/restart.sh
#
# 背景：本项目 uvicorn 由宝塔「python环境管理器」以 nohup 方式拉起，父进程为 init，
#       不走 systemd / supervisor，因此没有服务名可直接 restart，
#       需要「先 pkill 旧进程，再以 www 用户重新拉起」。
PY=/www/server/pyporject_evn/versions/3.11.16/bin/python3.11
UVICORN=/www/server/pyporject_evn/versions/3.11.16/bin/uvicorn
APP_DIR=/www/wwwroot/quizapp/backend
LOG=/www/wwwlogs/python/quizapp-backend/error.log

echo ">>> 停止旧进程..."
pkill -f 'uvicorn app.main:app'
sleep 2

echo ">>> 启动新进程..."
cd "$APP_DIR" || exit 1
sudo -u www bash -c "setsid $UVICORN app.main:app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips=127.0.0.1 >> $LOG 2>&1 < /dev/null &"
sleep 4

echo ">>> 健康检查..."
if curl -s --max-time 6 http://127.0.0.1:8000/health; then
  echo ""
  echo ">>> 重启完成，当前进程："
  ps -eo pid,user,cmd | grep 'uvicorn app.main' | grep -v grep
else
  echo ""
  echo ">>> 启动失败！最近日志："
  tail -30 "$LOG"
  exit 1
fi
