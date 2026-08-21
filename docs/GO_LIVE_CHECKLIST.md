# 上线执行手册：Docker、CI 与简历量化指标

> 目标：把这三点从“计划”变成“能写在简历上的结果”
> 1. Docker + 云服务器 + HTTPS 在线地址
> 2. 测试/CI/离线评测，拿到通过率
> 3. 运行数据统计，拿到 token、耗时、成本、成功率

## 1. 本地 Docker 部署

```bash
# 进入项目目录
cd D:/GitHub/ai-travel-agent

# 确保 .env 已填好真实 Key
# 构建并启动
docker compose up -d --build

# 查看状态
docker compose ps

# 打开
http://localhost:8000

# 看日志
docker compose logs -f app
```

数据目录 `./data` 通过 volume 挂载，容器重建不会丢数据库和上传文件。

## 2. 云服务器部署

推荐：腾讯云轻量 / 阿里云 ECS / 华为云 Flexus，2C2G 起步，选 Ubuntu 22.04。

```bash
# 服务器上安装
sudo apt update
sudo apt install -y docker.io docker-compose-plugin nginx
sudo systemctl enable --now docker

# 把项目传到服务器
rsync -av --exclude data --exclude .venv --exclude __pycache__ ./ root@你的服务器IP:/opt/ai-travel-agent/

# 服务器上启动
cd /opt/ai-travel-agent
cp .env .env.prod   # 用生产 Key
docker compose up -d --build
```

## 3. 域名与 HTTPS

1. 在域名商加一条 A 记录：`travel.你的域名.com` -> 服务器 IP。
2. 使用 Nginx 反向代理：

```nginx
server {
    listen 80;
    server_name travel.你的域名.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_buffering off;
    }
}
```

3. 安装 HTTPS 证书：

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d travel.你的域名.com
```

完成后访问 `https://travel.你的域名.com`，这个地址就可以写进简历。

## 4. 测试与 CI

本地执行：

```bash
python -m pytest tests -q
python -m app.eval.runner --output data/eval_report.json
```

CI 已经在 `.github/workflows/ci.yml` 配置好：

- `python -m compileall -q app scripts`
- `python -m pytest tests -q`
- `python -m app.eval.runner --output data/eval_report.json`
- 上传 `eval_report.json` 作为 artifact
- `docker build -f Dockerfile.prod`

推到 GitHub 后，在仓库 `Actions` 页可以看到通过结果。把“Tests passed”和“eval pass rate”截图或数字放进简历。

## 5. 运行数据统计

每次真实对话都会写入 `agent_runs` 表，包含意图、状态、prompt/completion token、耗时。

生成统计报告：

```bash
python scripts/usage_report.py --output data/usage_report.json
```

输出示例：

```json
{
  "total_runs": 100,
  "success_runs": 96,
  "failed_runs": 4,
  "success_rate": 0.96,
  "avg_latency_ms": 8200,
  "p95_latency_ms": 15000,
  "total_tokens": 1200000,
  "estimated_cost_yuan": 5.6,
  "by_intent": {"create": 40, "adjust": 35, "ask": 20, "chat": 5}
}
```

管理员接口：

- `GET /api/admin/runs`：最近运行记录
- `GET /api/admin/stats`：运行汇总 + 指标快照

搜索链路还会记录：

- `search_cache_hit` / `search_cache_miss`
- `search_provider_tavily` / `search_provider_serpapi` / `search_provider_multi_platform` / `search_provider_builtin_fallback`

缓存命中率可以从 `GET /api/admin/stats` 的 `metrics.tool_counts` 里计算：

```text
命中率 = search_cache_hit / (search_cache_hit + search_cache_miss)
```

## 6. 可以写进简历的量化指标

| 指标 | 获取方式 |
|---|---|
| 测试通过率 | `pytest` 输出 |
| 评测通过率 | `data/eval_report.json` 的 `pass_rate` |
| 平均耗时 / P95 | `scripts/usage_report.py` |
| Token 总量 / 预估成本 | `scripts/usage_report.py` |
| 搜索缓存命中率 | `/api/admin/stats` |
| 在线地址 | `https://travel.你的域名.com` |
