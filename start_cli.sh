#!/usr/bin/env bash
read -p "Do you want to use cloud (Gemini Omni Flash) or local rendering? (Enter 'cloud' or 'local'): " mode

if [ "$mode" != "cloud" ] && [ "$mode" != "local" ]; then
    echo "Invalid choice. Defaulting to local."
    mode="local"
fi

read -p "Enter the path to your JSON file (e.g., samples/BMW_M5.json): " sample
if [ -z "$sample" ]; then
    echo "No file provided. Exiting."
    exit 1
fi

echo "Generating video using $mode mode for $sample..."
python cli.py generate $mode --json "$sample"
