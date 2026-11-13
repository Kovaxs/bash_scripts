#!/bin/bash
#
# Symlink every file in ./bin into $HOME/.local/bin.
# Safe to run as ./setup.sh, or to source from bash or zsh.

# Resolve the folder this script lives in (works when executed or sourced from bash/zsh)
SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
SOURCE_FOLDER="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)/bin"

if [ ! -d "$SOURCE_FOLDER" ]; then
  echo "Source folder not found: $SOURCE_FOLDER" >&2
  return 1 2>/dev/null || exit 1
fi

mkdir -p "$HOME/.local/bin"

# Use find instead of a glob: zsh aborts on an unmatched glob (nomatch),
# whereas bash passes the literal pattern through.
find "$SOURCE_FOLDER" -mindepth 1 -maxdepth 1 -type f | while IFS= read -r file; do
  ln -sf "$file" "$HOME/.local/bin/$(basename "$file")"
  echo "Symlink created for: $file"
done

echo "All files have been symlinked to $HOME/.local/bin"

# spi needs a tiny Pi extension to report the active session without guessing.
EXTENSION_SOURCE="$(dirname "$SOURCE_FOLDER")/pi-extensions/spi.js"
if [ -f "$EXTENSION_SOURCE" ]; then
  PI_EXTENSIONS="${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}/extensions"
  mkdir -p "$PI_EXTENSIONS"
  ln -sf "$EXTENSION_SOURCE" "$PI_EXTENSIONS/spi.js"
  echo "Pi extension installed: $PI_EXTENSIONS/spi.js (run /reload in existing instances)"
fi
