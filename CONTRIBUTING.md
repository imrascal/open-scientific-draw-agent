# 贡献指南

## 开发环境

只需要 Python 3.11+ 和 Pillow。**不需要** Blender、GPU 或内网服务器：

```bash
python -m pip install Pillow
python -m unittest discover -s tests -v
```

## 合并请求要求

1. 新增行为必须带测试；测试不得依赖真实渲染、网络或私有服务；
2. 提交前自查：`git diff` 里不得出现真实主机名、账号、密码、API key；
3. 改动 `meta.json` 契约或退出码属于破坏性变更，需要在描述里单独说明；
4. 文档与代码同步：阈值、维度数、产物命名只能有一个事实来源。

## 报告问题

请附上：操作系统、Python 版本、`--renderer` 取值、`summary.json`（先删掉路径中的用户名）、完整报错。
不要粘贴真实凭据。
