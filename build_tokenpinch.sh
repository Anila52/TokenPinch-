#!/bin/bash

# Exit on any error
set -e

TARGET="${1:-macos}"
case "$TARGET" in
  windows)
    echo "Build the exe on Windows:"
    echo "  powershell -ExecutionPolicy Bypass -File build/windows/build.ps1"
    exit 0
    ;;
  android)
    exec bash "$(cd "$(dirname "$0")" && pwd)/build/android/install.sh"
    ;;
  macos)
    ;;
  *)
    echo "Usage: ./build_tokenpinch.sh [macos|windows|android]"
    exit 2
    ;;
esac

echo "🔒 TokenPinch Secure App & Binary Compiler v1.2.0"
echo "=================================================="

# Check if PyInstaller and required modules are installed
if ! command -v pyinstaller &> /dev/null; then
    echo "📦 Installing PyInstaller for native Mac compilation..."
    pip3 install pyinstaller
fi

echo "📦 Installing tiktoken and certifi..."
pip3 install tiktoken certifi

echo "🏗️ Compiling launcher.py into one unsigned Mac binary..."

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
rm -rf dist .pyibuild

ICON="$SCRIPT_DIR/MenuBarIconTemplate.png"
CACHE="$HOME/.tokenpinch/tiktoken_cache"
test -f "$ICON"
test -d "$CACHE"

pyinstaller --onefile \
            --name="tokenpinch" \
            --clean \
            --noconfirm \
            --distpath "$SCRIPT_DIR/dist" \
            --workpath "$SCRIPT_DIR/.pyibuild" \
            --specpath "$SCRIPT_DIR/.pyibuild" \
            --hidden-import="certifi" \
            --hidden-import="tiktoken" \
            --hidden-import="tiktoken_ext" \
            --hidden-import="tiktoken_ext.openai_public" \
            --hidden-import="rumps" \
            --add-data="$ICON:." \
            --add-data="$CACHE:tiktoken_cache" \
            "$SCRIPT_DIR/launcher.py"

echo "📦 Creating native macOS App Bundle (TokenPinch.app)..."

APP_DIR="dist/TokenPinch.app"
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"

# Create standard macOS directory structure
mkdir -p "$MACOS_DIR"
mkdir -p "$RESOURCES_DIR"
cp "$SCRIPT_DIR/AppIcon.icns" "$RESOURCES_DIR/AppIcon.icns"
cp "$SCRIPT_DIR/MenuBarIconTemplate.png" "$RESOURCES_DIR/MenuBarIconTemplate.png"

# Copy compiled binary to MacOS directory as the payload
cp "dist/tokenpinch" "$MACOS_DIR/tokenpinch_bin"

# Create the main executable launcher script
cat << 'EOF' > "$MACOS_DIR/TokenPinch"
#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
BIN="$DIR/tokenpinch_bin"
for dir in /usr/local/bin "$HOME/bin" "$HOME/.local/bin"; do
  case ":$PATH:" in
    *":$dir:"*) [ -w "$dir" ] && [ ! -e "$dir/tokenpinch" ] && ln -s "$BIN" "$dir/tokenpinch" ;;
  esac
done
if [ ! -s "$HOME/.tokenpinch/license.json" ]; then
  osascript -e "tell application \"Terminal\" to do script \"exec \\\"$BIN\\\" tray\""
  exit 0
fi
pgrep -x tokenpinch_bin >/dev/null 2>&1 && exit 0
"$BIN" tray >/dev/null 2>&1 &
EOF

# Make the launcher script executable
chmod +x "$MACOS_DIR/TokenPinch"

# Create modern Info.plist metadata file
cat << 'EOF' > "$CONTENTS_DIR/Info.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>TokenPinch</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundleIdentifier</key>
    <string>com.tokenpinch.app</string>
    <key>CFBundleName</key>
    <string>TokenPinch</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.2.0</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.15</string>
</dict>
</plist>
EOF

# Prepare staging folder for DMG creation
DMG_STAGE="dist/dmg_stage"
rm -rf "$DMG_STAGE"
mkdir -p "$DMG_STAGE"

# Copy the app bundle, plugins folder, and a symlink to Applications directory
cp -R "$APP_DIR" "$DMG_STAGE/"
cp -R plugins "$DMG_STAGE/"
ln -s /Applications "$DMG_STAGE/Applications"

echo "💿 Packaging App into a professional macOS Disk Image (.dmg)..."
rm -f ~/Desktop/TokenPinch.dmg
hdiutil create -volname "TokenPinch Installer" -srcfolder "$DMG_STAGE" -ov -format UDZO ~/Desktop/TokenPinch.dmg

# Copy the final App Bundle and standalone binary to Desktop
rm -rf ~/Desktop/TokenPinch.app ~/Desktop/tokenpinch
cp -R "$APP_DIR" ~/Desktop/
cp "dist/tokenpinch" ~/Desktop/

# Sync source copy to Desktop/TokenPinch_Product_Files as well
mkdir -p ~/Desktop/TokenPinch_Product_Files
# Sync source copy to ~/.tokenpinch as well for local execution
cp ~/Desktop/TokenPinch_Product_Files/tokenpinch.py ~/.tokenpinch/tokenpinch.py
cp build_tokenpinch.sh ~/Desktop/TokenPinch_Product_Files/
cp ~/Desktop/TokenPinch.dmg ~/Desktop/TokenPinch_Product_Files/
cp -R ~/Desktop/TokenPinch.app ~/Desktop/TokenPinch_Product_Files/
cp ~/Desktop/tokenpinch ~/Desktop/TokenPinch_Product_Files/
cp -R plugins ~/Desktop/TokenPinch_Product_Files/

echo "=================================================="
echo "🎉 SUCCESS! Your secure native files are ready on your desktop:"
echo "  1. 💿 Disk Image:  ~/Desktop/TokenPinch.dmg (Standard professional download!)"
echo "  2. 📂 App Bundle:  ~/Desktop/TokenPinch.app (Double-click to launch)"
echo "  3. ⚙️ CLI Binary:  ~/Desktop/tokenpinch     (For terminal automations)"
echo "=================================================="
echo "🛡️ Protection Details:"
echo "  - Core logic compiled into native machine executable."
echo "  - Bundle structure is fully compliant with standard macOS requirements."
echo "  - DMG contains decompiler plugins ready for installation!"
