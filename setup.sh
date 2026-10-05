#!/usr/bin/env bash
# One-time setup on the hackathon EC2 instance (Amazon Linux 2023).
#
#   chmod +x setup.sh
#   ./setup.sh
#
set -euo pipefail

echo "==> Installing system packages"
sudo dnf install -y python3 python3-pip git tmux

echo "==> Installing Python dependencies"
if python3 -m pip --version >/dev/null 2>&1; then
  python3 -m pip install --user -r requirements.txt
else
  pip3 install --user -r requirements.txt
fi

echo "==> Verifying"
python3 -c "import requests; print('requests', requests.__version__)"
tmux -V

cat <<'EOF'

Setup complete.

Next steps:
  1. cp env.example env.sh && nano env.sh     # add your Roostoo keys
  2. set -a; . ./env.sh; set +a
  3. python3 bot.py --check                   # read-only preflight
  4. tmux new -s bot 'python3 bot.py'         # start the live bot
     detach with Ctrl-B then D, reattach with: tmux attach -t bot
EOF
