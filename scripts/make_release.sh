#!/usr/bin/env bash
# Usage: scripts/make_release.sh   (run from repo root on a clean, pushed main; needs gh)
set -euo pipefail
v="$(tr -d '[:space:]' < VERSION)"
tag="v$v"
zip="ableton-assistant-$tag.zip"
git archive --format=zip --prefix=ableton-assistant/ -o "$zip" HEAD
notes="$(awk -v v="$v" '$0 ~ "^## "v"$"{f=1;next} /^## /{f=0} f' CHANGELOG.md)"
gh release create "$tag" "$zip" --title "$tag" --notes "${notes:-Release $tag}" --target main
rm -f "$zip"
