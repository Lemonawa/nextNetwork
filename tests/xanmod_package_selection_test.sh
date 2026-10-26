#!/bin/bash

set -euo pipefail

# shellcheck source=../main.sh
source "$(dirname "$0")/../main.sh"

assert_eq() {
    local expected="$1"
    local actual="$2"

    if [[ "$expected" != "$actual" ]]; then
        printf 'expected %s, got %s\n' "$expected" "$actual" >&2
        exit 1
    fi
}

assert_lines_eq() {
    local expected="$1"
    local actual="$2"

    if [[ "$expected" != "$actual" ]]; then
        printf 'expected lines:\n%s\nactual lines:\n%s\n' "$expected" "$actual" >&2
        exit 1
    fi
}

assert_contains() {
    local pattern="$1"
    local actual="$2"

    if ! printf '%s\n' "$actual" | grep -F -q "$pattern"; then
        printf 'expected output to contain: %s\nactual lines:\n%s\n' "$pattern" "$actual" >&2
        exit 1
    fi
}

assert_not_contains() {
    local pattern="$1"
    local actual="$2"

    if printf '%s\n' "$actual" | grep -F -q "$pattern"; then
        printf 'expected output to not contain: %s\nactual lines:\n%s\n' "$pattern" "$actual" >&2
        exit 1
    fi
}

first_line_number() {
    local pattern="$1"
    local actual="$2"

    printf '%s\n' "$actual" | grep -n -m1 -F "$pattern" | cut -d: -f1
}

assert_lt() {
    local left="$1"
    local right="$2"

    if (( left >= right )); then
        printf 'expected %s to be less than %s\n' "$left" "$right" >&2
        exit 1
    fi
}

assert_eq "linux-xanmod-lts-x64v1" "$(select_xanmod_package 1)"
assert_eq "linux-xanmod-x64v2" "$(select_xanmod_package 2)"
assert_eq "linux-xanmod-x64v3" "$(select_xanmod_package 3)"
assert_eq "linux-xanmod-x64v3" "$(select_xanmod_package 4)"
assert_lines_eq $'wget\nca-certificates\ngnupg' "$(required_packages)"
assert_eq "fq" "$(sysctl_qdisc)"
assert_lines_eq $'Types: deb\nURIs: http://deb.xanmod.org/\nSuites: bookworm\nComponents: main\nSigned-By: /etc/apt/keyrings/xanmod-archive-keyring.gpg' "$(render_xanmod_sources bookworm)"
main_sysctl="$(render_sysctl_config)"
assert_lt "$(first_line_number "net.ipv4.ip_forward = 1" "$main_sysctl")" "$(first_line_number "net.ipv4.tcp_rmem = 8192 262144 536870912" "$main_sysctl")"
assert_contains "net.ipv4.tcp_ecn = 2" "$main_sysctl"
assert_not_contains "net.ipv4.tcp_tw_reuse =" "$main_sysctl"

# shellcheck source=../testing.sh
source "$(dirname "$0")/../testing.sh"

assert_eq "linux-xanmod-lts-x64v1" "$(select_xanmod_package 1)"
assert_eq "linux-xanmod-x64v2" "$(select_xanmod_package 2)"
assert_eq "linux-xanmod-x64v3" "$(select_xanmod_package 3)"
assert_eq "linux-xanmod-x64v3" "$(select_xanmod_package 4)"
assert_lines_eq $'wget\nca-certificates\ngnupg' "$(required_packages)"
assert_eq "cake" "$(sysctl_qdisc)"
assert_lines_eq $'Types: deb\nURIs: http://deb.xanmod.org/\nSuites: bookworm\nComponents: main\nSigned-By: /etc/apt/keyrings/xanmod-archive-keyring.gpg' "$(render_xanmod_sources bookworm)"
testing_sysctl="$(render_sysctl_config)"
assert_lt "$(first_line_number "net.ipv4.ip_forward = 1" "$testing_sysctl")" "$(first_line_number "net.ipv4.tcp_rmem = 8192 262144 536870912" "$testing_sysctl")"
assert_contains "net.ipv4.tcp_ecn = 2" "$testing_sysctl"
assert_not_contains "net.ipv4.tcp_tw_reuse =" "$testing_sysctl"

# Check both standalone scripts; sourcing must not perform system changes.
for script in main.sh testing.sh; do
    # shellcheck source=../main.sh
    source "$(dirname "$0")/../$script"
    assert_eq "linux-xanmod-lts-x64v1" "$(select_xanmod_package 1 bookworm)"
    assert_eq "linux-xanmod-lts-x64v2" "$(select_xanmod_package 2 bookworm)"
    assert_eq "linux-xanmod-lts-x64v3" "$(select_xanmod_package 3 bookworm)"
    assert_eq "linux-xanmod-lts-x64v3" "$(select_xanmod_package 4 bookworm)"
    assert_eq "linux-xanmod-x64v3" "$(select_xanmod_package 4 trixie)"
    if select_xanmod_package 0 >/dev/null 2>&1; then
        echo "Invalid CPU level was accepted" >&2
        exit 1
    fi
    config="$(render_sysctl_config)"
    assert_contains "net.ipv4.tcp_wmem = 4096 16384 536870912" "$config"
    assert_contains "net.ipv4.tcp_collapse_max_bytes = 6291456" "$config"
    assert_contains "net.ipv4.tcp_mtu_probing = 1" "$config"
    # Restore original tuning values unless an isolated change has evidence.
    for setting in 'net.core.netdev_max_backlog = 16384' 'net.ipv4.tcp_fin_timeout = 15' 'net.ipv4.tcp_fastopen = 3' 'net.ipv4.tcp_slow_start_after_idle = 0' 'net.ipv4.tcp_keepalive_time = 600'; do
        assert_contains "$setting" "$config"
    done
    assert_contains "net.core.default_qdisc = $(sysctl_qdisc)" "$config"
    assert_contains "net.ipv4.tcp_congestion_control = bbr" "$config"
done

printf 'package selection and sysctl profiles ok\n'
