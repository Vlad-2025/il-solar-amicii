#!/usr/bin/env bash
# install.sh: developer setup for the Prosumer Bill & Solar Assistant.
#
# Installs everything the handoff doc uses:
#   git, GitHub CLI, curl, jq, build tools, Python 3 + venv,
#   Tesseract OCR + Romanian language pack, Poppler, OpenCV runtime libraries,
#   PostgreSQL client (psql), Docker Engine + Compose,
#   and the Python packages (streamlit, pvlib, pandas, scikit-learn, pdfplumber, ...).
#   Optional: Node.js, adb, JDK 17, FastAPI (--mobile) and the Android SDK (--android-sdk).
#
# Supported: Ubuntu, Debian, Linux Mint, Pop!_OS (apt) · Fedora (dnf) · Arch, Manjaro (pacman)
# Run it as your normal user from the repo root; it calls sudo when needed.

set -euo pipefail

NODE_MAJOR="${NODE_MAJOR:-22}"
VENV_DIR="${VENV_DIR:-.venv}"
ANDROID_HOME="${ANDROID_HOME:-$HOME/Android/Sdk}"
ANDROID_CMDLINE_ZIP="${ANDROID_CMDLINE_ZIP:-commandlinetools-linux-11076708_latest.zip}"
ANDROID_PLATFORM="${ANDROID_PLATFORM:-android-35}"
ANDROID_BUILD_TOOLS="${ANDROID_BUILD_TOOLS:-35.0.0}"

WITH_MOBILE=0
WITH_ANDROID_SDK=0
WITH_DOCKER=1
WITH_PYTHON=1

usage() {
  cat <<EOF
Usage: ./install.sh [options]

  (no options)    System packages, OCR + Romanian, psql, GitHub CLI, Docker,
                  Python virtualenv + requirements.txt
  --mobile        Also Node.js ${NODE_MAJOR}.x, adb, JDK 17 and FastAPI (Expo app + API)
  --android-sdk   Also the Android SDK for local APK builds (implies --mobile)
  --no-docker     Skip Docker
  --no-python     Skip the Python virtualenv and pip packages
  -h, --help      Show this help

Environment overrides: NODE_MAJOR, VENV_DIR, ANDROID_HOME, ANDROID_PLATFORM, ANDROID_BUILD_TOOLS
EOF
}

for arg in "$@"; do
  case "$arg" in
    --mobile) WITH_MOBILE=1 ;;
    --android-sdk) WITH_MOBILE=1; WITH_ANDROID_SDK=1 ;;
    --no-docker) WITH_DOCKER=0 ;;
    --no-python) WITH_PYTHON=0 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; usage; exit 1 ;;
  esac
done

log()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m   ok: %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m   !! %s\033[0m\n' "$*" >&2; }
have() { command -v "$1" >/dev/null 2>&1; }
as_root() { if [ "$(id -u)" -eq 0 ]; then "$@"; else sudo "$@"; fi; }

if [ "$(id -u)" -eq 0 ] && [ -n "${SUDO_USER:-}" ]; then
  echo "Run this as your normal user (without sudo); it asks for sudo itself." >&2
  exit 1
fi
TARGET_USER="$(id -un)"

# ---------------------------------------------------------------- distro detection
OS_ID="unknown"; OS_LIKE=""; OS_CODENAME=""; OS_UBUNTU_CODENAME=""
if [ -r /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  OS_ID="${ID:-unknown}"
  OS_LIKE="${ID_LIKE:-}"
  OS_CODENAME="${VERSION_CODENAME:-}"
  OS_UBUNTU_CODENAME="${UBUNTU_CODENAME:-}"
fi

if have apt-get; then PM=apt
elif have dnf; then PM=dnf
elif have pacman; then PM=pacman
else
  echo "No supported package manager found (apt, dnf or pacman)." >&2
  exit 1
fi

pm_update() {
  case "$PM" in
    apt)    as_root apt-get update -y ;;
    dnf)    as_root dnf makecache -y ;;
    pacman) as_root pacman -Syu --noconfirm ;;   # Arch: always full upgrade, never -Sy alone
  esac
}

