#!/usr/bin/env bash
# Fetch runtime assets that are not committed (all from GitHub / public-domain sources). Idempotent.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p assets/bin assets/voices assets/fonts assets/maps
if [ ! -x assets/bin/piper/piper ]; then
  curl -sL "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz" | tar xz -C assets/bin
fi
if [ ! -f assets/voices/en-us-ryan-high.onnx ]; then
  curl -sL "https://github.com/rhasspy/piper/releases/download/v0.0.2/voice-en-us-ryan-high.tar.gz" | tar xz -C assets/voices
fi
if [ ! -f assets/voices/en-gb-alan-low.onnx ]; then
  curl -sL "https://github.com/rhasspy/piper/releases/download/v0.0.2/voice-en-gb-alan-low.tar.gz" | tar xz -C assets/voices || true
fi
if [ ! -f assets/fonts/Fraunces-SemiBold.ttf ]; then
  curl -sL "https://github.com/undercasetype/Fraunces/raw/master/fonts/static/ttf/Fraunces-SemiBold.ttf" -o assets/fonts/Fraunces-SemiBold.ttf || true
  # sanity: a real TTF starts with 0x00010000 or 'true'
  head -c 4 assets/fonts/Fraunces-SemiBold.ttf | grep -q -P '^\x00\x01\x00\x00|^true' || rm -f assets/fonts/Fraunces-SemiBold.ttf
fi
if [ ! -f assets/fonts/Inter-Regular.ttf ]; then
  curl -sL "https://github.com/rsms/inter/releases/download/v4.1/Inter-4.1.zip" -o /tmp/inter.zip && \
  (cd /tmp && unzip -qo inter.zip 'extras/ttf/Inter-Regular.ttf' 'extras/ttf/Inter-SemiBold.ttf' -d inter && \
   cp inter/extras/ttf/Inter-Regular.ttf inter/extras/ttf/Inter-SemiBold.ttf "$OLDPWD/assets/fonts/") || true
fi
if [ ! -f assets/maps/world.geojson ]; then
  curl -sL "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson" -o assets/maps/world.geojson || true
  [ -s assets/maps/world.geojson ] || rm -f assets/maps/world.geojson
fi
ls -la assets/bin/piper/piper assets/voices/*.onnx
