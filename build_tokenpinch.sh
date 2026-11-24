#!/bin/bash

# Exit on any error
set -e

echo "🔒 TokenPinch Secure App & Binary Compiler v1.2.0"
echo "=================================================="

# Check if PyInstaller and required modules are installed
if ! command -v pyinstaller &> /dev/null; then
    echo "📦 Installing PyInstaller for native Mac compilation..."
    pip3 install pyinstaller
fi

echo "📦 Installing tiktoken and certifi..."
pip3 install tiktoken certifi

echo "🧬 Compiling tokenpinch.py with Cython into a native shared library (.so)..."
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 setup_cython.py build_ext --inplace

echo "🏗️ Compiling launcher.py and native library into a single standalone binary..."

# Clean up any old builds
rm -rf build dist

# Compile into a single, standalone macOS binary utilizing the Cython shared library
pyinstaller --onefile \
            --name="tokenpinch" \
            --clean \
            --hidden-import="certifi" \
            --hidden-import="tiktoken" \
            --hidden-import="tiktoken_ext" \
            --hidden-import="tiktoken_ext.openai_public" \
            --hidden-import="rumps" \
            --add-binary="tokenpinch.cpython-313-darwin.so:." \
            --add-data="/Users/Tariq/.tokenpinch/tiktoken_cache:tiktoken_cache" \
            launcher.py

echo "📦 Creating native macOS App Bundle (TokenPinch.app)..."

APP_DIR="dist/TokenPinch.app"
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"

# Create standard macOS directory structure
mkdir -p "$MACOS_DIR"
mkdir -p "$RESOURCES_DIR"

# Copy compiled binary to MacOS directory as the payload
cp "dist/tokenpinch" "$MACOS_DIR/tokenpinch_bin"

# Create the main executable launcher script
cat << 'EOF' > "$MACOS_DIR/TokenPinch"
#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
export PATH="$PATH:$DIR"

# Launch TokenPinch Tray App in the background
"$DIR/tokenpinch_bin" tray > /dev/null 2>&1 &

# Display a beautiful native notification
osascript -e 'display notification "Saves up to 90% of your AI budget!" with title "🤏 TokenPinch Activated" subtitle "Proxy Gateway live on Port 8799"'
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
