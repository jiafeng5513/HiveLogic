# HiveLogic Docker 部署指南

本文档指导使用 Docker 容器化部署 HiveLogic 服务端，适用于云主机或需要容器化隔离的场景。

## 前置条件

- Docker 24+
- Docker Compose v2+

## 1. 快速启动

```bash
# 在仓库根目录
docker compose up -d
```

服务将在 `http://localhost:8100` 启动。

验证：

```bash
curl http://localhost:8100/api/health
```

## 2. 配置

### 2.1 环境变量

通过 `.env` 文件或 `docker-compose.override.yml` 配置：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DATABASE_PATH` | `/data/stock_analysis.db` | 数据库路径（容器内） |
| `LOG_DIR` | `/data/logs` | 日志目录（容器内） |
| `CORS_ORIGINS` | （空） | 允许的客户端来源，逗号分隔 |
| `CORS_ALLOW_ALL` | `true` | 内网开发时允许所有来源 |

### 2.2 服务端 .env

将服务端配置文件挂载到容器：

```yaml
# docker-compose.override.yml
services:
  server:
    volumes:
      - ./server/.env:/app/server/.env:ro
    environment:
      - CORS_ALLOW_ALL=false
      - CORS_ORIGINS=https://your-client-domain.com
```

### 2.3 数据持久化

数据通过 Docker volume `hivelogic-data` 持久化，独立于容器生命周期：

```bash
# 查看数据卷
docker volume inspect hivelogic_hivelogic-data

# 备份数据卷
docker run --rm -v hivelogic_hivelogic-data:/data -v $(pwd):/backup \
  alpine tar czf /backup/hivelogic-data-$(date +%Y%m%d).tar.gz /data
```

## 3. 构建与镜像管理

```bash
# 重新构建镜像
docker compose build

# 查看镜像
docker images | grep hivelogic

# 清理旧镜像
docker image prune -f
```

## 4. 日志查看

```bash
# 实时日志
docker compose logs -f server

# 最近 100 行
docker compose logs --tail 100 server
```

## 5. 健康检查

Dockerfile 内置了 `HEALTHCHECK`，每 30 秒探测 `/api/health`：

```bash
docker compose ps
# STATUS 列显示 "healthy" / "unhealthy" / "starting"
```

## 6. 从 launchd 迁移到 Docker

如果在 mac mini 上从 launchd 切换到 Docker：

```bash
# 1. 停止 launchd 服务
launchctl unload ~/Library/LaunchAgents/com.hivelogic.server.plist

# 2. 迁移数据
cp ~/HiveLogic/data/stock_analysis.db ./data/

# 3. 启动 Docker
docker compose up -d

# 4. 验证
curl http://localhost:8100/api/health
```

## 7. 云迁移路径

Docker 镜像不变，迁移流程：

1. 构建并推送镜像到镜像仓库（`docker build -t registry/hivelogic-server:latest .`）
2. 云主机拉取镜像（`docker pull registry/hivelogic-server:latest`）
3. 挂载数据卷（从备份恢复）
4. `docker compose up -d`

未来迁移到 K8s 时，镜像不变，只需将 docker-compose.yml 转换为 K8s Deployment + PVC。

## 8. 多环境配置

### 8.1 环境概览

| 环境 | Compose 文件 | 用途 | HTTPS | 鉴权 | CORS |
|------|-------------|------|-------|------|------|
| 开发 | `docker-compose.yml` | 本地调试 | 否 | 关闭 | 允许所有 |
| 生产 | `docker-compose.yml` + `docker-compose.prod.yml` | 云主机上线 | 否（直连） | 强制开启 | 限定域名 |
| 生产+TLS | `docker-compose.yml` + `docker-compose.prod.yml` + `docker-compose.proxy.yml` | 云主机上线 | Caddy 自动 | 强制开启 | 限定域名 |

### 8.2 开发环境

```bash
docker compose up -d
```

- `CORS_ALLOW_ALL=true`，允许所有来源
- 鉴权关闭，直接访问 API
- 直接暴露 8100 端口

### 8.3 生产环境（无 TLS，已有前置负载均衡器）

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

`docker-compose.prod.yml` 关键配置：
- `CORS_ALLOW_ALL=false`，限定 `CORS_ORIGINS`
- `ADMIN_AUTH_ENABLED=true` / `CLIENT_AUTH_ENABLED=true`
- `TRUST_X_FORWARDED_FOR=true`（配合前置负载均衡器）
- `LOG_JSON=true`（JSON 日志供聚合系统消费）
- `restart: always` + 内存限制 4GB
- 日志驱动 `json-file`，单文件 50MB，保留 5 份

### 8.4 生产环境 + Caddy 自动 TLS

```bash
# 编辑 Caddyfile 替换域名
vim deploy/Caddyfile

# 启动
docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.proxy.yml up -d
```

- Caddy 自动申请/续期 Let's Encrypt 证书
- 80/443 端口由 Caddy 占用，后端 8100 不直接暴露
- HTTP/3 (QUIC) 默认启用
- 详见 `https_setup.md`

### 8.5 环境变量管理

生产环境敏感配置通过 `.env` 文件传入（不入版本控制）：

```bash
# 在仓库根目录创建 .env（docker compose 自动读取）
cat > .env << 'EOF'
CORS_ORIGINS=https://your-domain.com
ADMIN_AUTH_ENABLED=true
CLIENT_AUTH_ENABLED=true
RATE_LIMIT_PER_MINUTE=60
RATE_LIMIT_ACCOUNT_PER_MINUTE=120
EOF
```

服务端应用自身的 `.env`（数据库路径、AI Key 等）通过 volume 挂载：

```yaml
# docker-compose.prod.yml 已包含
volumes:
  - ./server/.env:/app/server/.env:ro
```

### 8.6 自定义 Override

如需进一步定制，创建 `docker-compose.override.yml`（docker compose 自动合并）：

```yaml
# docker-compose.override.yml
services:
  server:
    environment:
      - RATE_LIMIT_PER_MINUTE=120  # 提高限流
    deploy:
      resources:
        limits:
          memory: 8G  # 扩容
```
