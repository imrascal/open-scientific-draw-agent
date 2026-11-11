# 安全策略

## 不要提交的内容

- SSH 密码、私钥、API key；
- 内网 IP、主机名、共享目录路径；
- 真实渲染产物（可能含未发表数据）。

仓库里只有 `config/render.example.toml`，且只允许占位符。

## 如果密钥曾经泄漏

仅删除文件不够。请按顺序执行：

1. **先轮换**：改服务器密码或吊销密钥对；到服务商后台吊销并重建 API key。
2. 清理历史：`git filter-repo --replace-text secrets.txt`（或 BFG）。
3. force-push，并通知所有协作者重新 clone（旧副本推回来会把密钥带回）。
4. 若仓库已公开，把泄漏视为既成事实处理，只做第 1、3 步。

排查命令：

```bash
gitleaks detect --source . --log-opts="--all"
```

## 上报漏洞

请通过仓库 Issue 私下联系维护者，不要在公开 Issue 里贴可利用细节或真实凭据。
