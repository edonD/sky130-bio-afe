#!/bin/bash
set -euo pipefail
exec > /var/log/user-data.log 2>&1

BLOCK="${block_name}"
echo "=== Bio-AFE setup for block: $BLOCK ==="

# Wait for apt locks
sleep 15
for i in 1 2 3 4 5 6 7 8 9 10; do
  fuser /var/lib/apt/lists/lock >/dev/null 2>&1 || break
  sleep 5
done
for i in 1 2 3 4 5 6 7 8 9 10; do
  fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 || break
  sleep 5
done

# ============================================================
# 1. System packages
# ============================================================
apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  build-essential git tmux curl wget unzip \
  python3 python3-pip python3-venv \
  libreadline-dev libx11-dev libxaw7-dev libfftw3-dev \
  bison flex autoconf automake libtool

# ============================================================
# 2. ngspice 44 from source
# ============================================================
echo "=== Building ngspice 44 ==="
cd /tmp
wget -q https://sourceforge.net/projects/ngspice/files/ng-spice-rework/44/ngspice-44.tar.gz/download -O ngspice-44.tar.gz
tar xzf ngspice-44.tar.gz
cd ngspice-44
mkdir -p release
cd release
../configure \
  --with-readline=yes \
  --enable-xspice \
  --enable-cider \
  --enable-openmp \
  --disable-debug \
  --prefix=/usr/local
make -j16
make install
ldconfig

# ============================================================
# 3. Python packages
# ============================================================
echo "=== Installing Python packages ==="
pip3 install --break-system-packages \
  numpy scipy matplotlib \
  optuna cma scikit-optimize

# ============================================================
# 4. Node.js + Claude Code CLI
# ============================================================
echo "=== Installing Claude Code CLI ==="
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt-get install -y nodejs
npm install -g @anthropic-ai/claude-code

# ============================================================
# 5. SKY130 PDK models
# ============================================================
echo "=== Setting up SKY130 PDK ==="
WORK=/home/ubuntu/workspace
mkdir -p $WORK
cd $WORK

git clone --depth 1 https://github.com/mkghub/skywater130_fd_pr_models.git sky130_models
cd sky130_models
mkdir -p sky130_fd_pr_models
for dir in cells corners parameters parasitics capacitors r+c; do
  if [ -d "$dir" ]; then cp -r "$dir" sky130_fd_pr_models/; fi
done
find . -maxdepth 1 -name "*.spice" -exec cp {} sky130_fd_pr_models/ \; 2>/dev/null || true
cd $WORK

# ============================================================
# 6. Write block name and convenience scripts
# ============================================================
echo "$BLOCK" > /home/ubuntu/block_name

# go.sh — quick start
cat > /home/ubuntu/go.sh << 'INNEREOF'
#!/bin/bash
BLOCK=$(cat /home/ubuntu/block_name)
echo "=== Bio-AFE Agent: $BLOCK ==="
echo ""
echo "Tools:"
command -v ngspice && echo "  ngspice: OK"
command -v python3 && echo "  python3: OK"
command -v claude && echo "  claude:  OK"
echo ""
echo "Next steps:"
echo "  1. Clone your repo:  bash ~/clone_repo.sh <repo_url>"
echo "  2. cd ~/workspace/sky130-bio-afe/blocks/$BLOCK"
echo "  3. Run: claude"
echo "  4. Login with your Max account"
echo ""
INNEREOF
chmod +x /home/ubuntu/go.sh

# clone_repo.sh — clone and link PDK
cat > /home/ubuntu/clone_repo.sh << 'INNEREOF'
#!/bin/bash
REPO_URL="$${1:?Usage: bash clone_repo.sh <repo_url>}"
BLOCK=$(cat /home/ubuntu/block_name)
cd /home/ubuntu/workspace
rm -rf sky130-bio-afe
git clone "$REPO_URL" sky130-bio-afe
cd sky130-bio-afe
for d in blocks/*/; do
  ln -sf /home/ubuntu/workspace/sky130_models "$d/sky130_models"
done
echo ""
echo "Done. Now run:"
echo "  cd ~/workspace/sky130-bio-afe/blocks/$BLOCK"
echo "  claude"
INNEREOF
chmod +x /home/ubuntu/clone_repo.sh

# test_ngspice.sh
cat > /home/ubuntu/test_ngspice.sh << 'INNEREOF'
#!/bin/bash
echo "Testing ngspice + SKY130..."
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
ngspice -b /tmp/test.cir
echo ""
echo "If you see a voltage, ngspice + SKY130 works."
INNEREOF
chmod +x /home/ubuntu/test_ngspice.sh

# ============================================================
# Done
# ============================================================
chown -R ubuntu:ubuntu /home/ubuntu
echo "=== Setup complete for $BLOCK ==="
echo "READY" > /home/ubuntu/setup_complete
