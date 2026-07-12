# HiveLogic 服务端部署指南（macOS）

本文档指导在 mac mini（或任意 macOS 机器）上部署 HiveLogic 服务端，使其 7×24 常驻运行。

## 前置条件

- macOS 12+（推荐 macOS 14+）
- [Homebrew](https://brew.sh/)
- Python 3.12+（通过 uv 管理）
- [uv](https://docs.astral.sh/uv/)（Python 包管理器）

## 1. 环境准备

```bash
# 安装 Homebrew（如果尚未安装）
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 安装 uv
brew install uv

# 克隆代码
git clone <repo-url> ~/HiveLogic
cd ~/HiveLogic
```

## 2. 配置 .env

在 `server/` 目录下创建 `.env` 文件：

```bash
cp server/.env.example server/.env  # 如果有示例文件
# 或手动创建
```

关键配置项：

| 变量 | 说明 | 示例 |
|------|------|------|
| `DATABASE_PATH` | SQLite 数据库路径 | `/Users/anna/HiveLogic/data/stock_analysis.db` |
| `ADMIN_AUTH_ENABLED` | 启用 admin 口令鉴权 | `true` |
| `CORS_ORIGINS` | 允许的客户端来源（逗号分隔） | `http://192.168.50.100:5173` |
| `CORS_ALLOW_ALL` | 内网开发时允许所有来源 | `true`（仅内网） |

## 3. 数据目录与持久化

服务端的持久化文件位于 `DATABASE_PATH` 的同级目录下：

| 文件 | 说明 |
|------|------|
| `stock_analysis.db` | 主数据库（SQLite WAL 模式） |
| `.session_secret` | admin session 签名密钥（自动生成） |
| `.admin_password_hash` | admin 口令哈希 |

默认路径为 `./data/`，建议显式设置 `DATABASE_PATH` 指向独立数据目录：

```bash
export DATABASE_PATH=/Users/anna/HiveLogic/data/stock_analysis.db
```

## 4. 手动启动测试

```bash
# 首次运行会自动创建虚拟环境并安装依赖
./deploy/run_server.sh --host 0.0.0.0 --port 8100
```

验证服务：

```bash
curl http://localhost:8100/api/health
# 应返回 {"status":"healthy",...}
```

## 5. launchd 进程守护（开机自启 + 崩溃自拉起）

### 5.1 安装 plist

```bash
# 替换 __REPO_ROOT__ 占位符
REPO_ROOT="$HOME/HiveLogic"
sed "s|__REPO_ROOT__|$REPO_ROOT|g" deploy/com.hivelogic.server.plist \
  > ~/Library/LaunchAgents/com.hivelogic.server.plist

# 加载服务
launchctl load ~/Library/LaunchAgents/com.hivelogic.server.plist
```

### 5.2 管理命令

```bash
# 查看状态
launchctl list | grep hivelogic

# 停止
launchctl unload ~/Library/LaunchAgents/com.hivelogic.server.plist

# 启动
launchctl load ~/Library/LaunchAgents/com.hivelogic.server.plist

# 查看日志
tail -f ~/HiveLogic/logs/launchd-stdout.log
tail -f ~/HiveLogic/logs/launchd-stderr.log
```

### 5.3 launchd 配置说明

| 键 | 值 | 说明 |
|----|----|------|
| `RunAtLoad` | `true` | 加载时立即启动 |
| `KeepAlive` | `true` | 进程退出后自动重启 |
| `ProcessType` | `Background` | 后台进程优先级 |

## 6. 数据库备份

```bash
# 手动备份
./deploy/backup_db.sh

# 自动备份（crontab，每天凌晨 3:30）
crontab -e
# 添加：
30 3 * * * /Users/anna/HiveLogic/deploy/backup_db.sh >> /Users/anna/HiveLogic/logs/backup.log 2>&1
```

备份脚本使用 `sqlite3 .backup`（WAL 安全），保留最近 30 份备份。

## 7. 网络与安全（内网阶段）

### 7.1 固定 IP

在 mac mini 上设置静态 IP（系统设置 → 网络 → 高级 → TCP/IP → 手动配置）。
例如 `192.168.50.7`。

### 7.2 端口放行

macOS 默认防火墙不阻止入站连接。如启用了防火墙：

```bash
# 允许 Python/uv 监听 8100 端口（系统设置 → 网络 → 防火墙）
# 或使用 pfctl 规则（高级）
```

### 7.3 admin 口令

首次启动后，设置 admin 口令：

```bash
cd server
uv run python -c "from src.auth import set_admin_password; set_admin_password('your-strong-password')"
```

### 7.4 客户端连接

在客户端的「设置 → 服务端连接」中：
1. 选择「远程服务端」模式
2. 填入 `http://192.168.50.7:8100`
3. 点击「测试连接」验证可达性
4. 保存并重启客户端

## 8. 验收清单

- [ ] mac mini 重启后服务端自动恢复（`launchctl list | grep hivelogic` 有输出）
- [ ] `kill` 进程后被 launchd 拉起（等待几秒后 `curl /api/health` 仍可用）
- [ ] 客户端断开/重连后行情不丢失
- [ ] 数据库备份正常生成
