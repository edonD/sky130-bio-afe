#!/bin/bash
# Run on each EC2 instance to complete setup after user-data partially failed
set -euo pipefail

BLOCK=$(cat /home/ubuntu/block_name 2>/dev/null || echo "unknown")
echo "=== Fixing setup for block: $BLOCK ==="

# ============================================================
# 1. ngspice — install from apt (fast, reliable, good enough)
# ============================================================
echo "=== Installing ngspice from apt ==="
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y ngspice
echo "ngspice: $(ngspice --version 2>&1 | head -1)"

# ============================================================
# 2. Python packages
# ============================================================
echo "=== Installing Python packages ==="
pip3 install --break-system-packages numpy scipy matplotlib optuna cma scikit-optimize 2>/dev/null || \
pip3 install numpy scipy matplotlib optuna cma scikit-optimize

# ============================================================
# 3. Node.js + Claude CLI
# ============================================================
echo "=== Installing Claude CLI ==="
if ! command -v node &>/dev/null; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | sudo bash -
  sudo apt-get install -y nodejs
fi
sudo npm install -g @anthropic-ai/claude-code 2>/dev/null || true

# ============================================================
# 4. SKY130 PDK
# ============================================================
echo "=== Setting up SKY130 PDK ==="
WORK=/home/ubuntu/workspace
mkdir -p $WORK
cd $WORK

if [ ! -d sky130_models ]; then
  git clone --depth 1 https://github.com/mkghub/skywater130_fd_pr_models.git sky130_models
  cd sky130_models
  mkdir -p sky130_fd_pr_models
  for dir in cells corners parameters parasitics capacitors r+c; do
    [ -d "$dir" ] && cp -r "$dir" sky130_fd_pr_models/
  done
  find . -maxdepth 1 -name "*.spice" -exec cp {} sky130_fd_pr_models/ \; 2>/dev/null || true
  cd $WORK
else
  echo "sky130_models already exists"
fi

# ============================================================
# 5. Clone repo
# ============================================================
echo "=== Cloning bio-afe repo ==="
cd $WORK
if [ ! -d sky130-bio-afe/.git ]; then
  git clone https://YOUR_GITHUB_TOKEN@github.com/edonD/sky130-bio-afe.git
fi
cd sky130-bio-afe

# Configure git for commits
git config user.email "agent-${BLOCK}@bio-afe.ai"
git config user.name "Bio-AFE Agent ($BLOCK)"
git remote set-url origin https://YOUR_GITHUB_TOKEN@github.com/edonD/sky130-bio-afe.git

# Symlink PDK into each block
for d in blocks/*/; do
  ln -sf /home/ubuntu/workspace/sky130_models "$d/sky130_models" 2>/dev/null || true
done

# ============================================================
# 6. Test ngspice + PDK
# ============================================================
echo "=== Testing ngspice + SKY130 ==="
cat > /tmp/test.cir << 'SPICE'
* Quick SKY130 test
.lib "/home/ubuntu/workspace/sky130_models/sky130.lib.spice" tt
M1 out in vdd vdd sky130_fd_pr__pfet_01v8 w=1u l=0.15u
M2 out in 0 0 sky130_fd_pr__nfet_01v8 w=0.5u l=0.15u
Vdd vdd 0 1.8
Vin in 0 0.9
.op
.control
run
print v(out)
quit
.endc
.end
SPICE
ngspice -b /tmp/test.cir 2>&1 | grep "v(out)"

# ============================================================
# 7. Convenience: go.sh
# ============================================================
cat > /home/ubuntu/go.sh << GOEOF
#!/bin/bash
BLOCK=\$(cat /home/ubuntu/block_name)
echo "=== Bio-AFE: \$BLOCK ==="
echo "  cd ~/workspace/sky130-bio-afe/blocks/\$BLOCK"
echo "  Then run: claude"
cd /home/ubuntu/workspace/sky130-bio-afe/blocks/\$BLOCK
exec bash
GOEOF
chmod +x /home/ubuntu/go.sh

echo ""
echo "=== SETUP COMPLETE for $BLOCK ==="
echo "READY" > /home/ubuntu/setup_complete
echo ""
echo "Now run:"
echo "  bash ~/go.sh"
echo "  claude"
