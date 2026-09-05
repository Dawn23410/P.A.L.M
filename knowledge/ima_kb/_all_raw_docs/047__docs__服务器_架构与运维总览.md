# 服务器 · 架构与运维总览

> 更新：2026-08-31 | P.A.L.M 家庭服务器（PVE 虚拟化）

## 网络拓扑（192.168.1.0/24）
- PVE 宿主机 .250:8006（pve-node，9.2.11）
- OpenWrt CT252 .252：LuCI :80 / AdGuard Home :3000 / DNS :53 / DHCP :67（离线兜底核心）
- dev251 CT251 .251：编程容器（Debian 12）
- web-bt VM102 .253：建站 VM（Debian 12，宝塔待装）
- 网关统一 .250（PVE）；断网兜底：笔记本插 nic1 → WRT 下发 DHCP(100-249)

## 客户机
| 机 | 配置 | 要点 |
|---|---|---|
| VM102 web-bt | 2核/2.5G+1Gswap/50G | Debian 12 cloud，cpu=host，SSH 公钥登录，宝塔未装 |
| CT251 dev251 | 1G/2核/10G+/projects 50G | Python3.10/Node24/Java21/Go/Rust，pip 269 包，unprivileged+nesting |
| CT252 openwrt | 256M/1核/1G | AGH 17.9万规则 + dnsmasq :53/:67 |

## 授时（分层）
- PVE chrony 直连国内源：ntp.ntsc.ac.cn(prefer)/aliyun/tencent/neu，已 allow 局域网
- LXC 共享宿主内核时钟，容器间差值恒 ≈0（实测 0.02ms）
- 坑：chrony 4.8 的 allow 不支持行内注释

## 公网穿透（容器化待落地）
- 轻量 LXC（Alpine ~100MB）+ nginx 按域/路径分发多服务
- 域名 zerodimensioncn.eu.org 审核中（每日 13:00 自动检查）
