#!/bin/sh
# Dev deploy to Ollie (Kodi in the "kodi" Docker container, next to the
# AVR-X2700H): copy the addon into the container and restart the service
# (disable + enable over JSON-RPC inside the container).
#   scripts/deploy.sh            (KODI_SSH defaults to "ollie")
set -eu
SSH_HOST="${KODI_SSH:-ollie}"
ID=service.denonavr
DEST=/storage/.kodi/addons/$ID
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

rpc() {
  printf '{"jsonrpc":"2.0","id":1,"method":"Addons.SetAddonEnabled","params":{"addonid":"%s","enabled":%s}}' "$ID" "$1" |
    ssh "$SSH_HOST" "sudo -n docker exec -i kodi sh -c 'nc -w 2 127.0.0.1 9090'" >/dev/null || true
}

rpc false
sleep 3
COPYFILE_DISABLE=1 tar -C "$ROOT" -cf - --exclude __pycache__ --exclude .DS_Store \
  addon.xml LICENSE.txt README.md service.py default.py resources |
  ssh "$SSH_HOST" "sudo -n docker exec -i kodi sh -c 'set -e; rm -rf $DEST.new; mkdir -p $DEST.new;
    tar -xf - -C $DEST.new; rm -rf $DEST.old; [ -d $DEST ] && mv $DEST $DEST.old; mv $DEST.new $DEST;
    rm -rf $DEST.old'"
sleep 2
rpc true
echo "deployed $ID to $SSH_HOST and restarted the service"