pm_install() {
  case "$PM" in
    apt)    as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y "$@" ;;
    dnf)    as_root dnf install -y "$@" ;;
    pacman) as_root pacman -S --needed --noconfirm "$@" ;;
  esac
}

# Install the first package name that exists (names differ between releases).
pm_install_any() {
  local p
  for p in "$@"; do
    if pm_install "$p" >/dev/null 2>&1; then ok "$p"; return 0; fi
  done
  warn "could not install any of: $*"
}

add_profile_line() {
  local line="$1" rc
  for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
    if [ -f "$rc" ] || [ "$rc" = "$HOME/.bashrc" ]; then
      grep -qxF "$line" "$rc" 2>/dev/null || echo "$line" >> "$rc"
    fi
  done
}

# ---------------------------------------------------------------- system packages
install_system_packages() {
  local base py ocr_core pg
  case "$PM" in
    apt)
      base=(git curl wget ca-certificates gnupg build-essential unzip jq)
      py=(python3 python3-venv python3-pip python3-dev)
      ocr_core=(tesseract-ocr poppler-utils)
      pg=(postgresql-client) ;;
    dnf)
      base=(git curl wget ca-certificates gnupg2 gcc gcc-c++ make unzip jq)
      py=(python3 python3-pip python3-devel)
      ocr_core=(tesseract poppler-utils)
      pg=(postgresql) ;;
    pacman)
      base=(git curl wget ca-certificates gnupg base-devel unzip jq)
      py=(python python-pip)
      ocr_core=(tesseract poppler)
      pg=(postgresql) ;;
  esac

  log "Base tools, Python, Tesseract, Poppler, psql"
  pm_install "${base[@]}" "${py[@]}" "${ocr_core[@]}" "${pg[@]}"

  log "Tesseract language packs (English + Romanian)"
  case "$PM" in
    apt)    pm_install_any tesseract-ocr-eng; pm_install_any tesseract-ocr-ron ;;
    dnf)    pm_install_any tesseract-langpack-eng tesseract-tessdata-eng; pm_install_any tesseract-langpack-ron ;;
    pacman) pm_install_any tesseract-data-eng; pm_install_any tesseract-data-ron ;;
  esac

  log "OpenCV runtime libraries"
  case "$PM" in
    apt)    pm_install_any libglib2.0-0t64 libglib2.0-0; pm_install_any libgl1 ;;
    dnf)    pm_install_any glib2; pm_install_any mesa-libGL ;;
    pacman) pm_install_any glib2; pm_install_any mesa ;;
  esac
}

# ---------------------------------------------------------------- GitHub CLI
install_gh() {
  if have gh; then ok "GitHub CLI already installed"; return; fi
  log "GitHub CLI"
  case "$PM" in
    apt)
      as_root install -m 0755 -d /etc/apt/keyrings
      curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        | as_root tee /etc/apt/keyrings/githubcli-archive-keyring.gpg >/dev/null
      as_root chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
      echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        | as_root tee /etc/apt/sources.list.d/github-cli.list >/dev/null
      as_root apt-get update -y
      pm_install gh ;;
    dnf)    pm_install gh ;;
    pacman) pm_install github-cli ;;
  esac
}

# ---------------------------------------------------------------- Docker
install_docker_apt_official() {
  local dist codename
  if [ "$OS_ID" = ubuntu ] || [[ "$OS_LIKE" == *ubuntu* ]]; then
    dist=ubuntu; codename="${OS_UBUNTU_CODENAME:-$OS_CODENAME}"
  else
    dist=debian; codename="$OS_CODENAME"
  fi
  [ -n "$codename" ] || return 1
  as_root install -m 0755 -d /etc/apt/keyrings
  curl -fsSL "https://download.docker.com/linux/$dist/gpg" | as_root tee /etc/apt/keyrings/docker.asc >/dev/null
  as_root chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/$dist $codename stable" \
    | as_root tee /etc/apt/sources.list.d/docker.list >/dev/null
  as_root apt-get update -y
  pm_install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
}

