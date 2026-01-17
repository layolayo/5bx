#!/bin/bash

# 5BX Installation Script
# Installs udev rules for Garmin devices as described in readme.txt

RULES_FILE="99-garmin.rules"
DEST_DIR="/etc/udev/rules.d"

if [ ! -f "$RULES_FILE" ]; then
    echo "Error: $RULES_FILE not found in current directory."
    echo "Please run this script from the 5BX project folder."
    exit 1
fi

echo "Installing $RULES_FILE to $DEST_DIR..."
sudo cp "$RULES_FILE" "$DEST_DIR/$RULES_FILE"

echo "Reloading udev rules..."
sudo udevadm control --reload-rules && sudo udevadm trigger

echo "Installation complete."
