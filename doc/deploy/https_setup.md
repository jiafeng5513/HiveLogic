# HTTPS / WSS 部署指南（Caddy 反向代理）

本文档指导通过 Caddy 反向代理为 HiveLogic 服务端启用 HTTPS/WSS 加密传输。

## 为什么选 Caddy

| 维度 | Caddy | Nginx | Traefik |
|------|-------|-------|---------|
| 自动 TLS | 内置 Let's Encrypt 自动签发+续期 | 需 certbot 额外组件 | 内置但配置复杂 |
| 配置复杂度 | ~30 行 Caddyfile | ~80 行 + certbot | YAML/Docker labels |
| HTTP/3 | 默认启用 | 需编译参数 | 支持 |
| 资源占用 | ~20MB 内存 | ~5MB | ~50MB |
| 适用场景 | 中小项目首选 | 高并发/精细控制 | K8s/动态服务发现 |

HiveLogic 选用 Caddy：自动 TLS 零配置、单文件配置、资源占用低。

## 部署架构

```
客户端 (HTTPS/WSS)
    │
    ▼
┌──────────────────────────┐
│  Caddy (:80, :443)        │  ← 自动 TLS 证书
│  - 反向代理 → backend     │
│  - 安全头 (HSTS 等)       │
│  - 限流 (基础)            │
└──────────┬───────────────┘
           │ (内网 HTTP)
           ▼
┌──────────────────────────┐
│  FastAPI (:8100)          │  ← 不直接暴露
│  - REST API + WebSocket   │
│  - 深层鉴权 + 限流         │
└──────────────────────────┘
```

## 1. 前置条件

- 已按 `docker_deploy.md` 部署 Docker 版 HiveLogic 服务端
- 拥有域名（公网部署）或使用内网 IP（内网部署）
- 开放 80 + 443 端口

### 1.1 公网域名场景

1. DNS A 记录指向服务器公网 IP
2. 确保运营商/云厂商未封 80/443 端口

### 1.2 内网无域名场景

Caddy 使用 internal CA 自动签发证书，浏览器需手动信任：

```bash
# 1. 编辑 Caddyfile，将 your-domain.com 替换为内网 IP
#    例: 192.168.50.7 {
sed -i 's/your-domain.com/192.168.50.7/g' deploy/Caddyfile

# 2. 信任 Caddy 内部 CA（首次访问时浏览器会提示不安全）
#    macOS: 访问 https://192.168.50.7 → 高级 → 信任证书
```

## 2. 启动

```bash
# 编辑 Caddyfile 替换域名
vim deploy/Caddyfile
# 将 your-domain.com 替换为实际域名，如 app.hivelogic.com

# 启动（Caddy + 后端）
docker compose -f docker-compose.yml -f docker-compose.proxy.yml up -d
```

验证：

```bash
# HTTPS 健康检查
curl https://your-domain.com/api/health

# 证书信息
openssl s_client -connect your-domain.com:443 -servername your-domain.com < /dev/null 2>/dev/null | openssl x509 -noout -dates -issuer

# 应看到 Let's Encrypt 签发，有效期 ~90 天
```

## 3. 客户端配置

在客户端「设置 → 服务端连接」中：
1. 选择「远程服务端」模式
2. 填入 `https://your-domain.com`（注意 https）
3. 测试连接
4. 保存重启

WebSocket 自动走 `wss://` 协议，无需额外配置。

## 4. 安全头说明

Caddyfile 配置了以下安全头：

| Header | 作用 |
|--------|------|
| `Strict-Transport-Security` | HSTS：强制浏览器后续访问走 HTTPS（31536000s = 1年） |
| `X-Content-Type-Options` | 禁止 MIME 嗅探 |
| `X-Frame-Options` | 禁止 iframe 嵌入（防点击劫持） |
| `Referrer-Policy` | 控制 Referrer 泄露 |

内网测试阶段如需关闭 HSTS（避免浏览器缓存强制 HTTPS），注释掉对应行即可。

## 5. 证书管理

Caddy 自动管理证书生命周期：
- 首次启动：通过 ACME HTTP-01 自动申请 Let's Encrypt 证书
- 续期：到期前 30 天自动续期
- 撤销/重置：删除 `caddy_data` volume 后重启

```bash
# 查看证书状态
docker exec hivelogic-caddy caddy list-modules | grep tls

# 重置证书（谨慎！）
docker compose -f docker-compose.yml -f docker-compose.proxy.yml down
docker volume rm hivelogic_caddy_data
docker compose -f docker-compose.yml -f docker-compose.proxy.yml up -d
```

## 6. 日志查看

```bash
# Caddy 访问日志（JSON 格式）
docker compose -f docker-compose.yml -f docker-compose.proxy.yml logs -f caddy

# 后端日志（不受影响）
docker compose -f docker-compose.yml -f docker-compose.proxy.yml logs -f server
```

## 7. 后端配合配置

启用反向代理后，后端需感知 `X-Forwarded-*` 头。在 `server/.env` 中：

```bash
# 信任反向代理转发的客户端 IP（用于限流、日志记录真实 IP）
TRUST_X_FORWARDED_FOR=true

# CORS 允许客户端来源
CORS_ALLOW_ALL=false
CORS_ORIGINS=https://your-domain.com
```

## 8. 故障排查

### 8.1 证书申请失败

```bash
# 检查 80 端口可达性（Let's Encrypt HTTP-01 验证需要）
curl -I http://your-domain.com/.well-known/acme-challenge/test

# 常见原因：
# - 80 端口被防火墙拦截
# - DNS 未正确指向本机
# - 已有其他服务占用 80/443
```

### 8.2 WebSocket 连接失败

Caddyfile 已对 `/ws/*` 路径配置反向代理。确认：
- 客户端使用 `wss://` 而非 `ws://`
- 后端 `/ws/market` 端点正常工作（`curl https://your-domain.com/api/ws/status`）

### 8.3 502 Bad Gateway

```bash
# 后端容器是否健康
docker compose -f docker-compose.yml -f docker-compose.proxy.yml ps
# server 列应为 "healthy"

# 后端是否监听 8100
docker exec hivelogic-server curl -s http://localhost:8100/api/health
```

## 9. 回滚

如需移除 Caddy 回到直接暴露 8100 端口：

```bash
docker compose -f docker-compose.yml -f docker-compose.proxy.yml down
docker compose up -d  # 仅基础 compose，直接暴露 8100
```
