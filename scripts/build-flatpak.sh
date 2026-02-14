#!/usr/bin/env bash
set -euo pipefail

MANIFEST=flatpak/manifest.yml
BUILD_DIR=flatpak-build
REPO_DIR=flatpak-repo
BUNDLE=disco-notes.flatpak
APP_ID=org.disco.DiscoNotes
BRANCH=stable
RUNTIME_REPO=https://dl.flathub.org/repo/

# Download pre-built wheels for all Python dependencies into flatpak/deps/
echo "Downloading Python dependency wheels..."
rm -rf flatpak/deps && mkdir -p flatpak/deps
uv export --format requirements-txt --no-dev --no-editable --no-emit-project | \
  uv run python -m pip download \
    --only-binary :all: \
    --python-version 3.12 \
    --platform manylinux2014_x86_64 \
    --abi cp312 --abi none --abi abi3 \
    -r /dev/stdin \
    -d flatpak/deps
echo "Downloaded $(ls flatpak/deps/*.whl | wc -l) wheels"

# Clean build outputs
rm -rf "$BUILD_DIR" "$REPO_DIR" "$BUNDLE"

# Build, export to repo, and install locally
flatpak-builder --force-clean --default-branch="$BRANCH" --repo="$REPO_DIR" \
  --install --user "$BUILD_DIR" "$MANIFEST"

# Create a single-file bundle for distribution
flatpak build-bundle "$REPO_DIR" "$BUNDLE" "$APP_ID" "$BRANCH" --runtime-repo="$RUNTIME_REPO"

echo "✓ Built bundle: $BUNDLE"
echo "✓ Installed locally for user"
echo "To run: flatpak run $APP_ID"
