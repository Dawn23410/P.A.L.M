# P.A.L.M 内网可登录地址清单

> 网段：管理段 `192.168.1.0/24`（仅局域网可达）
> **公网穿透已于 2026-08-31 全部禁用**（Cloudflare Tunnel / 樱花 Frp 均 stop + disable，无任何公网地址）。以下仅局域网预设通道。

## 统一凭据
- 通用密码：`[REDACTED_PASSWORD]`
- 网关/宿主机/VM 系统账号均使用上述密码（SSH 与 Web 同口令）。

---

## 1. PVE 管理面板（宿主机）
- **地址**：https://192.168.1.250:8006
- **账号**：`root`
- **密码**：`[REDACTED_PASSWORD]`
- **用途**：PVE 宿主机管理、VM/CT 开关机、控制台、存储、备份。
- 注：自签证书，浏览器会告警，继续访问即可。

## 2. PVE SSH（宿主机命令行）
- **地址**：`ssh root@192.168.1.250`（端口 22）
- **账号**：`root` / **密码**：`[REDACTED_PASSWORD]`

## 3. OpenWrt 路由器 LuCI（网关）
- **地址**：http://192.168.1.252
- **账号**：`root` / **密码**：`[REDACTED_PASSWORD]`（与 AGH 同口令；若曾单独改过以实际为准）
- **用途**：网关、DHCP、防火墙、网络管理；断网兜底核心。

## 4. AdGuard Home 去广告后台
- **地址**：http://192.168.1.252:3000
- **账号**：`root` / **密码**：`[REDACTED_PASSWORD]`
- **用途**：DNS 过滤规则、统计、客户端管理。

## 5. Ubuntu VM100 桌面（noVNC 网页，推荐）
- **地址**：http://192.168.1.253（nginx :80）
- **鉴权**：HTTP Basic Auth → **账号** `ubuntu` / **密码** `[REDACTED_PASSWORD]`
- 验证：无密码访问返回 `401`，带密返回 `200`。
- **说明**：
  - 浏览器直连即可，无需额外 VNC 密码（x11vnc 已设 `-nopw`，仅 nginx 一层 Basic Auth）。
  - 已预装 **WorkBuddy 桌面版**（桌面图标 `workbuddyai`，点击即开图形界面）。
  - 已预装编程环境：Python 3.10 / Node 24 / Java 21 / Go 1.27 / Rust 1.98。
  - 链路：浏览器 → nginx(:80) → websockify(:6080 localhost) → x11vnc(:5900 localhost)。

## 6. Ubuntu VM100 SSH（命令行运维）
- **地址**：`ssh ubuntu@192.168.1.253`（端口 22）
- **账号**：`ubuntu` / **密码**：`[REDACTED_PASSWORD]`
- **说明**：`go` 与 `cargo` 需在**登录壳**中使用（已写 `/etc/profile.d/go.sh`、rustup 写入 `~/.cargo/env`）；打开桌面终端即为登录壳，可直接用。

---

## 不可从局域网直连（仅 localhost 绑定）
- VNC `:5900`、websockify `:6080` 均绑定 `127.0.0.1`，外部必须经 nginx(:80) 访问，**不可直连**。
- 公网隧道（Cloudflare / 樱花）：**已禁用**，无公网地址。

## 断网兜底
- 笔记本网线插 PVE `nic1` → OpenWrt 下发 DHCP(100-249) → 直连 `.250/.252/.253` 上述地址仍可用。
