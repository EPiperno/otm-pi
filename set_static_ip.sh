#!/usr/bin/env bash
CONN_NAME="Wired connection 1"
IP="192.168.10.2/24"
GW="192.168.10.1"
DNS="8.8.8.8"

sudo nmcli connection modify "$CONN_NAME" ipv4.addresses $IP
sudo nmcli connection modify "$CONN_NAME" ipv4.gateway $GW
sudo nmcli connection modify "$CONN_NAME" ipv4.dns $DNS
sudo nmcli connection modify "$CONN_NAME" ipv4.method manual

sudo nmcli connection down "$CONN_NAME"
sudo nmcli connection up "$CONN_NAME"

ip addr show eth0
