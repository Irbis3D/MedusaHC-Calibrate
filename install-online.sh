#!/usr/bin/env bash
set -euo pipefail

REPOSITORY="${MEDUSAHC_CALIBRATE_REPOSITORY:-https://github.com/Irbis3D/MedusaHC-Calibrate.git}"
REF="${MEDUSAHC_CALIBRATE_REF:-main}"
INSTALL_DIR="${MEDUSAHC_CALIBRATE_DIR:-${HOME}/medusahc-calibrate}"
ACTION="${1:-install}"
temporary=""
cleanup() {
  [[ -z "${temporary}" ]] || rm -rf -- "${temporary}"
}
trap cleanup EXIT

command -v git >/dev/null 2>&1 || { echo "git is required" >&2; exit 1; }

case "${ACTION}" in
  install)
    if [[ -e "${INSTALL_DIR}" && ! -d "${INSTALL_DIR}/.git" ]]; then
      echo "Refusing to replace non-Git path: ${INSTALL_DIR}" >&2
      exit 1
    fi
    if [[ ! -d "${INSTALL_DIR}/.git" ]]; then
      git clone --branch "${REF}" --single-branch "${REPOSITORY}" "${INSTALL_DIR}"
    fi
    ;;
  update)
    [[ -d "${INSTALL_DIR}/.git" ]] || { echo "MedusaHC-Calibrate is not installed in ${INSTALL_DIR}" >&2; exit 1; }
    [[ -z "$(git -C "${INSTALL_DIR}" status --porcelain)" ]] || { echo "The Calibrate repository has local changes; update cancelled." >&2; exit 1; }
    git -C "${INSTALL_DIR}" pull --ff-only
    ;;
  uninstall|status)
    if [[ ! -d "${INSTALL_DIR}/.git" ]]; then
      temporary="$(mktemp -d /tmp/medusahc-calibrate-command.XXXXXX)"
      git clone --quiet --depth 1 --branch "${REF}" --single-branch "${REPOSITORY}" "${temporary}/source"
    fi
    ;;
  *) echo "Usage: install-online.sh [install|update|uninstall|status]" >&2; exit 2 ;;
esac

if [[ -d "${INSTALL_DIR}/.git" ]]; then
  bash "${INSTALL_DIR}/install.sh" "$@"
elif [[ -n "${temporary}" ]]; then
  bash "${temporary}/source/install.sh" "$@"
else
  echo "MedusaHC-Calibrate checkout not found: ${INSTALL_DIR}" >&2
  exit 1
fi

if [[ "${ACTION}" == "uninstall" ]]; then
  resolved_home="$(realpath -m -- "${HOME}")"
  resolved_install="$(realpath -m -- "${INSTALL_DIR}")"
  case "${resolved_install}" in
    "${resolved_home}"/*) rm -rf -- "${resolved_install}" ;;
    *) echo "Checkout kept because it is outside HOME: ${resolved_install}" >&2 ;;
  esac
fi
