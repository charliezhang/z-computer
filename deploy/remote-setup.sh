#!/usr/bin/env bash
# Runs ON the instance (invoked by deploy.sh). Installs Caddy, Node, the Claude CLI and uv once; builds and restarts every time.
set -euo pipefail
SITE="${SITE:?SITE hostname required}"
APP=/home/ubuntu/z-computer
export DEBIAN_FRONTEND=noninteractive

if ! command -v caddy >/dev/null; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl rsync
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  sudo apt-get update -qq && sudo apt-get install -y -qq caddy
fi
if ! command -v node >/dev/null; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - >/dev/null
  sudo apt-get install -y -qq nodejs
fi
command -v claude >/dev/null || sudo npm install -g --silent @anthropic-ai/claude-code
[ -x "$HOME/.local/bin/uv" ] || curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
export PATH="$HOME/.local/bin:$PATH"

(cd "$APP/backend" && uv sync -q)
(cd "$APP/frontend" && npm ci --silent && npm run build --silent)
sudo mkdir -p /var/www/z-computer && sudo rsync -a --delete "$APP/frontend/dist/" /var/www/z-computer/

sudo tee /etc/systemd/system/z-backend.service >/dev/null <<UNIT
[Unit]
Description=Z-Studio backend (FastAPI + Z-Coder + Z-runtime)
After=network.target

[Service]
User=ubuntu
WorkingDirectory=$APP/backend
EnvironmentFile=-$APP/backend/.env
Environment=PATH=/home/ubuntu/.local/bin:/usr/local/bin:/usr/bin:/bin HOME=/home/ubuntu
ExecStart=/home/ubuntu/.local/bin/uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
UNIT

sudo tee /etc/caddy/Caddyfile >/dev/null <<CADDY
$SITE {
	handle /api/* {
		reverse_proxy 127.0.0.1:8000
	}
	handle /ws/* {
		reverse_proxy 127.0.0.1:8000
	}
	handle {
		root * /var/www/z-computer
		try_files {path} /index.html
		file_server
	}
}
CADDY

sudo systemctl daemon-reload
sudo systemctl enable z-backend >/dev/null 2>&1
sudo systemctl restart z-backend
sudo systemctl enable caddy >/dev/null 2>&1
sudo systemctl reload caddy 2>/dev/null || sudo systemctl restart caddy
for i in $(seq 1 15); do
  curl -sf http://127.0.0.1:8000/api/health >/dev/null && { echo "backend healthy"; exit 0; }
  sleep 2
done
echo "backend NOT healthy after 30s"; sudo journalctl -u z-backend -n 30 --no-pager; exit 1
