$mode = Read-Host "Do you want to use cloud (Gemini Omni Flash) or local rendering? (Enter 'cloud' or 'local')"
if ($mode -ne "cloud" -and $mode -ne "local") {
    Write-Host "Invalid choice. Defaulting to local."
    $mode = "local"
}

$sample = Read-Host "Enter the path to your JSON file (e.g., samples/BMW_M5.json)"
if ([string]::IsNullOrWhiteSpace($sample)) {
    Write-Host "No file provided. Exiting."
    exit 1
}

Write-Host "Generating video using $mode mode for $sample..."
python cli.py generate $mode --json $sample
