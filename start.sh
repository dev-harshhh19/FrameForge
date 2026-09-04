#!/usr/bin/env bash
read -p "Do you want to use cloud (Gemini Omni Flash) or local rendering? (Enter 'cloud' or 'local'): " mode

if [ "$mode" != "cloud" ] && [ "$mode" != "local" ]; then
    echo "Invalid choice. Defaulting to local."
    mode="local"
fi

sample="samples/BMW_M5.json"
echo "Generating video using $mode mode for $sample..."
python cli.py generate $mode --json "$sample"
