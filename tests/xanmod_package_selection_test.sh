#!/bin/bash

set -euo pipefail

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

printf 'xanmod package selection ok\n'
