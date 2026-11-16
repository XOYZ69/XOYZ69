#!/usr/bin/env bash
# Installs the Yoshida command line tool from a GitHub release into ./.yoshida-bin
# Version: $YOSHIDA_VERSION, else yoshida/YOSHIDA_VERSION ("latest" is allowed).
# Needs: gh (with GH_TOKEN), unzip.
set -euo pipefail

version="${YOSHIDA_VERSION:-$(tr -d '[:space:]' < yoshida/YOSHIDA_VERSION)}"
if [ "$version" = "latest" ]; then
  tag="$(gh release view -R XOYZ69/yoshida --json tagName --jq .tagName)"
else
  tag="v${version#v}"
fi

case "$(uname -m)" in
  x86_64) arch=x86_64 ;;
  aarch64|arm64) arch=aarch64 ;;
  *) echo "unsupported architecture $(uname -m)" >&2; exit 1 ;;
esac

work="$(mktemp -d)"
gh release download "$tag" -R XOYZ69/yoshida -p 'yoshida-*.zip' -D "$work"
unzip -q "$work"/yoshida-*.zip -d "$work/unpacked"
bin="$(find "$work/unpacked" -path "*/bin/${arch}-linux/yoshida" -type f | head -n 1)"
[ -n "$bin" ] || { echo "no ${arch}-linux binary in release $tag" >&2; exit 1; }

mkdir -p .yoshida-bin
install -m 0755 "$bin" .yoshida-bin/yoshida
.yoshida-bin/yoshida version
echo "YOSHIDA_BIN=$PWD/.yoshida-bin/yoshida" >> "${GITHUB_ENV:-/dev/null}"
