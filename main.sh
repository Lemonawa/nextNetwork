#!/bin/bash

set -euo pipefail

required_packages(){
    printf '%s\n' wget ca-certificates gnupg
}

sysctl_qdisc(){
    printf '%s\n' fq
}

require_root(){
    if [[ "${EUID}" -ne 0 ]]; then
        echo "Please run this script as root." >&2
        exit 1
    fi
}

select_xanmod_package(){
    local branch=""
    # XanMod only publishes LTS packages for Debian bookworm.
    if [[ "${2:-}" == "bookworm" || "$1" == "1" ]]; then
        branch="lts-"
    fi
    case "$1" in
        1) printf '%s\n' "linux-xanmod-${branch}x64v1" ;;
        2) printf '%s\n' "linux-xanmod-${branch}x64v2" ;;
        3|4) printf '%s\n' "linux-xanmod-${branch}x64v3" ;;
        *)
            echo "Unsupported x86-64 psABI level: $1" >&2
            return 1
            ;;
    esac
}

get_debian_codename(){
    local ID VERSION_CODENAME
    # shellcheck source=/dev/null
    . /etc/os-release
    if [[ "${ID:-}" != "debian" ]]; then
        echo "Only Debian GNU/Linux is supported." >&2
        return 1
    fi
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
    local -a packages
    mapfile -t packages < <(required_packages)
    apt-get update
    apt-get install -y "${packages[@]}"
    echo "System is ready"
}

write_sysctl_config(){
    if [[ -f /etc/sysctl.d/99-nextnetwork.conf ]]; then
        cp /etc/sysctl.d/99-nextnetwork.conf /etc/sysctl.d/99-nextnetwork.conf.bak
    fi
    render_sysctl_config > /etc/sysctl.d/99-nextnetwork.conf
}

finish_with_reboot_notice(){
    local answer
    echo "Completed. Reboot to activate the installed kernel and default qdisc."
    if read -r -p "Reboot now? [y/N]: " answer && [[ "$answer" =~ ^[Yy]([Ee][Ss])?$ ]]; then
        reboot
    fi
}

install_xanmod_kernel()(
    require_root
    local debian_codename kernel_package cpu_output cpu_level cpu_status=0 work_dir
    debian_codename=$(get_debian_codename)
    if [[ "$(dpkg --print-architecture)" != "amd64" ]]; then
        echo "XanMod requires the amd64 architecture." >&2
        exit 1
    fi
    prepare
    echo "Installing XanMod Kernel"
    work_dir=$(mktemp -d)
    trap 'rm -rf -- "$work_dir"' EXIT
    wget --timeout=30 --tries=3 -O "$work_dir/check_x86-64_psabi.sh" https://dl.xanmod.org/check_x86-64_psabi.sh
    # The official probe is awk, and exits with CPU level + 1 on success.
    cpu_output=$(awk -f "$work_dir/check_x86-64_psabi.sh") || cpu_status=$?
    cpu_level=$(printf '%s\n' "$cpu_output" | sed -n 's/^CPU supports x86-64-v\([1-4]\)$/\1/p')
    if [[ ! "$cpu_level" =~ ^[1-4]$ ]] || (( cpu_status != cpu_level + 1 )); then
        echo "Unable to detect x86-64 psABI level." >&2
        exit 1
    fi
    kernel_package=$(select_xanmod_package "$cpu_level" "$debian_codename")
    install -d -m 0755 /etc/apt/keyrings
    wget --timeout=30 --tries=3 -O "$work_dir/archive.key" https://dl.xanmod.org/archive.key
    gpg --batch --yes --dearmor -o "$work_dir/xanmod-archive-keyring.gpg" "$work_dir/archive.key"
    install -m 0644 "$work_dir/xanmod-archive-keyring.gpg" /etc/apt/keyrings/xanmod-archive-keyring.gpg
    write_xanmod_sources "$debian_codename"
    apt-get update
    apt-get install -y "$kernel_package"
    echo "XanMod Kernel installed."
    write_sysctl_config
    finish_with_reboot_notice
)

check_running_kernel(){
    local available qdisc
    # BBR may be built in; do not fail merely because modprobe is unavailable.
    modprobe tcp_bbr 2>/dev/null || true
    available=$(sysctl -n net.ipv4.tcp_available_congestion_control)
    if [[ " $available " != *" bbr "* ]]; then
        echo "BBR is unavailable. Boot the installed XanMod kernel first." >&2
        return 1
    fi
    if ! sysctl -n net.ipv4.tcp_collapse_max_bytes > /dev/null 2>&1; then
        echo "The Cloudflare TCP collapse patch is unavailable. Boot XanMod before applying this profile." >&2
        return 1
    fi
    qdisc=$(sysctl_qdisc)
    if ! modprobe "sch_$qdisc"; then
        echo "Unable to load $qdisc. Check the running kernel before applying tuning." >&2
        return 1
    fi
}

configure(){
    require_root
    get_debian_codename > /dev/null
    check_running_kernel
    write_sysctl_config
    # Apply only this profile, without reapplying unrelated system settings.
    sysctl -p /etc/sysctl.d/99-nextnetwork.conf
    finish_with_reboot_notice
}

main(){
    if [[ -t 1 && -n "${TERM:-}" ]]; then clear; fi
    echo "1. Install"
    echo "2. I have already installed XanMod Kernel"
    echo "0. Exit"
    read -r -p "Choose an option: " option
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
