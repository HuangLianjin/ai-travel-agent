# 国内轻量服务器部署

适合想稳定、不睡觉、便宜上线的场景。推荐腾讯云/阿里云轻量应用服务器。

## 1. 买服务器

- 腾讯云：轻量应用服务器，2C2G 起步，Ubuntu 22.04。
- 阿里云：轻量应用服务器，2C2G 起步，Ubuntu 22.04。
- 新用户常有活动价，一般每月几元到 30 元左右。
- 地域选离你和面试官近的，比如广州/上海/北京。

## 2. 放行端口

在云控制台“防火墙/安全组”放行：

```text
22    SSH
80    可选，后续配域名用
443   可选，后续配 HTTPS 用
8000  直接访问项目
```

## 3. 一键部署

SSH 登录服务器后执行：

```bash
sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/HuangLianjin/ai-travel-agent/main/scripts/deploy_linux.sh)"
```

脚本会安装 Docker、拉取项目、生成 `.env`、启动服务。

## 4. 填 Key

编辑 `/opt/ai-travel-agent/.env`，至少填：

```text
OPENAI_API_KEY=你的 DeepSeek Key
TAVILY_API_KEY=你的 Tavily Key
MAP_MCP_API_KEY=你的高德 Key
QWEATHER_API_KEY=你的和风天气 Key
QWEATHER_API_HOST=你的和风天气 Host
ADMIN_INIT_PASSWORD=管理员初始密码
DEMO_SEED_ENABLED=true
```

然后重启：

```bash
cd /opt/ai-travel-agent
docker compose up -d --build
```

## 5. 访问

```text
http://你的服务器IP:8000
```

演示账号：`demo / demo123`。

## 6. 可选：域名 + HTTPS

1. 域名商加 A 记录：`travel.你的域名.com -> 服务器IP`。
2. 安装 Nginx 和证书：

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```

3. Nginx 配置见 `docs/GO_LIVE_CHECKLIST.md`。
4. 申请证书：

```bash
sudo certbot --nginx -d travel.你的域名.com
```

完成后访问 `https://travel.你的域名.com`。
