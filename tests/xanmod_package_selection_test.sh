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

assert_eq "linux-xanmod-lts-x64v1" "$(select_xanmod_package 1)"
assert_eq "linux-xanmod-x64v2" "$(select_xanmod_package 2)"
assert_eq "linux-xanmod-x64v3" "$(select_xanmod_package 3)"
assert_eq "linux-xanmod-x64v3" "$(select_xanmod_package 4)"
assert_lines_eq $'wget\nca-certificates\ngnupg' "$(required_packages)"

source "$(dirname "$0")/../testing.sh"

assert_eq "linux-xanmod-lts-x64v1" "$(select_xanmod_package 1)"
assert_eq "linux-xanmod-x64v2" "$(select_xanmod_package 2)"
assert_eq "linux-xanmod-x64v3" "$(select_xanmod_package 3)"
assert_eq "linux-xanmod-x64v3" "$(select_xanmod_package 4)"
assert_lines_eq $'wget\nca-certificates\ngnupg' "$(required_packages)"

printf 'xanmod package selection ok\n'
