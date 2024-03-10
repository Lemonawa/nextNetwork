# nextNetwork
A simple script to optimize network performance on Debian GNU/Linux.  
Support Debian GNU/Linux only.  
## Usage
BBR+fq(Recommended in bad network conditions):
```bash
bash <(sudo curl -sSL https://raw.githubusercontent.com/Lemonawa/nextNetwork/main/main.sh)
```  
BBR+cake(Recommended in good network conditions):
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