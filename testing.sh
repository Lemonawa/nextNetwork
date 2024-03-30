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
net.ipv4.tcp_adv_win_scale = 1
net.ipv4.tcp_collapse_max_bytes = 6291456
net.ipv4.tcp_notsent_lowat = 131072

# BBR+cake
net.ipv4.tcp_congestion_control = bbr
net.core.default_qdisc = cake

# ECN, as per RFC3168
net.ipv4.tcp_ecn = 1

# TCP window scaling, as per RFC1323
net.ipv4.tcp_window_scaling = 1

# UDP
net.ipv4.udp_rmem_min=16384
net.ipv4.udp_wmem_min=16384
net.core.rmem_default=26214400
net.core.rmem_max=26214400
net.core.optmem_max=65535
net.ipv4.udp_mem=8192 262144 536870912
net.core.netdev_max_backlog=32768

# some optimization
net.ipv4.tcp_syncookies = 1
net.ipv4.tcp_tw_reuse = 1
net.ipv4.icmp_ignore_bogus_error_responses = 1
net.ipv4.icmp_echo_ignore_broadcasts = 1
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.default.accept_source_route = 0
net.ipv4.tcp_tw_recycle = 1
net.ipv4.tcp_fin_timeout = 2
net.ipv4.tcp_keepalive_time = 1200
net.ipv4.ip_local_port_range = 10000 65000
net.ipv4.tcp_max_syn_backlog = 8192
net.ipv4.tcp_max_tw_buckets = 6000
net.core.somaxconn = 32768
net.ipv4.tcp_synack_retries = 2
net.ipv4.tcp_syn_retries = 2
net.ipv4.tcp_mem = 94500000 91500000 92700000
net.ipv4.tcp_max_orphans = 3276800
net.ipv4.tcp_fin_timeout = 30
net.inet.tcp.sendspace = 65536
net.inet.tcp.recvspace = 65536
net.inet.udp.sendspace = 65535
net.inet.udp.recvspace = 65535
net.local.stream.sendspace = 65535
net.local.stream.recvspace = 65535
net.inet.tcp.rfc1323 = 1
net.inet.tcp.rfc1644 = 1
net.inet.tcp.rfc3042 = 1
net.inet.tcp.rfc3390 = 1
kern.ipc.maxsockbuf = 2097152
kern.maxfiles = 65536
kern.maxfilesperproc = 32768
net.inet.tcp.delayed_ack = 0
net.inet.icmp.drop_redirect = 1
net.inet.icmp.log_redirect = 1
net.inet.ip.redirect = 0
net.inet6.ip6.redirect = 0
net.inet.icmp.bmcastecho = 0
net.inet.icmp.maskrepl = 0
net.inet.icmp.icmplim = 100
net.inet.tcp.always_keepalive = 1
net.inet.ip.intr_queue_maxlen = 1000
net.inet.tcp.blackhole = 2
net.inet.udp.blackhole = 1
net.inet.tcp.inflight.enable = 1
net.inet.ip.fastforwarding = 0
kern.ipc.somaxconn = 2048
net.inet.udp.checksum = 1
net.inet.tcp.syncookies = 1
net.local.stream.recvspace = 65536
net.local.dgram.maxdgram = 16384
net.local.dgram.recvspace = 65536
net.inet.tcp.mssdflt = 1460
net.inet.tcp.inflight_enable = 1
net.inet.tcp.minmss = 1460
net.inet.raw.maxdgram = 65536
net.inet.raw.recvspace = 16384

EOF
    sysctl -p
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