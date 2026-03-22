#!/bin/bash

set -euo pipefail

required_packages(){
    printf '%s\n' wget ca-certificates gnupg
}

sysctl_qdisc(){
    printf '%s\n' cake
}

require_root(){
    if [[ "${EUID}" -ne 0 ]]; then
        echo "Please run this script as root." >&2
        exit 1
    fi
}

select_xanmod_package(){
    case "$1" in
        1) printf '%s\n' "linux-xanmod-lts-x64v1" ;;
        2) printf '%s\n' "linux-xanmod-x64v2" ;;
        3|4) printf '%s\n' "linux-xanmod-x64v3" ;;
        *)
            echo "Unsupported x86-64 psABI level: $1" >&2
            return 1
            ;;
    esac
}

get_debian_codename(){
    . /etc/os-release
    if [[ -z "${VERSION_CODENAME:-}" ]]; then
        echo "Unable to detect Debian codename." >&2
        return 1
    fi

    printf '%s\n' "$VERSION_CODENAME"
}

render_xanmod_sources(){
    cat <<EOF
Types: deb
URIs: http://deb.xanmod.org/
Suites: $1
Components: main
Signed-By: /etc/apt/keyrings/xanmod-archive-keyring.gpg
EOF
}

write_xanmod_sources(){
    render_xanmod_sources "$1" > /etc/apt/sources.list.d/xanmod-release.sources
}

render_sysctl_config(){
    cat <<EOF
# Enable forwarding first because toggling ip_forward resets IPv4 sysctls.
net.ipv4.ip_forward = 1

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
net.ipv4.tcp_fastopen = 3
net.ipv4.tcp_mtu_probing = 1
net.ipv4.tcp_slow_start_after_idle = 0
net.ipv4.tcp_keepalive_time = 600
net.ipv4.tcp_keepalive_intvl = 60
net.ipv4.tcp_keepalive_probes = 3
net.ipv4.tcp_syncookies = 1

# BBR+$(sysctl_qdisc)
net.ipv4.tcp_congestion_control = bbr
net.core.default_qdisc = $(sysctl_qdisc)

# ECN: accept it on incoming connections without requesting it on outbound SYNs.
net.ipv4.tcp_ecn = 2

# TCP window scaling, as per RFC1323
net.ipv4.tcp_window_scaling = 1
EOF
}

prepare(){
    require_root
    echo "Preparing the system"
    apt update
    apt install -y $(required_packages)
    echo "System is ready"
}

write_sysctl_config(){
    if [[ -f /etc/sysctl.d/99-nextnetwork.conf ]]; then
        cp /etc/sysctl.d/99-nextnetwork.conf /etc/sysctl.d/99-nextnetwork.conf.bak
    fi
    render_sysctl_config > /etc/sysctl.d/99-nextnetwork.conf
}

finish_with_reboot_notice(){
    clear
    echo "Completed. Reboot the system to take effect."
    read -p "Press any key to continue..."
    reboot
}

install_xanmod_kernel(){
    prepare
    echo "Installing XanMod Kernel"
    wget -O check_x86-64_psabi.sh https://dl.xanmod.org/check_x86-64_psabi.sh -U "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0"
    chmod +x check_x86-64_psabi.sh
    cpu_output=$(./check_x86-64_psabi.sh || true)
    cpu_level=$(printf '%s\n' "$cpu_output" | awk -F 'v' '/x86-64-v/ {print $2}')
    if [[ -z "${cpu_level}" ]]; then
        echo "Unable to detect x86-64 psABI level."
        exit 1
    fi
    rm check_x86-64_psabi.sh
    kernel_package=$(select_xanmod_package "$cpu_level")
    debian_codename=$(get_debian_codename)
    mkdir -p /etc/apt/keyrings
    wget -qO - https://dl.xanmod.org/archive.key -U "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0" | gpg --dearmor -o /etc/apt/keyrings/xanmod-archive-keyring.gpg
    write_xanmod_sources "$debian_codename"
    apt update
    apt install "$kernel_package" -y
    echo "XanMod Kernel installed."
    write_sysctl_config
    finish_with_reboot_notice
}

configure(){
    require_root
    write_sysctl_config
    sysctl --system
    finish_with_reboot_notice
}

main(){
    clear
    echo "1. Install and configure"
    echo "2. I have already installed XanMod Kernel"
    echo "0. Exit"
    read -p "Choose an option: " option
    case $option in
        1) install_xanmod_kernel ;;
        2) configure ;;
        0) exit ;;
        *) 
            echo -e "Invalid option" 
            exit 1
            ;;
    esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main
fi
