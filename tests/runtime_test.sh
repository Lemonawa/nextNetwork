#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."

for script in main.sh testing.sh; do
    # Run checks in child shells so errexit remains active in the tested path.
    bash -s -- "$script" <<'TEST'
set -euo pipefail
source "$1"
require_root(){ :; }
get_debian_codename(){ echo trixie; }
check_running_kernel(){ :; }
write_sysctl_config(){ echo write; }
sysctl(){ printf 'sysctl %s\n' "$*"; }
finish_with_reboot_notice(){ echo finish; }
expected=$'write\nsysctl -p /etc/sysctl.d/99-nextnetwork.conf\nfinish'
[[ "$(configure)" == "$expected" ]]
TEST
    if bash -s -- "$script" <<'TEST'
set -euo pipefail
source "$1"
require_root(){ :; }
get_debian_codename(){ echo trixie; }
check_running_kernel(){ return 1; }
write_sysctl_config(){ echo 'ERROR: config written before preflight' >&2; exit 99; }
configure
TEST
    then
        echo 'Missing kernel did not stop configuration' >&2
        exit 1
    else
        [[ "$?" == 1 ]]
    fi
    for reply in n '' yes; do
        result=$(bash -s -- "$script" "$reply" <<'TEST'
set -euo pipefail
source "$1"
reboot(){ echo REBOOT_CALLED; }
finish_with_reboot_notice <<< "$2"
TEST
)
        if [[ "$reply" == yes ]]; then
            [[ "$result" == *REBOOT_CALLED* ]]
        else
            [[ "$result" != *REBOOT_CALLED* ]]
        fi
    done
    result=$(bash -s -- "$script" <<'TEST'
set -euo pipefail
source "$1"
reboot(){ echo REBOOT_CALLED; }
finish_with_reboot_notice < /dev/null
TEST
)
    [[ "$result" != *REBOOT_CALLED* ]]
    for available in 'reno cubic' 'reno bbr cubic'; do
        if bash -s -- "$script" "$available" <<'TEST'
set -euo pipefail
source "$1"
AVAILABLE="$2"
sysctl(){ echo "$AVAILABLE"; }
modprobe(){ :; }
check_running_kernel
TEST
        then
            [[ "$available" == *bbr* ]]
        else
            [[ "$available" != *bbr* ]]
        fi
    done
    if bash -s -- "$script" <<'TEST'
set -euo pipefail
source "$1"
sysctl(){
    if [[ "$*" == '-n net.ipv4.tcp_available_congestion_control' ]]; then
        echo 'reno bbr cubic'
    else
        return 1
    fi
}
modprobe(){ :; }
check_running_kernel
TEST
    then
        echo 'Missing Cloudflare patch was accepted' >&2
        exit 1
    fi
done
printf 'runtime preflight, scoped sysctl apply and reboot confirmation ok\n'
