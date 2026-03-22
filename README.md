# nextNetwork
A simple script to optimize relay and egress network performance on Debian GNU/Linux.
Support Debian GNU/Linux only.

Built around XanMod Kernel, Cloudflare TCP tuning, and XanMod's default BBRv3.

The installer follows the current XanMod repository layout and selects packages by CPU level:

- `x86-64-v1` -> `linux-xanmod-lts-x64v1`
- `x86-64-v2` -> `linux-xanmod-x64v2`
- `x86-64-v3` -> `linux-xanmod-x64v3`
- `x86-64-v4` -> `linux-xanmod-x64v3`

## Usage
`main.sh` - BBRv3+fq (recommended default, more balanced across most relay and egress workloads):
```bash
bash -lc 'apt-get update && apt-get install -y wget ca-certificates && bash <(wget -qO- https://raw.githubusercontent.com/Lemonawa/nextNetwork/main/main.sh)'
```  
`testing.sh` - BBRv3+cake (testing profile, useful when you want stronger queue shaping):
```bash
bash -lc 'apt-get update && apt-get install -y wget ca-certificates && bash <(wget -qO- https://raw.githubusercontent.com/Lemonawa/nextNetwork/main/testing.sh)'
```

## Notes
- Run the script as `root`.
- The one-liners above bootstrap `wget` and `ca-certificates` first so they work on minimal Debian installs too.
- Inside the script, only `wget`, `ca-certificates`, and `gnupg` are installed before adding the XanMod repository.
- If you prefer `curl`, install it first and replace `wget -qO-` with `curl -sSL`.
- Option `1` installs XanMod, writes the sysctl profile, and then reboots. Live sysctl apply is intentionally skipped until the new kernel is booted.
- Option `2` is for systems already running XanMod; it applies the sysctl profile immediately and then reboots after confirmation.

## License
[MIT](https://choosealicense.com/licenses/mit/)
## Credits
[XanMod Kernel](https://xanmod.org/)  
[nexstorm/magicTCP](https://github.com/nexstorm/magicTCP)  
[Cloudflare's TCP collapse processing for high throughput and low latency](https://blog.cloudflare.com/optimizing-tcp-for-high-throughput-and-low-latency)  
[Linux内核参数调优 - Is Yang's Blog](https://www.isisy.com/1159.html)
