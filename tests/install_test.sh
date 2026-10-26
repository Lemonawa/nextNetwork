#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Exercise installer control flow with real temporary files and the actual awk
# probe invocation, but mock every package/system write and all downloads.
mock_install(){
    bash -s -- "$@" <<'TEST'
set -euo pipefail
source "$1"
CPU_LEVEL="$2"
CPU_STATUS="$3"
ARCH="$4"
CODENAME="$5"
require_root(){ :; }
get_debian_codename(){ echo "$CODENAME"; }
dpkg(){ echo "$ARCH"; }
prepare(){ echo PREPARE; }
wget(){
    [[ "$1" == --timeout=30 && "$2" == --tries=3 && "$3" == -O ]]
    local target="$4" url="$5"
    case "$url" in
        */check_x86-64_psabi.sh)
            printf 'BEGIN { print "CPU supports x86-64-v%s"; exit %s }\n' "$CPU_LEVEL" "$CPU_STATUS" > "$target"
            ;;
        */archive.key) echo key > "$target" ;;
        *) return 1 ;;
    esac
}
gpg(){
    [[ "$1 $2 $3 $4" == '--batch --yes --dearmor -o' ]]
    [[ -s "$6" ]]
    echo keyring > "$5"
}
install(){
    case "$*" in
        '-d -m 0755 /etc/apt/keyrings') : ;;
        '-m 0644 '*'/etc/apt/keyrings/xanmod-archive-keyring.gpg')
            [[ -s "$3" ]]
            ;;
        *) return 1 ;;
    esac
}
write_xanmod_sources(){ echo "SUITE:$1"; }
apt-get(){ printf 'APT:%s\n' "$*"; }
write_sysctl_config(){ echo WRITE_CONFIG; }
finish_with_reboot_notice(){ echo FINISH; }
install_xanmod_kernel
TEST
}

for script in main.sh testing.sh; do
    for codename in trixie bookworm; do
        for level in 1 2 3 4; do
            output=$(mock_install "$script" "$level" "$((level + 1))" amd64 "$codename")
            mapped_level="$level"
            [[ "$level" != 4 ]] || mapped_level=3
            branch=""
            if [[ "$level" == 1 || "$codename" == bookworm ]]; then branch=lts-; fi
            [[ "$output" == *"SUITE:$codename"* ]]
            [[ "$output" == *"APT:install -y linux-xanmod-${branch}x64v${mapped_level}"* ]]
            [[ "$output" == *WRITE_CONFIG*FINISH* ]]
        done
    done
    if output=$(mock_install "$script" 2 3 arm64 trixie 2>&1); then
        echo 'Non-amd64 installation was accepted' >&2
        exit 1
    fi
    [[ "$output" != *PREPARE* ]]
    for invalid in '0 1' '2 0' '2 1' '4 3' '5 6'; do
        read -r level status <<< "$invalid"
        if output=$(mock_install "$script" "$level" "$status" amd64 trixie 2>&1); then
            echo 'Invalid probe output/status was accepted' >&2
            exit 1
        fi
        [[ "$output" != *APT:* && "$output" != *WRITE_CONFIG* ]]
    done
done
printf 'installer package mapping, probe statuses and architecture guard ok\n'
