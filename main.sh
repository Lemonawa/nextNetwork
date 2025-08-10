#!/bin/bash

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
    cpu_level=$(./check_x86-64_psabi.sh | awk -F 'v' '{print $2}')
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
    cp /etc/sysctl.d/99-nextnetwork.conf /etc/sysctl.d/99-nextnetwork.conf.bak # backup
    cat <<'EOF' > /etc/sysctl.d/99-nextnetwork.conf
# -------------------------------
# TCP Congestion Control & Queueing
# -------------------------------
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr

# -------------------------------
# Increase buffer sizes for high throughput
# -------------------------------
net.core.rmem_max = 67108864
net.core.wmem_max = 67108864
net.ipv4.tcp_rmem = 4096 87380 67108864
net.ipv4.tcp_wmem = 4096 65536 67108864
net.core.optmem_max = 65536

# -------------------------------
# TCP performance tuning
# -------------------------------
net.ipv4.tcp_mtu_probing = 1
net.ipv4.tcp_slow_start_after_idle = 0
net.ipv4.tcp_fastopen = 3
net.ipv4.tcp_window_scaling = 1
net.ipv4.tcp_timestamps = 1
net.ipv4.tcp_sack = 1
net.ipv4.tcp_no_metrics_save = 1
net.ipv4.tcp_low_latency = 1
net.ipv4.tcp_adv_win_scale = -2

# -------------------------------
# Reduce latency in queuing
# -------------------------------
net.core.netdev_max_backlog = 16384
net.ipv4.tcp_max_syn_backlog = 8192
net.ipv4.tcp_fin_timeout = 10

# -------------------------------
# Enable reuse of TIME_WAIT sockets for fast reconnects
# -------------------------------
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_tw_recycle = 0

# -------------------------------
# UDP buffer tuning
# -------------------------------
net.ipv4.udp_rmem_min = 4096
net.ipv4.udp_wmem_min = 4096
EOF
    sysctl --system
    clear
    echo "Completed. Reboot the system to take effect."
    read -p "Press any key to continue..."
    reboot
}

main(){
    clear
    echo "1. Install"
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
