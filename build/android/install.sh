#!/data/data/com.termux/files/usr/bin/bash
set -e
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

if [ -z "${PREFIX:-}" ] || ! printf '%s' "$PREFIX" | grep -q '/com.termux/'; then
    echo "Run build/android/install.sh inside Termux on Android."
    exit 1
fi

pkg install -y python
pip install -r "$ROOT/requirements.txt"
mkdir -p "$PREFIX/share/tokenpinch" "$PREFIX/bin"
cp "$ROOT/tokenpinch.py" "$PREFIX/share/tokenpinch/tokenpinch.py"
cat > "$PREFIX/bin/tokenpinch" << EOF
#!/data/data/com.termux/files/usr/bin/sh
exec python3 "\$PREFIX/share/tokenpinch/tokenpinch.py" "\$@"
EOF
chmod +x "$PREFIX/bin/tokenpinch"
python3 "$ROOT/tokenpinch.py" autostart
echo "Android gateway starts at Termux boot. Chrome on Android cannot load the browser companion."
