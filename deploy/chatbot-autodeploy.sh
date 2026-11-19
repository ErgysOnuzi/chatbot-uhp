#!/bin/sh
# Vendosje automatike: kur në GitHub ka commit të ri në main, e merr dhe e rindërton backend-in dhe frontend-in.
# Instalimi (si root, një herë):
#   install -m 755 deploy/chatbot-autodeploy.sh /usr/local/bin/chatbot-autodeploy
#   cp deploy/chatbot-autodeploy.service deploy/chatbot-autodeploy.timer /etc/systemd/system/
#   systemctl daemon-reload && systemctl enable --now chatbot-autodeploy.timer
# Regjistri: journalctl -u chatbot-autodeploy
set -eu

SERVICE_DIR="${CHATBOT_SERVICE_DIR:-/data/coolify/services/awvqxjdqdo6ry0ksqrwfiiq9}"
PROJECT="${CHATBOT_COMPOSE_PROJECT:-awvqxjdqdo6ry0ksqrwfiiq9}"
REPO="$SERVICE_DIR/source/chatbot-uhp"

exec 9>/run/chatbot-autodeploy.lock
flock -n 9 || { echo "Një vendosje tjetër është duke u kryer."; exit 0; }

cd "$REPO"
git fetch -q origin main
local_rev=$(git rev-parse HEAD)
remote_rev=$(git rev-parse origin/main)
[ "$local_rev" = "$remote_rev" ] && exit 0

# Ndryshimet e paruajtura në server (p.sh. punë në vazhdim) nuk mbishkruhen kurrë.
if [ -n "$(git status --porcelain)" ]; then
  echo "Ka ndryshime lokale në $REPO; vendosja u anashkalua."
  exit 0
fi
if [ "$(git rev-parse --abbrev-ref HEAD)" != "main" ]; then
  echo "Dega aktuale nuk është main; vendosja u anashkalua."
  exit 0
fi

git merge --ff-only -q origin/main
echo "Vendoset $(git log --oneline -1)"
cd "$SERVICE_DIR"
docker compose -p "$PROJECT" up -d --build backend frontend
echo "Vendosja përfundoi."
