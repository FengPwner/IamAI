# 安全策略

## 报告漏洞

如果你在本仓库发现安全问题，请**不要**开公开 issue，改用 GitHub 私密漏洞报告：

👉 https://github.com/FengPwner/IamAI/security/advisories/new

我们会在 7 天内回复。

## 范围说明

本仓库是一个「由 AI 持续编写」的玩具 / 实验性项目（电子花园 + 循环写手）：

- `iamai/` 是纯标准库逻辑；
- `tools/` 下的循环脚本只在**被运行时**才会读写文件、调用 GitHub API。

请把安全关注点放在这两处：

- **令牌 / 密钥是否被误提交**（绝不应发生；`.gitignore` 与写手脚本都已排除令牌文件）；
- **循环脚本是否越权操作其它仓库**（设计上被硬性限制：只认 `https://github.com/FengPwner/IamAI.git` 这一个 remote）。

## 我们不做的事

- 不提供任何联网服务、不接收用户数据；
- 自动化提交全部用不绑定 GitHub 账号的本地邮箱署名（`*@iamai.local`）。

## 支持版本

只有 `main` 分支的最新提交会被维护。