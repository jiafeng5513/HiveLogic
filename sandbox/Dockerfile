# sandbox/Dockerfile — AI 代码执行沙箱镜像
#
# 设计原则:
#   1. 无网络库 — 镜像内不安装 requests/httpx/urllib3/aiohttp 等，从源头杜绝数据出境
#   2. 非 root 运行 — sandbox 用户无 sudo，无 shell 登录
#   3. 只读文件系统 — 仅 /tmp 可写（tmpfs），配合 docker-compose read_only: true
#   4. 资源受限 — mem_limit 1g, cpus 0.5（在 docker-compose 中设置）
#   5. 数据只读 — 服务端缓存 DB 以只读卷挂载，沙箱可读不可写

FROM python:3.12-slim

# 创建非 root 用户
RUN groupadd -r sandbox && useradd -r -g sandbox -d /home/sandbox -s /usr/sbin/nologin sandbox

# 安装数据科学栈 + 中国市场数据源
# 注意: 不安装任何网络库（requests, httpx, urllib3, aiohttp, httpx 等）
# akshare 依赖部分网络库但我们在 network_mode: none 下运行，网络调用会直接失败
# 保留 akshare 是因为它的 DataFrame 工具函数（如指标计算）可离线使用
RUN pip install --no-cache-dir \
    "pandas>=2.2" \
    "numpy>=1.26" \
    "scipy>=1.13" \
    "matplotlib>=3.8" \
    "scikit-learn>=1.4" \
    "statsmodels>=0.14" \
    "akshare>=1.12" \
    "tushare>=1.4" \
    && rm -rf /root/.cache/pip

# matplotlib 非交互后端（无显示器环境必须）
ENV MPLBACKEND=Agg \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONDONTWRITEBYTECODE=1

# 工作目录 — /sandbox 为代码执行根目录
WORKDIR /sandbox
RUN mkdir -p /sandbox/data /tmp/sandbox_output && \
    chown -R sandbox:sandbox /sandbox /tmp/sandbox_output

# 安装 hivelogic_data 辅助模块（只读数据访问封装）
COPY sandbox/hivelogic_data.py /sandbox/hivelogic_data.py

# 切换到非 root 用户
USER sandbox

# 无 CMD — 此镜像作为 sidecar，由服务端通过 docker exec 注入代码执行
# 容器启动后保持 idle（sleep infinity），等待 exec 调用
CMD ["sleep", "infinity"]
