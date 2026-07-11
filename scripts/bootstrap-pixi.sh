#!/usr/bin/env bash

set -euo pipefail

readonly PIXI_VERSION="${PIXI_VERSION:-0.72.2}"
readonly PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly INSTALL_DIR="${PROJECT_ROOT}/.tools/bin"
readonly PIXI_BIN="${INSTALL_DIR}/pixi"
readonly TARGET="aarch64-apple-darwin"
readonly DOWNLOAD_URL="https://github.com/prefix-dev/pixi/releases/download/v${PIXI_VERSION}/pixi-${TARGET}.tar.gz"

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
    echo "This bootstrap script currently supports Apple Silicon macOS only." >&2
    exit 1
fi

if [[ -x "${PIXI_BIN}" ]] && [[ "$("${PIXI_BIN}" --version)" == "pixi ${PIXI_VERSION}" ]]; then
    echo "Pixi ${PIXI_VERSION} is already installed at ${PIXI_BIN}."
    exit 0
fi

temporary_directory="$(mktemp -d)"
trap 'rm -rf "${temporary_directory}"' EXIT

echo "Downloading Pixi ${PIXI_VERSION} for ${TARGET}."
curl --fail --location --silent --show-error \
    "${DOWNLOAD_URL}" \
    --output "${temporary_directory}/pixi.tar.gz"
tar -xzf "${temporary_directory}/pixi.tar.gz" -C "${temporary_directory}"

mkdir -p "${INSTALL_DIR}"
install -m 0755 "${temporary_directory}/pixi" "${PIXI_BIN}"

echo "Installed Pixi ${PIXI_VERSION} at ${PIXI_BIN}."
