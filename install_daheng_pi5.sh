#!/usr/bin/env bash
# install_daheng_pi5.sh
# One-shot installer for Daheng Galaxy SDK + Python bindings on Raspberry Pi 5
# Based on: openUC2 "Install driver for Daheng Camera" (fixed typos & unzip) :contentReference[oaicite:0]{index=0}

set -euo pipefail

# -------- Config (versions from the guide) --------
SDK_ZIP_URL="https://dahengimaging.com/downloads/Galaxy_Linux-armhf_Gige-U3_32bits-64bits_1.5.2303.9202.zip"
PY_TGZ_URL="https://dahengimaging.com/downloads/Galaxy_Linux_Python_2.0.2106.9041.tar.gz"

# -------- Preflight checks --------
if [[ $(id -u) -eq 0 ]]; then
  echo "Please don't run this script as root. It will use sudo only when needed."
  exit 1
fi

ARCH="$(uname -m)"
if [[ "$ARCH" != "aarch64" && "$ARCH" != "armv7l" && "$ARCH" != "armhf" ]]; then
  echo "Warning: Detected arch '$ARCH'. This script is intended for Raspberry Pi (arm/aarch64)."
fi

if ! command -v wget >/dev/null 2>&1; then
  echo "Installing wget..."
  sudo apt-get update -y
  sudo apt-get install -y wget
fi

# unzip & tar are needed for extraction; pip for Python package install
sudo apt-get update -y
sudo apt-get install -y unzip tar python3 python3-pip python3-venv

# -------- Paths --------
DL="$HOME/Downloads"
mkdir -p "$DL"

# -------- Download SDK & Python bindings --------
echo "Downloading Daheng Galaxy SDK zip to $DL ..."
wget -c "$SDK_ZIP_URL" -P "$DL"

echo "Downloading Daheng Galaxy Python bindings tar.gz to $DL ..."
wget -c "$PY_TGZ_URL" -P "$DL"

# -------- Extract SDK --------
SDK_ZIP="$(basename "$SDK_ZIP_URL")"
SDK_DIR_BASENAME="${SDK_ZIP%.zip}"

echo "Extracting SDK zip..."
cd "$DL"
# Unzip into a folder with the same base name (if not already)
if [[ ! -d "$SDK_DIR_BASENAME" ]]; then
  unzip -q "$SDK_ZIP" -d "$SDK_DIR_BASENAME"
fi

# Try to locate the .run installer (name per guide)
RUN_CANDIDATE_1="$DL/$SDK_DIR_BASENAME/Galaxy_camera.run"
RUN_CANDIDATE_2="$(find "$DL/$SDK_DIR_BASENAME" -maxdepth 2 -type f -name '*.run' | head -n 1)"

if [[ -f "$RUN_CANDIDATE_1" ]]; then
  GALAXY_RUN="$RUN_CANDIDATE_1"
elif [[ -n "${RUN_CANDIDATE_2:-}" ]]; then
  GALAXY_RUN="$RUN_CANDIDATE_2"
else
  echo "ERROR: Could not find Galaxy .run installer in '$DL/$SDK_DIR_BASENAME'."
  echo "Contents:"
  ls -la "$DL/$SDK_DIR_BASENAME"
  exit 1
fi

echo "Making Galaxy installer executable..."
chmod +x "$GALAXY_RUN"

echo "Running Galaxy SDK installer (you may be prompted by a TUI/CLI installer)..."
sudo "$GALAXY_RUN"

# -------- Optionally reload udev (some SDKs install rules) --------
if command -v udevadm >/dev/null 2>&1; then
  echo "Reloading udev rules (if any were installed)..."
  sudo udevadm control --reload-rules || true
  sudo udevadm trigger || true
fi

# -------- Extract & install Python bindings --------
PY_TGZ="$(basename "$PY_TGZ_URL")"
PY_DIR_BASENAME="${PY_TGZ%.tar.gz}"

echo "Extracting Python bindings..."
cd "$DL"
if [[ ! -d "$PY_DIR_BASENAME" ]]; then
  tar -xzf "$PY_TGZ"
fi

# The guide uses ~/Downloads/Galaxy_Linux_Python_.../api
PY_API_DIR="$DL/$PY_DIR_BASENAME/api"
if [[ ! -d "$PY_API_DIR" ]]; then
  echo "ERROR: Expected API directory not found: $PY_API_DIR"
  echo "Contents:"
  ls -la "$DL/$PY_DIR_BASENAME"
  exit 1
fi

# If user is inside a venv, use that pip; otherwise install --user
echo "Installing gxipy (Python API) with pip..."
if [[ -n "${VIRTUAL_ENV:-}" ]]; then
  # venv active
  python3 -m pip install -U pip
  python3 -m pip install -e "$PY_API_DIR"
else
  # no venv: install for user
  python3 -m pip install -U --user pip
  python3 -m pip install -e "$PY_API_DIR" --user
  # Ensure ~/.local/bin in PATH for user installs
  if ! grep -q '.local/bin' <<< "$PATH"; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
    export PATH="$HOME/.local/bin:$PATH"
  fi
fi

# -------- Quick smoke test path (optional) --------
SAMPLE_MONO="$DL/$PY_DIR_BASENAME/sample/GxSingleCamMono/GxSingleCamMono.py"
if [[ -f "$SAMPLE_MONO" ]]; then
  echo
  echo "Optional: You can test the camera with:"
  echo "  python3 \"$SAMPLE_MONO\""
  echo "(If you see a SyntaxWarning about 'is' vs '==', it's harmless for the demo.)"
fi

echo
echo "------------------------------------------------------------"
echo "Daheng Galaxy SDK + Python bindings installed (script fixes: unzip + 'Downloads' typo)."
echo "It is recommended to reboot before first use."
echo "To reboot now, run:  sudo reboot"
echo "------------------------------------------------------------"
