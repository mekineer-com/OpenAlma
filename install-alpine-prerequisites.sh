#!/bin/sh
set -eu

. /etc/os-release
[ "$ID" = alpine ] || { echo "OpenAlma automatic setup currently supports Alpine 3.23." >&2; exit 1; }
case "$VERSION_ID" in 3.23|3.23.*) ;; *) echo "OpenAlma automatic setup currently supports Alpine 3.23." >&2; exit 1 ;; esac
[ "$(uname -m)" = x86_64 ] || {
    echo "OpenAlma automatic setup currently supports x86_64 hosts." >&2
    exit 1
}

if [ "$(id -u)" -ne 0 ]; then
    command -v doas >/dev/null 2>&1 || { echo "Run this installer as root (doas is unavailable)." >&2; exit 1; }
    exec doas "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/$(basename -- "$0")" "$@"
fi

apk add --no-cache \
    build-base ca-certificates curl git nginx nodejs npm sqlite-dev unzip wireguard-tools

bun_version=1.3.14
bun_sha256=14bd9aedeebf1dba67e8def9531c89bc989ecfdf1de42e5bfcaf1b8cd9294719
if [ "$(bun --version 2>/dev/null || true)" != "$bun_version" ]; then
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT HUP INT TERM
    archive="$tmp/bun.zip"
    curl -fsSL "https://github.com/oven-sh/bun/releases/download/bun-v$bun_version/bun-linux-x64-musl.zip" -o "$archive"
    printf '%s  %s\n' "$bun_sha256" "$archive" | sha256sum -c -
    unzip -q "$archive" -d "$tmp"
    install -m 0755 "$tmp/bun-linux-x64-musl/bun" /usr/local/bin/bun
fi

[ "$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')" = 3.12 ]
case "$(node --version)" in v20.*|v22.*|v24.*|v25.*) ;; *) echo "Unsupported Node.js version." >&2; exit 1 ;; esac
[ "$(bun --version)" = "$bun_version" ]
printf 'OpenAlma prerequisites ready.\n'
