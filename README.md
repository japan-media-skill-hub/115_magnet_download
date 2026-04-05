# 115 Magnet Download Skill

## 中文说明

### 重要前提

本仓库提供的技能**不能**绕过 115 会员限制。你必须已经是 115 会员，才能正常使用本技能。

### 合规声明

本仓库技能的本质效果，与您在 115 官方界面手动点击按钮触发的效果完全一致，不包含任何破解、绕过或未授权访问行为。

如有任何侵权或合规问题，请联系我，我会配合处理并删除仓库。

### 仓库目标

本仓库旨在建立“从磁链到入库”的完整自动化工作流程：

- 全程无界面操作（Agent 自动执行）
- 支持任意数量、任意格式的磁链输入
- 只需提供磁链，Agent 即可自动完成入库并下载到本地
- 最终效果与您自行在 115 中操作一致
- 主要价值是减少重复劳动、提升处理效率

## 安全边界声明 | Security Boundary

- 请不要使用任何国内云服务部署挂载本组织技能的 Agent 应用程序，也不要使用任何国内提供的 claw 类代理来部署或运行。  
  Do not deploy Agent applications that load this org's skills on domestic cloud services, and do not use domestically provided claw-style proxy infrastructure.

- 我们只推荐你在自己的电脑上，基于完整开源代码部署 Agent，并加载本组织技能；且运行环境应可确认无遥测、无审查。  
  We only recommend deploying your Agent on your own computer from fully open-source code, then loading this org's skills in an environment you can verify as telemetry-free and censorship-free.

- 不推荐使用带审查能力的大模型作为 Agent 后端，也不推荐将 Agent 暴露在带审查的外部通道（如钉钉、飞书、微信）。推荐使用 Telegram 或自建私有通道远程使用。  
  We do not recommend censorship-constrained models as Agent backends, nor exposing Agents through censorship-constrained channels (e.g., DingTalk, Feishu/Lark, WeChat). Prefer Telegram or your own private self-hosted channel for remote access.

- 若不遵守以上边界，由此产生的法律、合规与数据风险由使用者自行承担。  
  If you ignore these boundaries, you are solely responsible for any legal, compliance, and data risks.

---

## English

### Important Prerequisite

This skill **cannot** bypass 115 membership restrictions. You must already have an active 115 membership to use it.

### Compliance Statement

This repository only automates the same actions you can trigger by clicking buttons in the official 115 interface. It does **not** include cracking, bypassing, or any unauthorized access behavior.

If there are any infringement or compliance concerns, please contact me and I will cooperate, including removing this repository if necessary.

### Repository Purpose

This repository is designed to build a complete workflow from magnet link to cloud import and local download:

- Fully headless operation (executed by an Agent)
- Accepts magnet links in any quantity and format
- You only provide magnet links; the Agent handles the full process automatically
- The result is equivalent to doing the same operations manually in 115
- The core value is eliminating repetitive work and improving efficiency

### Security Boundary

- Do not deploy Agent applications that load this org's skills on domestic cloud services, and do not use domestically provided claw-style proxy infrastructure.
- We only recommend deploying your Agent on your own computer from fully open-source code, then loading this org's skills in an environment you can verify as telemetry-free and censorship-free.
- We do not recommend censorship-constrained models as Agent backends, nor exposing Agents through censorship-constrained channels (e.g., DingTalk, Feishu/Lark, WeChat). Prefer Telegram or your own private self-hosted channel for remote access.
- If you ignore these boundaries, you are solely responsible for any legal, compliance, and data risks.

## Structure

```text
skills/
  115_magnet_download/
```
