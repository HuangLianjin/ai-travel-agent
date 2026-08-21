# 安全加固计划（已落地）

## 已完成

- 注册：手机号必填、格式校验、手机号唯一、后端生成 6 位验证码、验证通过才创建账号、注册限流
- 密码策略：8-64 位，必须含字母和数字，禁止弱密码和包含用户名
- 登录：IP 每分钟限流、用户名每小时限流、连续 5 次失败锁定 15 分钟
- Token：access 30 分钟 + refresh 7 天轮换，改密/登出可吊销
- 忘记密码：手机号验证码重置
- 管理员：不再自动创建 admin/admin123；`ADMIN_INIT_PASSWORD` 初始化并强制首次改密
- 2FA：TOTP 动态口令，登录校验，后台可绑定/解绑
- 权限：普通 admin 只审核内容，改状态/角色仅 super_admin
- 审计：login_audit 记录 IP、UA、成功/失败，管理员操作进 audit_logs
- 演示账号：默认关闭，`DEMO_SEED_ENABLED=true` 才创建 demo/demo123

## 验收命令

```bash
python -m pytest tests -q
```