install_docker() {
  if have docker && docker compose version >/dev/null 2>&1; then
    ok "Docker and Compose already installed"
    return
  fi
  log "Docker Engine + Compose"
  if have docker; then
    # Docker is there but Compose v2 is missing: add only the plugin.
    pm_install_any docker-compose-plugin docker-compose-v2 docker-compose
  else
    case "$PM" in
      apt)
        if ! install_docker_apt_official; then
          warn "Docker's apt repo failed; using the distro packages instead"
          as_root rm -f /etc/apt/sources.list.d/docker.list
          as_root apt-get update -y
          pm_install docker.io
          pm_install_any docker-compose-v2 docker-compose-plugin docker-compose
        fi ;;
      dnf)    pm_install moby-engine docker-compose || pm_install docker docker-compose ;;
      pacman) pm_install docker docker-compose ;;
    esac
  fi

  if have systemctl && [ -d /run/systemd/system ]; then
    as_root systemctl enable --now docker || warn "could not start the Docker service"
  else
    warn "systemd not running (WSL?): start Docker with 'sudo service docker start'"
  fi
  if ! id -nG "$TARGET_USER" | grep -qw docker; then
    as_root usermod -aG docker "$TARGET_USER"
    DOCKER_GROUP_ADDED=1
  fi
}

# ---------------------------------------------------------------- mobile tooling
install_node() {
  if have node && [ "$(node -v | sed 's/^v//; s/\..*//')" -ge 20 ]; then
    ok "Node.js $(node -v) already installed"
    return
  fi
  log "Node.js"
  case "$PM" in
    apt)
      curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | as_root bash -
      pm_install nodejs ;;
    dnf)    pm_install nodejs npm ;;
    pacman) pm_install nodejs npm ;;
  esac
}

install_mobile() {
  install_node
  log "adb and JDK 17 (Expo / Android builds)"
  case "$PM" in
    apt)    pm_install_any adb android-tools-adb; pm_install_any openjdk-17-jdk ;;
    dnf)    pm_install_any android-tools; pm_install_any java-17-openjdk-devel java-21-openjdk-devel ;;
    pacman) pm_install_any android-tools; pm_install_any jdk17-openjdk ;;
  esac
}

install_android_sdk() {
  local tools="$ANDROID_HOME/cmdline-tools/latest" tmp
  log "Android SDK in $ANDROID_HOME"
  if [ ! -x "$tools/bin/sdkmanager" ]; then
    tmp="$(mktemp -d)"
    curl -fL "https://dl.google.com/android/repository/$ANDROID_CMDLINE_ZIP" -o "$tmp/tools.zip"
    unzip -q "$tmp/tools.zip" -d "$tmp"
    mkdir -p "$ANDROID_HOME/cmdline-tools"
    rm -rf "$tools"
    mv "$tmp/cmdline-tools" "$tools"
    rm -rf "$tmp"
  fi
  export ANDROID_HOME
  export PATH="$tools/bin:$ANDROID_HOME/platform-tools:$PATH"
  yes | sdkmanager --licenses >/dev/null 2>&1 || true
  sdkmanager "cmdline-tools;latest" "platform-tools" "platforms;$ANDROID_PLATFORM" "build-tools;$ANDROID_BUILD_TOOLS"
  add_profile_line "export ANDROID_HOME=\"$ANDROID_HOME\""
  add_profile_line "export PATH=\"\$ANDROID_HOME/cmdline-tools/latest/bin:\$ANDROID_HOME/platform-tools:\$PATH\""
}

# ---------------------------------------------------------------- Python packages
write_default_requirements() {
  cat > requirements.txt <<'EOF'
streamlit
pvlib
pandas
scikit-learn
pdfplumber
pypdfium2
pytesseract
opencv-python-headless
stripe
supabase
holidays
requests
pyyaml
EOF
}

