#!/usr/bin/env bash
set -euo pipefail

IP_CIDR="${1:-192.168.10.2/24}"
GATEWAY="${2:-192.168.10.1}"
DNS="${3:-8.8.8.8 1.1.1.1}"
IFACE="${4:-eth0}"
PROFILE="otm-${IFACE}-static"

# Normalize any CRLF that sneaked in
# (harmless if already LF)
if grep -Iq . "$0"; then sed -i 's/\r$//' "$0" || true; fi

echo "Setting static IPv4 on $IFACE -> $IP_CIDR (gw $GATEWAY, dns $DNS) ..."

# Ensure NetworkManager manages the device
sudo nmcli dev set "$IFACE" managed yes || true

# Create or update profile
if nmcli -t -f NAME connection show | grep -Fxq "$PROFILE"; then
  sudo nmcli connection modify "$PROFILE" \
    ipv4.addresses "$IP_CIDR" ipv4.gateway "$GATEWAY" ipv4.dns "$DNS" \
    ipv4.method manual connection.autoconnect yes
else
  sudo nmcli connection add type ethernet ifname "$IFACE" con-name "$PROFILE" \
    ipv4.addresses "$IP_CIDR" ipv4.gateway "$GATEWAY" ipv4.dns "$DNS" \
    ipv4.method manual autoconnect yes
fi

# Bring down other active profiles on this iface
sudo nmcli -t -f NAME,TYPE,DEVICE connection show --active | \
  awk -F: -v ifc="$IFACE" '$2=="ethernet" && $3==ifc {print $1}' | \
  xargs -r -I{} sudo nmcli connection down "{}"

# Bring our profile up
sudo nmcli connection up "$PROFILE"

echo "Done."
ip addr show "$IFACE" | sed -n 's/ *inet \([0-9.\/]*\).*/Assigned: \1/p'

