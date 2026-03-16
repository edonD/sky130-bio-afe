#!/bin/bash
# ============================================================
# deploy.sh — Launch or destroy Bio-AFE EC2 instances
#
# Usage:
#   ./deploy.sh up        # Launch 5 instances
#   ./deploy.sh down      # Destroy all instances
#   ./deploy.sh status    # Show IPs and SSH commands
#   ./deploy.sh ssh <blk> # SSH into a block instance
# ============================================================

set -euo pipefail
cd "$(dirname "$0")"

ACTION="${1:-status}"

case "$ACTION" in

  up)
    echo "=== Launching 5 Bio-AFE instances ==="
    terraform init -upgrade
    terraform apply -auto-approve
    echo ""
    echo "=== Instances launched. Waiting for setup (~3-5 min) ==="
    echo ""
    terraform output -json ssh_commands | python3 -c "
import json, sys
cmds = json.load(sys.stdin)
for block, cmd in sorted(cmds.items()):
    print(f'  {block:12s} -> {cmd}')
"
    echo ""
    echo "Wait ~5 min for setup to complete, then SSH in."
    echo "On each instance, run:"
    echo "  bash go.sh        # navigate to block directory"
    echo "  claude             # start claude, login with Max account"
    ;;

  down)
    echo "=== Destroying all instances ==="
    terraform destroy -auto-approve
    ;;

  status)
    echo "=== Instance Status ==="
    terraform output -json instances 2>/dev/null | python3 -c "
import json, sys
try:
    ips = json.load(sys.stdin)
    for block, ip in sorted(ips.items()):
        print(f'  {block:12s} -> {ip}')
except:
    print('  No instances running. Run: ./deploy.sh up')
" || echo "  Run 'terraform init' first, or no instances deployed."
    echo ""
    echo "SSH commands:"
    terraform output -json ssh_commands 2>/dev/null | python3 -c "
import json, sys
try:
    cmds = json.load(sys.stdin)
    for block, cmd in sorted(cmds.items()):
        print(f'  {block:12s} -> {cmd}')
except:
    pass
" || true
    ;;

  ssh)
    BLOCK="${2:?Usage: ./deploy.sh ssh <block_name>}"
    IP=$(terraform output -json instances | python3 -c "import json,sys; print(json.load(sys.stdin)['$BLOCK'])")
    KEY=$(grep key_name terraform.tfvars | cut -d'"' -f2)
    echo "Connecting to $BLOCK ($IP)..."
    ssh -i ~/.ssh/${KEY}.pem -o StrictHostKeyChecking=no ubuntu@$IP
    ;;

  *)
    echo "Usage: ./deploy.sh {up|down|status|ssh <block>}"
    exit 1
    ;;
esac
