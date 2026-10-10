#!/usr/bin/env bash
# Cross-compiles the plugin for 64-bit Windows from Linux (cargo-xwin) -> dist/Mortiflix-Singer-plugin-windows.zip
set -euo pipefail
cd "$(dirname "$0")"
XWIN_ACCEPT_LICENSE=1 cargo xwin build --release --lib --target x86_64-pc-windows-msvc
rm -rf dist && mkdir -p "dist/Mortiflix Singer.vst3/Contents/x86_64-win"
cp target/x86_64-pc-windows-msvc/release/mortiflix_singer_bridge.dll "dist/Mortiflix Singer.vst3/Contents/x86_64-win/Mortiflix Singer.vst3"
cp target/x86_64-pc-windows-msvc/release/mortiflix_singer_bridge.dll "dist/Mortiflix Singer.clap"
(cd dist && zip -qr Mortiflix-Singer-plugin-windows.zip "Mortiflix Singer.vst3" "Mortiflix Singer.clap")
echo "dist/Mortiflix-Singer-plugin-windows.zip"
