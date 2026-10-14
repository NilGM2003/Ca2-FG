#!/bin/bash
# Creates "LIFU Sonication.app" on the Desktop (or in the folder given as first argument).
# Double-clicking it starts the GUI without opening a terminal or an editor.
#
# Usage (from anywhere):   bash scripts/make_mac_app.sh
#
# The app runs `uv run lifu-gui` inside this project folder, so presets, limits and the
# sonication log stay in <project>/data. If you move or rename the project folder,
# run this script again.
set -euo pipefail

PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
APP_NAME="LIFU Sonication"
DEST="${1:-$HOME/Desktop}"
APP="$DEST/$APP_NAME.app"

# --- find uv (Finder-launched apps do not read your shell profile) -----------------
UV="${UV:-$(command -v uv || true)}"
if [ -z "$UV" ]; then
  for c in /opt/homebrew/bin/uv /usr/local/bin/uv "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
    if [ -x "$c" ]; then UV="$c"; break; fi
  done
fi
if [ -z "$UV" ]; then
  echo "Could not find uv. Install it (https://docs.astral.sh/uv/) and run this again." >&2
  exit 1
fi
echo "Project: $PROJECT"
echo "uv:      $UV"

# --- bundle skeleton ------------------------------------------------------------------
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$PROJECT/data"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>$APP_NAME</string>
  <key>CFBundleDisplayName</key><string>$APP_NAME</string>
  <key>CFBundleIdentifier</key><string>local.lifu.sonication</string>
  <key>CFBundleExecutable</key><string>launcher</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

# --- launcher -------------------------------------------------------------------------
cat > "$APP/Contents/MacOS/launcher" <<LAUNCHER
#!/bin/bash
cd "$PROJECT" || exit 1
export PATH="$(dirname "$UV"):/opt/homebrew/bin:/usr/local/bin:\$PATH"
# libusb (needed for USB access to the generator)
export DYLD_FALLBACK_LIBRARY_PATH="/opt/homebrew/lib:/usr/local/lib:\${DYLD_FALLBACK_LIBRARY_PATH:-}"
LOG="$PROJECT/data/launcher.log"
echo "=== \$(date) ===" >> "\$LOG"
"$UV" run --quiet lifu-gui >> "\$LOG" 2>&1
code=\$?
if [ \$code -ne 0 ]; then
  osascript -e 'display dialog "LIFU Sonication stopped with an error. Details are in data/launcher.log inside the project folder." buttons {"OK"} default button "OK" with icon caution'
fi
exit \$code
LAUNCHER
chmod +x "$APP/Contents/MacOS/launcher"

# --- icon (optional; the app works without it) ------------------------------------
TMP="$(mktemp -d)"
PNG="$TMP/icon_1024.png"
if "$UV" run --quiet --project "$PROJECT" python "$PROJECT/scripts/make_icon.py" "$PNG" 2>/dev/null && [ -f "$PNG" ]; then
  ICONSET="$TMP/AppIcon.iconset"
  mkdir -p "$ICONSET"
  for s in 16 32 128 256 512; do
    sips -z "$s" "$s" "$PNG" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
    sips -z "$((s * 2))" "$((s * 2))" "$PNG" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns" || echo "Icon step failed; the app will use a default icon."
else
  echo "Could not draw the icon; the app will use a default icon."
fi
rm -rf "$TMP"

xattr -cr "$APP" 2>/dev/null || true
touch "$APP"
echo
echo "Created: $APP"
echo "Double-click it to start. (First launch may take a few seconds.)"
