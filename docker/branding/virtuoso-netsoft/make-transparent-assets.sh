#!/usr/bin/env bash
# Convert Virtuoso logo/favicon JPEGs to true transparent PNGs and regenerate derived assets.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ASSETS="${SCRIPT_DIR}/assets"
FUZZ="${VIRTUOSO_BG_FUZZ:-12%}"

if ! command -v convert >/dev/null 2>&1; then
  echo "ERROR: ImageMagick convert is required" >&2
  exit 1
fi

make_transparent() {
  local src="$1"
  local dst="$2"
  local tmp="${dst}.tmp.png"
  convert "$src" \( +clone -fuzz "$FUZZ" -fill none -floodfill +0+0 black \) \
    -alpha off -compose CopyOpacity -composite PNG32:"$tmp"
  mv -f "$tmp" "$dst"
  echo "  transparent PNG: $(basename "$dst")"
}

echo "==> Removing black background (fuzz=${FUZZ})"
for name in virtuoso-logo.png virtuoso-favicon.png; do
  src="${ASSETS}/${name}"
  [[ -f "$src" ]] || { echo "ERROR: missing ${src}" >&2; exit 1; }
  make_transparent "$src" "$src"
done

echo "==> Regenerating virtuoso-favicon.ico"
convert "${ASSETS}/virtuoso-favicon.png" \
  \( -clone 0 -resize 16x16 \) \
  \( -clone 0 -resize 32x32 \) \
  \( -clone 0 -resize 48x48 \) \
  -delete 0 "${ASSETS}/virtuoso-favicon.ico"

echo "==> Regenerating logo SVG wrappers"
python3 "${SCRIPT_DIR}/generate-logo-svgs.py"

echo "==> Asset check"
file "${ASSETS}/virtuoso-logo.png" "${ASSETS}/virtuoso-favicon.png"
identify -format '%f: %m %A\n' "${ASSETS}/virtuoso-logo.png" "${ASSETS}/virtuoso-favicon.png"

echo "==> Syncing to Keycloak theme directories"
DOCKER_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
for theme_img in \
  "${DOCKER_ROOT}/keycloak-theme/virtuoso/login/resources/img" \
  "${DOCKER_ROOT}/keycloak-theme/variphi/login/resources/img"; do
  mkdir -p "$theme_img"
  cp -a "${ASSETS}/virtuoso-logo.png" "${ASSETS}/virtuoso-favicon.png" "${ASSETS}/virtuoso-favicon.ico" \
    "$theme_img/"
  echo "  synced -> ${theme_img}"
done

echo "OK: Virtuoso assets are transparent PNGs"
