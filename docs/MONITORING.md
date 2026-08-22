# 监控告警配置

线上进程由 crontab 每 5 分钟执行一次健康检查，请求 `/api/health`；连续失败时通过 PushPlus 推送到微信（可选同时推送到企业微信机器人）。

## 1. 申请 PushPlus

1. 打开 https://www.pushplus.plus ，用微信扫码登录。
2. 完成实名认证后，在“一对一推送”页面复制 token。
3. 把 token 填到 `.env`：

```bash
PUSHPLUS_TOKEN=你的token
```

PushPlus 免费版可满足开发/面试演示场景；企业微信机器人 `WECHAT_WEBHOOK` 为可选第二通道。

## 2. 配置定时任务

```bash
crontab -e
```

添加：

```cron
*/5 * * * * /usr/bin/python3 /root/ai-travel-agent/scripts/monitor_health.py >> /root/health_check.log 2>&1
```

## 3. 验证

```bash
curl -s http://127.0.0.1:8000/api/health
# 收到 JSON 且 code=0 表示服务正常

# 手动触发一条测试消息
python3 - <<'PY'
import json, urllib.request
token = "你的token"
payload = json.dumps({"token": token, "title": "星旅 Agent 监控测试", "content": "收到即表示告警链路正常", "template": "txt"}).encode()
req = urllib.request.Request("https://www.pushplus.plus/send", data=payload, headers={"Content-Type": "application/json"})
print(urllib.request.urlopen(req, timeout=15).read().decode())
PY
```

返回 `code: 200` 后，微信会收到一条“星旅 Agent 监控测试”消息，说明告警链路已打通。
