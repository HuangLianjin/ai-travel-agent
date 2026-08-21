# Contributing

感谢你愿意参与 Star Travel Agent 的改进。

## 开发流程

1. Fork 本仓库。
2. 新建功能分支：`feat/xxx` 或 `fix/xxx`。
3. 修改代码并补充测试。
4. 本地运行：

```bash
python -m pytest tests -q
python -m app.eval.runner --output data/eval_report.json
```

5. 提交 PR，描述改动内容和验证结果。

## 代码规范

- 保持现有 FastAPI + LangGraph 结构。
- 不提交 `.env`、`data/`、日志和上传文件。
- 新增外部 API 必须支持降级和缓存。
- 新增功能必须补测试或离线评测。
