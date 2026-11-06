#!/usr/bin/env bash
# Creates the private analysis folder from this kit.
#   ./setup.sh ~/life-analysis /path/to/archive.json
set -euo pipefail
if [ "$#" -ne 2 ]; then echo "usage: $0 DEST_FOLDER ARCHIVE_JSON"; exit 2; fi
DEST="$1"; ARCHIVE="$2"
KIT="$(cd "$(dirname "$0")" && pwd)"
case "$DEST" in
  *"Mobile Documents"*|*iCloud*|*Dropbox*|*"Google Drive"*|*GoogleDrive*|*OneDrive*)
    echo "Refusing: $DEST looks like a synced folder. Choose a folder that is not synced."; exit 1;;
esac
[ -f "$ARCHIVE" ] || { echo "Not found: $ARCHIVE"; exit 1; }
[ -e "$DEST" ] && [ -n "$(ls -A "$DEST" 2>/dev/null)" ] && { echo "Refusing: $DEST is not empty."; exit 1; }
mkdir -p "$DEST"/{raw,private,work,out}
cp -R "$KIT/template/." "$DEST/"
cp "$ARCHIVE" "$DEST/raw/archive.json"
chmod a-w "$DEST/raw/archive.json" "$DEST/raw"
chmod 700 "$DEST/private"
echo "Created $DEST"
echo "Next: cd $DEST && python3 tools/suggest_names.py   (see $KIT/README.md)"
python3 "$DEST/tools/check_setup.py" "$DEST" || true
