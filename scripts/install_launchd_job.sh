#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
PLIST_NAME="com.codex.us-low-price-volume-report.plist"
SOURCE_PLIST="$ROOT_DIR/launchd/$PLIST_NAME"
TARGET_DIR="$HOME/Library/LaunchAgents"
TARGET_PLIST="$TARGET_DIR/$PLIST_NAME"

mkdir -p "$TARGET_DIR"
cp "$SOURCE_PLIST" "$TARGET_PLIST"

launchctl unload "$TARGET_PLIST" 2>/dev/null || true
launchctl load "$TARGET_PLIST"

echo "Installed launchd job: $TARGET_PLIST"