setup_python() {
  log "Python virtualenv ($VENV_DIR) and packages"
  if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    warn "Python $(python3 -V 2>&1) is older than 3.10; some packages may fail"
  fi
  if [ ! -f requirements.txt ]; then
    if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      warn "no requirements.txt: writing the list from the handoff doc"
      write_default_requirements
    else
      warn "not inside the repo and no requirements.txt here: skipping pip packages"
      warn "clone the repo, cd into it and run ./install.sh again"
      return
    fi
  fi
  if [ ! -f packages.txt ]; then
    printf '%s\n' tesseract-ocr tesseract-ocr-ron poppler-utils > packages.txt   # Streamlit Cloud apt list
  fi

  python3 -m venv "$VENV_DIR"
  "$VENV_DIR/bin/python" -m pip install --upgrade pip wheel
  "$VENV_DIR/bin/pip" install -r requirements.txt
  "$VENV_DIR/bin/pip" install pytest ruff
  if [ "$WITH_MOBILE" -eq 1 ]; then
    "$VENV_DIR/bin/pip" install fastapi "uvicorn[standard]" python-multipart
  fi
  PYTHON_DONE=1
}

# ---------------------------------------------------------------- summary
version_of() {
  case "$1" in
    pdftoppm) pdftoppm -v 2>&1 | head -n1 ;;
    java)     java -version 2>&1 | grep -v '^Picked up' | head -n1 ;;
    *)        "$1" --version 2>&1 | head -n1 ;;
  esac
}

summary() {
  local c
  log "Installed"
  for c in git gh python3 tesseract pdftoppm psql docker node npm adb java; do
    if have "$c"; then printf '   %-10s %s\n' "$c" "$(version_of "$c" || true)"; fi
  done
  if have docker; then printf '   %-10s %s\n' "compose" "$(docker compose version 2>/dev/null || echo 'not found')"; fi

  if tesseract --list-langs 2>/dev/null | grep -qx ron; then ok "Tesseract Romanian (ron) available"
  else warn "Tesseract Romanian (ron) language data missing"; fi

  if [ "${PYTHON_DONE:-0}" -eq 1 ]; then
    if "$VENV_DIR/bin/python" -c "import streamlit, pvlib, pandas, sklearn, pdfplumber, pypdfium2, pytesseract, cv2, stripe, supabase, holidays, yaml" 2>/dev/null; then
      ok "Python packages import cleanly"
    else
      warn "some Python packages failed to import; check the pip output above"
    fi
  fi

  log "Next steps"
  [ "${DOCKER_GROUP_ADDED:-0}" -eq 1 ] && echo "   - Log out and back in (or run 'newgrp docker') so docker works without sudo"
  echo "   - gh auth login"
  [ "${PYTHON_DONE:-0}" -eq 1 ] && echo "   - source $VENV_DIR/bin/activate && streamlit run app/Home.py"
  [ "$WITH_DOCKER" -eq 1 ] && echo "   - docker compose up -d   (local Postgres, once docker-compose.yml exists)"
  [ "$WITH_ANDROID_SDK" -eq 1 ] && echo "   - Open a new terminal so ANDROID_HOME is set"
  echo "   - On each Android phone: install the ntfy app and subscribe to your topic"
}

# ---------------------------------------------------------------- main
log "Detected: ${PRETTY_NAME:-$OS_ID} (package manager: $PM)"
pm_update
install_system_packages
install_gh
# Plain if-blocks (not "&&") so errors inside each step still stop the script.
if [ "$WITH_DOCKER" -eq 1 ]; then install_docker; fi
if [ "$WITH_MOBILE" -eq 1 ]; then install_mobile; fi
if [ "$WITH_ANDROID_SDK" -eq 1 ]; then install_android_sdk; fi
if [ "$WITH_PYTHON" -eq 1 ]; then setup_python; fi
summary
