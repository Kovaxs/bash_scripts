#!/bin/bash

# Set the source folder (replace with your folder path)
SOURCE_FOLDER="$HOME/bash_scripts/bin/"

# Create $HOME/bin if it doesn't exist
mkdir -p $HOME/bin

# Loop through all files in the source folder and create symlinks
for file in "$SOURCE_FOLDER"/*; do
  if [ -f "$file" ]; then
    ln -sf "$file" "$HOME/bin/$(basename "$file")"
    echo "Symlink created for: $file"
  fi
done

echo "All files have been symlinked to $HOME/bin"
