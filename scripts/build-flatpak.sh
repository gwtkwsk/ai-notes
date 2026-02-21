#!/usr/bin/env bash
set -euo pipefail

MANIFEST=flatpak/manifest.yml
BUILD_DIR=build/flatpak-build
REPO_DIR=build/repo
STATE_DIR=build/.flatpak-builder
BUNDLE=build/ai-notes.flatpak
APP_ID=ai.notes.AINotes
BRANCH=stable
RUNTIME_REPO=https://dl.flathub.org/repo/

# Download pre-built wheels for all Python dependencies
echo "Downloading Python dependency wheels..."
rm -rf build/deps && mkdir -p build/deps
uv export --format requirements-txt --no-dev --no-editable --no-emit-project | \
  uv run python -m pip download \
    --only-binary :all: \
    --python-version 3.12 \
    --platform manylinux2014_x86_64 \
    --abi cp312 --abi none --abi abi3 \
    -r /dev/stdin \
    -d build/deps
echo "Downloaded $(ls build/deps/*.whl | wc -l) wheels"

# Clean build outputs
rm -rf "$BUILD_DIR" "$REPO_DIR" "$STATE_DIR" "$BUNDLE"

# Build, export to repo, and install locally
flatpak-builder --force-clean --state-dir="$STATE_DIR" --default-branch="$BRANCH" \
  --repo="$REPO_DIR" --install --user "$BUILD_DIR" "$MANIFEST"

# Create a single-file bundle for distribution
flatpak build-bundle "$REPO_DIR" "$BUNDLE" "$APP_ID" "$BRANCH" --runtime-repo="$RUNTIME_REPO"

echo "✓ Built bundle: $BUNDLE"
echo "✓ Installed locally for user"
echo "To run: flatpak run $APP_ID"
