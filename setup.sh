#!/bin/bash

# Set the source folder (this repo)
SOURCE_FOLDER="$HOME/bin_scripts/bin"

# Create $HOME/.local/bin if it doesn't exist
mkdir -p "$HOME/.local/bin"

# Loop through all files in the source folder and create symlinks
for file in "$SOURCE_FOLDER"/*; do
  if [ -f "$file" ]; then
    ln -sf "$file" "$HOME/.local/bin/$(basename "$file")"
    echo "Symlink created for: $file"
  fi
done

echo "All files have been symlinked to $HOME/.local/bin"
