#!/bin/bash
# meter-app-v2 OTA setup script
# Run on Orange Pi to install/update meter-app-v2

set -e

INSTALL_DIR="/home/orangepi/meter-app-v2"
BACKUP_DIR="/home/orangepi/meter-app-v2-backup-$(date +%Y%m%d_%H%M%S)"
SERVICE_NAME="meterapp"
VERSION_FILE="$INSTALL_DIR/VERSION"

echo "=== meter-app-v2 Setup ==="
echo "Timestamp: $(date)"

# 1. Stop service if running
if systemctl is-active --quiet $SERVICE_NAME 2>/dev/null; then
    echo "Stopping $SERVICE_NAME service..."
    sudo systemctl stop $SERVICE_NAME
    sleep 2
fi

# 2. Backup current version
if [ -d "$INSTALL_DIR" ]; then
    echo "Backing up current version to $BACKUP_DIR..."
    cp -r "$INSTALL_DIR" "$BACKUP_DIR"
fi

# 3. Extract new version (if zip provided in /tmp)
if [ -f "/tmp/meter-app-v2.zip" ]; then
    echo "Extracting new version..."
    mkdir -p "$INSTALL_DIR"
    unzip -o /tmp/meter-app-v2.zip -d "$INSTALL_DIR"
fi

# 4. Install dependencies
echo "Installing Python dependencies..."
cd "$INSTALL_DIR"
pip3 install -r requirements.txt --quiet

# 5. Validate config.json
echo "Validating config.json..."
python3 -c "import json; json.load(open('config.json'))" || {
    echo "ERROR: config.json is invalid JSON!"
    exit 1
}

# 6. Start service
echo "Starting $SERVICE_NAME service..."
sudo systemctl start $SERVICE_NAME

# 7. Verify
sleep 3
if systemctl is-active --quiet $SERVICE_NAME; then
    echo "✅ Setup complete! Service is running."
    cat $VERSION_FILE 2>/dev/null || echo "Version: unknown"
else
    echo "❌ Service failed to start. Check: journalctl -u $SERVICE_NAME -n 50"
    exit 1
fi
