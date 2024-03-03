#!/bin/bash

prepare(){
    echo "Preparing the system"
    apt update
    apt install -y wget
    echo "System is ready"
}

install_xanmod_edge_kernel(){
    prepare
    echo "Installing XanMod Edge Kernel"
    wget -O check_x86-64_psabi.sh https://dl.xanmod.org/check_x86-64_psabi.sh
    chmod +x check_x86-64_psabi.sh
    cpu_level=$(./check_x86-64_psabi.sh | awk -F 'v' '{print $2}')
    rm check_x86-64_psabi.sh
    wget -qO - https://dl.xanmod.org/archive.key | sudo gpg --dearmor -o /usr/share/keyrings/xanmod-archive-keyring.gpg
    echo 'deb [signed-by=/usr/share/keyrings/xanmod-archive-keyring.gpg] http://deb.xanmod.org releases main' | sudo tee /etc/apt/sources.list.d/xanmod-release.list
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
    cp /etc/sysctl.conf /etc/sysctl.conf.bak # backup
    echo 'precedence  ::ffff:0:0/96   100' | sudo tee -a /etc/gai.conf # prefer ipv4
    cat <<'EOF' > /etc/sysctl.conf
# https://blog.cloudflare.com/optimizing-tcp-for-high-throughput-and-low-latency
net.ipv4.tcp_rmem = 8192 262144 536870912
net.ipv4.tcp_wmem = 8192 262144 536870912
net.ipv4.tcp_adv_win_scale = -2
net.ipv4.tcp_collapse_max_bytes = 6291456
net.ipv4.tcp_notsent_lowat = 131072

# BBR+fq
net.ipv4.tcp_congestion_control = bbr
net.core.default_qdisc = fq

# ECN, as per RFC3168
net.ipv4.tcp_ecn = 1

# TCP window scaling, as per RFC1323
net.ipv4.tcp_window_scaling = 1

EOF
    sysctl -p
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