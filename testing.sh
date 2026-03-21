#!/bin/bash

set -euo pipefail

prepare(){
    echo "Preparing the system"
    apt update
    apt install -y wget gnupg gnupg2 gnupg1 sudo
    echo "System is ready"
}

install_xanmod_edge_kernel(){
    prepare
    echo "Installing XanMod Edge Kernel"
    wget -O check_x86-64_psabi.sh https://dl.xanmod.org/check_x86-64_psabi.sh -U "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0"
    chmod +x check_x86-64_psabi.sh
    cpu_output=$(./check_x86-64_psabi.sh || true)
    cpu_level=$(printf '%s\n' "$cpu_output" | awk -F 'v' '/x86-64-v/ {print $2}')
    if [[ -z "${cpu_level}" ]]; then
        echo "Unable to detect x86-64 psABI level."
        exit 1
    fi
    rm check_x86-64_psabi.sh
    wget -qO - https://dl.xanmod.org/archive.key -U "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0" | sudo gpg --dearmor -o /usr/share/keyrings/xanmod-archive-keyring.gpg
    cat <<'EOF' > /etc/apt/sources.list.d/xanmod-release.sources
Types: deb
URIs: http://deb.xanmod.org/
Suites: releases
Components: main
Signed-By: /usr/share/keyrings/xanmod-archive-keyring.gpg
EOF
    apt update
    if [[ "${cpu_level}" == "4" ]]; then
      apt update && apt install linux-xanmod-edge-x64v4 -y
    elif [[ "${cpu_level}" == "3" ]]; then
      apt update && apt install linux-xanmod-edge-x64v3 -y
    elif [[ "${cpu_level}" == "2" ]]; then
      apt update && apt install linux-xanmod-edge-x64v2 -y
    else
      apt update && apt install linux-xanmod-edge-x64v1 -y
    fi
    echo "XanMod Edge Kernel installed."
    configure
}

configure(){
    if [[ -f /etc/sysctl.d/99-nextnetwork.conf ]]; then
        cp /etc/sysctl.d/99-nextnetwork.conf /etc/sysctl.d/99-nextnetwork.conf.bak
    fi
    cat <<'EOF' > /etc/sysctl.d/99-nextnetwork.conf
# https://blog.cloudflare.com/optimizing-tcp-for-high-throughput-and-low-latency
net.ipv4.tcp_rmem = 8192 262144 536870912
net.ipv4.tcp_wmem = 4096 16384 536870912
net.ipv4.tcp_adv_win_scale = -2
net.ipv4.tcp_collapse_max_bytes = 6291456
net.ipv4.tcp_notsent_lowat = 131072

# Connection handling for relay and egress servers
net.core.somaxconn = 4096
net.core.netdev_max_backlog = 16384
net.ipv4.tcp_max_syn_backlog = 8192
net.ipv4.ip_local_port_range = 10240 65535
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fastopen = 3
net.ipv4.tcp_mtu_probing = 1
net.ipv4.tcp_slow_start_after_idle = 0
net.ipv4.tcp_keepalive_time = 600
net.ipv4.tcp_keepalive_intvl = 60
net.ipv4.tcp_keepalive_probes = 3
net.ipv4.tcp_syncookies = 1
net.ipv4.ip_forward = 1

# BBR+cake
net.ipv4.tcp_congestion_control = bbr
net.core.default_qdisc = cake

# ECN, as per RFC3168
net.ipv4.tcp_ecn = 1

# TCP window scaling, as per RFC1323
net.ipv4.tcp_window_scaling = 1
EOF
    sysctl --system
    clear
    echo "Completed. Reboot the system to take effect."
    read -p "Press any key to continue..."
    reboot
}

main(){
    clear
    echo "1. Install and configure"
    echo "2. I have already installed XanMod Edge Kernel"
    echo "0. Exit"
    read -p "Choose an option: " option
    case $option in
        1) install_xanmod_edge_kernel ;;
        2) configure ;;
        0) exit ;;
        *) 
            echo -e "Invalid option" 
            exit 1
            ;;
    esac
}
main
