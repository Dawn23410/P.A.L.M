# 服务器 · 运维凭据与坑速查

## 凭据（中间打码，完整版见本地 MEMORY.md）
| 项 | 值 |
|---|---|
| 各主机统一密码 | wang**9594 |
| 建站 VM 账号 | debian / wang**9594 |
| 樱花 Frp | w53j****************************1u95 : 28****77（frp-sea.com:42503） |
| Cloudflare API | cfut************************2184（只读） |
| AGH 早期密码 | P@LM***6agh（后统一） |

## 关键坑速查
1. 无默认浏览器 → xdg-open 落到 LibreOffice（WorkBuddy 登录异常）
2. LXC 非登录 shell PATH 缺 /usr/local/bin → /usr/bin 建软链
3. rustup 需 RUSTUP_DIST_SERVER=rsproxy.cn，否则连官方源卡死
4. Debian 12 无 openjdk-21 → 清华 Adoptium tarball + update-alternatives
5. Debian cloud image 禁密码 SSH → 注入公钥登录
6. pkill -f 会匹配执行命令自身 → 用 PID 文件管服务进程
7. pip 走官方源哈希不匹配 → 必须显式 -i ustc
8. 樱花 frpc 需 x86-64-v2 → PVE CPU 类型设 host
9. WorkBuddy Linux 版锁 isOversea → ACC_PRODUCT_CONFIG_PATH 覆写切国服
10. chrony allow 行不支持行内注释
