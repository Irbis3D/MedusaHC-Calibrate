#!/usr/bin/env bash
set -euo pipefail

REPOSITORY="${MEDUSAHC_CALIBRATE_REPOSITORY:-Irbis3D/MedusaHC-Calibrate}"
REF="${MEDUSAHC_CALIBRATE_REF:-main}"
PACKAGE_URL="${MEDUSAHC_CALIBRATE_PACKAGE_URL:-https://api.github.com/repos/${REPOSITORY}/tarball/${REF}}"
temporary="$(mktemp -d /tmp/medusahc-calibrate-install.XXXXXX)"
cleanup() { rm -rf -- "${temporary}"; }
trap cleanup EXIT
curl -fsSL --connect-timeout 15 --max-time 120 --retry 3 "${PACKAGE_URL}" -o "${temporary}/source.tar.gz"
mkdir -p "${temporary}/source"
tar -xzf "${temporary}/source.tar.gz" -C "${temporary}/source" --strip-components=1
if [[ "$#" == 0 ]]; then set -- install; fi
bash "${temporary}/source/install.sh" "$@"

