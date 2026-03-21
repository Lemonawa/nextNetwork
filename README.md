# nextNetwork
A simple script to optimize relay and egress network performance on Debian GNU/Linux.
Support Debian GNU/Linux only.

Built around XanMod Kernel, Cloudflare TCP tuning, and XanMod's default BBRv3.

## Usage
`main.sh` - BBRv3+fq (recommended default, more balanced across most relay and egress workloads):
```bash
bash <(sudo curl -sSL https://raw.githubusercontent.com/Lemonawa/nextNetwork/main/main.sh)
```  
`testing.sh` - BBRv3+cake (testing profile, useful when you want stronger queue shaping):
```bash
bash <(sudo curl -sSL https://raw.githubusercontent.com/Lemonawa/nextNetwork/main/testing.sh)
```
## License
[MIT](https://choosealicense.com/licenses/mit/)
## Credits
[XanMod Kernel](https://xanmod.org/)  
[nexstorm/magicTCP](https://github.com/nexstorm/magicTCP)  
[Cloudflare's TCP collapse processing for high throughput and low latency](https://blog.cloudflare.com/optimizing-tcp-for-high-throughput-and-low-latency)  
[Linux内核参数调优 - Is Yang's Blog](https://www.isisy.com/1159.html)
