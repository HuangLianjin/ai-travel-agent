# Security Policy

## Reporting a Vulnerability

请通过 GitHub Issues 私密报告，或在 Issue 中标注 `security`。

请勿在公开 Issue 中粘贴真实 API Key、数据库内容或用户数据。

## Key 管理

- `.env` 已被 `.gitignore` 忽略，禁止提交。
- 线上环境使用平台环境变量注入，不要把 Key 写入仓库。
- 如果 Key 意外提交，请立即到对应平台重置 Key。
