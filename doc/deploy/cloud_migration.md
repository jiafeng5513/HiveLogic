# 云迁移指南（mac mini → 云主机 Docker）

本文档指导将 HiveLogic 服务端从内网 mac mini 迁移到云主机 Docker 部署。

## 迁移架构对比

| 维度 | mac mini (内网) | 云主机 (Docker) |
|------|----------------|-----------------|
| 进程守护 | launchd | Docker `restart: always` |
| HTTPS | 无（内网直连） | Caddy 自动 TLS |
| 备份 | crontab + backup_db.sh | 调度器内置 + 云快照 |
| 网络 | 内网 IP，无防火墙 | 安全组 + Caddy 反向代理 |
| 数据 | 本地磁盘 | Docker volume + 云盘快照 |

## 前置条件

- 云主机：2C4G+（推荐 4C8G），100GB+ 磁盘
- Docker 24+ / Docker Compose v2+
- 已备案域名（中国大陆）或境外服务器 + 域名
- 安全组开放 80/443 端口

## 1. 数据备份（mac mini 端）

```bash
# 1.1 停止服务（避免写入冲突）
launchctl unload ~/Library/LaunchAgents/com.hivelogic.server.plist

# 1.2 完整备份
./deploy/backup_db.sh ~/migration_backup

# 1.3 备份配置文件
cp server/.env ~/migration_backup/.env
cp -r data/.session_secret ~/migration_backup/  # admin session 密钥
cp -r data/.admin_password_hash ~/migration_backup/  # admin 密码哈希

# 1.4 打包
cd ~/migration_backup && tar czf ../hivelogic_migration.tar.gz .

# 1.5 重启服务（mac mini 可继续服务直到切换完成）
launchctl load ~/Library/LaunchAgents/com.hivelogic.server.plist
```

## 2. 云主机准备

```bash
# 2.1 安装 Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# 重新登录使 docker 组生效

# 2.2 克隆代码
git clone <repo-url> ~/HiveLogic
cd ~/HiveLogic

# 2.3 传输迁移包
# 在 mac mini 端：
scp ~/hivelogic_migration.tar.gz <cloud-user>@<cloud-ip>:~/
```

## 3. 数据恢复（云主机端）

```bash
# 3.1 创建数据目录
mkdir -p ~/hivelogic-data

# 3.2 解压迁移包
tar xzf ~/hivelogic_migration.tar.gz -C ~/hivelogic-data/

# 3.3 恢复配置
cp ~/hivelogic-data/.env server/.env

# 3.4 编辑 .env 适配云环境
vim server/.env
```

`.env` 关键项修改：

```bash
DATABASE_PATH=/data/stock_analysis.db
LOG_DIR=/data/logs

# 启用鉴权
ADMIN_AUTH_ENABLED=true
CLIENT_AUTH_ENABLED=true

# CORS 限制为客户端域名
CORS_ALLOW_ALL=false
CORS_ORIGINS=https://your-domain.com

# 信任反向代理
TRUST_X_FORWARDED_FOR=true

# 日志 JSON 格式（供日志聚合）
LOG_JSON=true

# 限流
RATE_LIMIT_PER_MINUTE=60
RATE_LIMIT_ACCOUNT_PER_MINUTE=120
```

## 4. 启动服务

```bash
# 4.1 使用生产 compose + 反向代理
docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.proxy.yml up -d

# 4.2 验证
curl https://your-domain.com/api/health
docker compose ps  # 所有容器应为 healthy
```

## 5. 数据卷管理

### 5.1 使用命名卷（推荐生产）

```yaml
# docker-compose.prod.yml 已配置
volumes:
  hivelogic-data:  # 持久化数据
  caddy_data:      # TLS 证书
  caddy_config:    # Caddy 配置
```

### 5.2 使用绑定挂载（便于直接管理）

```yaml
# docker-compose.override.yml
services:
  server:
    volumes:
      - /home/anna/hivelogic-data:/data
```

### 5.3 云盘快照

大多数云厂商支持磁盘快照。建议：
- 每日自动快照（保留 7 天）
- 关键操作前手动快照

## 6. DNS 切换

```bash
# 6.1 确认云主机服务正常
curl -I https://your-domain.com/api/health
# 应返回 200

# 6.2 更新 DNS A 记录
# 在域名服务商控制台，将 A 记录从 mac mini IP 改为云主机 IP

# 6.3 等待 DNS 生效（TTL 视配置，通常 5-60 分钟）
dig your-domain.com +short
# 确认返回云主机 IP

# 6.4 停止 mac mini 服务
launchctl unload ~/Library/LaunchAgents/com.hivelogic.server.plist
```

## 7. 回滚方案

如云主机出现问题需回滚到 mac mini：

```bash
# 7.1 DNS 回切
# 将 A 记录改回 mac mini IP

# 7.2 恢复 mac mini 数据（如有云上增量）
# 在云主机上导出最新数据
docker exec hivelogic-server sqlite3 /data/stock_analysis.db ".backup '/tmp/rollback.db'"
docker cp hivelogic-server:/tmp/rollback.db ~/rollback.db
scp ~/rollback.db anna@<mac-mini-ip>:~/HiveLogic/data/stock_analysis.db

# 7.3 启动 mac mini 服务
launchctl load ~/Library/LaunchAgents/com.hivelogic.server.plist
```

## 8. 迁移后验证清单

- [ ] `https://your-domain.com/api/health` 返回 200
- [ ] 客户端连接 `https://your-domain.com` 正常加载行情
- [ ] WebSocket 实时行情通过 `wss://` 正常推送
- [ ] admin 管理面板可登录并操作
- [ ] 客户端账号可登录（如启用 CLIENT_AUTH_ENABLED）
- [ ] 调度任务正常执行（管理面板查看 scheduler 状态）
- [ ] 备份任务正常执行（管理面板触发或查看 `data/backups/`）
- [ ] Caddy TLS 证书有效（浏览器无警告）
- [ ] 日志正常输出（`docker compose logs -f server`）

## 9. 后续运维

### 日志聚合（可选）

`LOG_JSON=true` 已在 `.env` 中启用，日志为 JSON 格式，可直接接入：

```bash
# Loki + Promtail
# 或 Datadog Agent
# 或 ELK Stack
```

### 监控告警

- `/api/v1/admin/health` 提供聚合健康状态
- 配合 Uptime Robot / 阿里云监控 对该端点探测
- `status: critical` 时触发告警

### 定期更新

```bash
cd ~/HiveLogic
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.proxy.yml build
docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.proxy.yml up -d
```
