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
uv export --format requirements-txt --no-dev --no-editable --no-emit-project \
  > /tmp/requirements-flatpak.txt
uv run python -m pip download \
  --only-binary :all: \
  --python-version 3.12 \
  --platform manylinux2014_x86_64 \
  --platform linux_x86_64 \
  --abi cp312 \
  --abi none \
  --abi abi3 \
  --implementation cp \
  -r /tmp/requirements-flatpak.txt \
  -d flatpak/deps
echo "Downloaded $(ls flatpak/deps/*.whl | wc -l) wheels"

# Clean build dir
rm -rf "$BUILD_DIR" "$REPO_DIR" "$BUNDLE"
mkdir -p "$BUILD_DIR" "$REPO_DIR"

# Build and export into a local repo
flatpak-builder --force-clean --default-branch="$BRANCH" --repo="$REPO_DIR" "$BUILD_DIR" "$MANIFEST"

# Create a single-file bundle that references the runtime repo
flatpak build-bundle "$REPO_DIR" "$BUNDLE" "$APP_ID" "$BRANCH" --runtime-repo="$RUNTIME_REPO"

echo "Built repo: $REPO_DIR"
echo "Built bundle: $BUNDLE"

# Optional: install locally for testing (per-user)
flatpak --user remote-add --no-gpg-verify local-disconotes "$REPO_DIR" 2>/dev/null || true
flatpak --user install local-disconotes "$APP_ID" "$BRANCH" -y || true

echo "To run: flatpak run $APP_ID"
