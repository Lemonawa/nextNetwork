#!/bin/bash
# Execute both installers against temporary apt paths and a real Debian archive public key.
set -euo pipefail
repo_dir=$(cd "$(dirname "$0")/.." && pwd)
fixture_dir=$(mktemp -d)
trap 'rm -rf -- "$fixture_dir"' EXIT
export GNUPGHOME="$fixture_dir/gnupg"
mkdir -m 0700 "$GNUPGHOME"
# Reuse public data only; no secret keys, network access or agent is needed.
gpg --no-autostart --no-options --batch --no-default-keyring --keyring /usr/share/keyrings/debian-archive-keyring.gpg --armor --export > "$fixture_dir/archive.asc" 2>/dev/null
[[ -s "$fixture_dir/archive.asc" ]]

for script in main.sh testing.sh; do
    for version in original current; do
        case_dir="$fixture_dir/$script-$version"
        mkdir -p "$case_dir/etc/apt/sources.list.d"
        if [[ "$version" == original ]]; then
            git -C "$repo_dir" show "5dfb9ede9ec0727984f97076a9685cb293f5097a:$script" > "$case_dir/source.sh"
        else
            cp "$repo_dir/$script" "$case_dir/source.sh"
        fi
        python3 - "$case_dir" <<'PY'
from pathlib import Path
import sys
root=Path(sys.argv[1])
p=root/'source.sh'
p.write_text(p.read_text().replace('/etc/apt/',str(root/'etc/apt')+'/'))
PY
        cat > "$case_dir/execute.sh" <<'TEST'
#!/bin/bash
set -euo pipefail
case_dir="$1"
archive_key="$2"
cd "$case_dir"
# shellcheck source=/dev/null
source "$case_dir/source.sh"
require_root(){ :; }
prepare(){ :; }
get_debian_codename(){ echo trixie; }
dpkg(){ echo amd64; }
apt(){ :; }
apt-get(){ :; }
write_sysctl_config(){ :; }
finish_with_reboot_notice(){ :; }
# An unattended installer has no terminal from which to answer overwrite prompts.
gpg(){ command gpg --no-tty "$@"; }
wget(){
    local destination='' url=''
    while (( $# )); do
        case "$1" in
            -O|-qO) destination="$2"; shift 2 ;;
            -U) shift 2 ;;
            https://*) url="$1"; shift ;;
            *) shift ;;
        esac
    done
    case "$url" in
        */check_x86-64_psabi.sh)
            printf '#!/usr/bin/awk -f\nBEGIN {print "CPU supports x86-64-v2"; exit 3}\n' > "$destination"
            ;;
        */archive.key)
            if [[ "$destination" == '-' ]]; then cat "$archive_key"; else cp "$archive_key" "$destination"; fi
            ;;
        *) return 1 ;;
    esac
}
install_xanmod_kernel
TEST
        if ! timeout 10 bash "$case_dir/execute.sh" "$case_dir" "$fixture_dir/archive.asc" > "$case_dir/first.log" 2>&1; then
            cat "$case_dir/first.log" >&2
            exit 1
        fi
        if timeout 10 bash "$case_dir/execute.sh" "$case_dir" "$fixture_dir/archive.asc" > "$case_dir/second.log" 2>&1; then
            second_status=0
        else
            second_status=$?
        fi
        if [[ "$version" == original ]]; then
            [[ "$second_status" != 0 && "$second_status" != 124 ]]
            printf '%s original: first install passed; unattended repeat failed as reproduced\n' "$script"
        else
            [[ "$second_status" == 0 ]]
            [[ "$(stat -c '%a' "$case_dir/etc/apt/keyrings/xanmod-archive-keyring.gpg")" == 644 ]]
            gpg --batch --show-keys "$case_dir/etc/apt/keyrings/xanmod-archive-keyring.gpg" > /dev/null 2>&1
            printf '%s current: both installs passed; real keyring remains valid and mode 0644\n' "$script"
        fi
    done
done
