---
name: 115_magnet_download
description: 独立处理 115 Cookie、离线磁链提交、云盘遍历探索、pickcode 下载与 aria2 托管；探索阶段只提供事实遍历，不预设文件落点。
---

# 115 Magnet Download Skill

这个技能现在是**独立技能**。运行时逻辑以 `active_skills/115_magnet_download/scripts/` 为准，不再依赖 `repo/` 里的脚本才能工作。`repo/` 仅保留为历史参考，不是技能事实来源。

## 渐进式披露

默认先看本文件，只按这里的最小必要流程执行。

当出现这些情况时，再去读参考文档：

- 115 返回结构和直觉不一致
- `m=0` 条目是否还能继续展开拿不准
- pickcode、`fid`、`cid`、`te` 的含义混淆
- 遇到接口波动，不确定该如何回退或限速

参考文档位置：`active_skills/115_magnet_download/reference/115_CLOUD_EXPLORE_METHOD.md`

这个安排是刻意的：先用最少规则完成任务，只有遇到阻碍或不明处时，才展开读更细的方法说明。

## 技能定位

适合这些请求：

- “给你 cookie，帮我加磁链”
- “先把磁链存进 `jav_magnet_queue.toml`，晚点再分批提交”
- “检查 115 cookie 是否还能用”
- “从根目录开始探索 115 网盘结构”
- “给我找某个目录/文件真实 pickcode”
- “把确认好的文件交给 aria2 下载”

## 当前原则

- 探索阶段只做**遍历与事实采集**，不预设“文件一定在云下载/磁链名目录下”。
- 任何“寻找之前磁链添加的文件”的动作，都必须先走遍历脚本看真实树，再由 Agent 或用户判断目标条目。
- 下载阶段必须明确：**115 下载依赖最终文件节点的 `pickcode`**，目录 pickcode 或父层伪目录 pickcode 不可靠。
- 委托下载前必须**先批量创建计划里的 `dest_dir` 目录**，再调用 aria2，避免因目录不存在导致任务中止。
- 探查拿到大视频 `pickcode` 后，必须把 pickcode 反写到 `memory/jav_magnet_queue.toml` 对应条目（优先写 `remark`；多视频用分号分隔），用于下次免探索快速重试。
- Cookie 默认持久化；除非失效或用户明确要求，不主动清空。
- 探索必须限速，默认每请求前等待 `1.0s`，避免过快刮取。
- 115 的 `m` 字段不能单独判断目录/文件；要结合 `fid`、`size`、`sha` 和实际是否可继续列举。
- `memory/jav_magnet_queue.toml` 必须由脚本管理，不再依赖大模型直接手改大文件。

## 已纠正的错误经验

这些旧说法现在视为错误，不能再作为技能依据：

- 错误：可以直接按“云下载/磁链名称目录”去取文件。
- 错误：父层列表里 `m=0` 就等于最终文件。
- 错误：父层条目的 pickcode 可以直接用于下载。
- 错误：探索脚本可以直接替用户认定哪个文件就是本次磁链对应主片。
- 错误：登录检查时手工覆盖 `Host` 头更稳。
- 错误：`queue-by-plan` 的 `dest_dir` 可以随意生成，只要 pickcode 正确就一定能委托成功。
- 错误：一旦委托脚本报错，只看返回码就够了。需要把 aria2/委托阶段的 stdio 错误完整保留到 plan/日志里，便于快速定位是路径、权限还是直链问题。
- 错误：生成下载计划时不能回看之前成功的计划模板。遇到错误计划或下载失败，应优先检索已成功的历史计划，复用其中正确的 `dest_dir`、目录层级与命名模板，再修正当前计划。

## 计划与委托的故障恢复

当 `queue-by-plan` 或 aria2 返回错误时：

1. 保留脚本的 stdout/stderr，不要只看退出码。
2. 先判断是 `dest_dir`、权限、路径不存在，还是 pickcode/直链失效。
3. 若属于路径或模板问题，优先搜索历史成功计划（`plans/*`）找出同类任务的正确目录模板。
4. 以成功计划为基准，修正当前计划后再重试。
5. 错误计划文件若已确认无效，可移除或归档，避免下次误用。


这些旧说法现在视为错误，不能再作为技能依据：

- 错误：可以直接按“云下载/磁链名称目录”去取文件。
- 错误：父层列表里 `m=0` 就等于最终文件。
- 错误：父层条目的 pickcode 可以直接用于下载。
- 错误：探索脚本可以直接替用户认定哪个文件就是本次磁链对应主片。
- 错误：登录检查时手工覆盖 `Host` 头更稳。

## 技能目录

- 说明：`active_skills/115_magnet_download/SKILL.md`
- 参考：`active_skills/115_magnet_download/reference/115_CLOUD_EXPLORE_METHOD.md`
- 脚本：
  - `active_skills/115_magnet_download/scripts/skill_115_common.py`
  - `active_skills/115_magnet_download/scripts/magnet_queue.py`
  - `active_skills/115_magnet_download/scripts/explore_115_tree.py`
  - `active_skills/115_magnet_download/scripts/pipeline_115_magnet_download.py`
  - `active_skills/115_magnet_download/scripts/download_plan_builder.py`

## 核心能力

### 1) Cookie 管理

- 保存 Cookie
- 检查 Cookie 是否可登录
- 复用现有 Cookie，不频繁要求用户重给

### 2) 磁链队列管理

- 管理 `memory/jav_magnet_queue.toml`
- 追加磁链、避免重复、筛选、统计、批量改状态、清理已完成条目
- 支持先长期积累，再按批次提交到 115
- `magnet_queue.py` 的 `list` 输出必须视为标准分页 JSON，可被 Agent 直接读、写文件、或通过管道再喂回 `apply-json`

### 3) 离线磁链提交

- 把 pending 磁链提交到 115 离线任务
- 只把“提交成功”视为 `submitted`
- 不把“提交成功”误判成“文件已出现”
- 支持 `--limit 10` 这类批次提交

### 4) 云盘结构遍历

- 从任意 `cid` 开始遍历
- 输出名称、路径、大小、`cid`、`fid`、pickcode、更新时间
- 对伪目录继续下钻
- 只输出事实，不自动认定目标文件

### 5) 下载托管

- 在**已经明确文件 pickcode**后，调用 downurl
- 把直链交给 aria2
- NFS 环境强制 `file-allocation=none`

### 6) aria2c 专用记忆

### 7) 115 同步状态记忆（新增）

- 记忆文件：`memory/115_sync_state.toml`
- 用途：记录两类关键状态，减少重复探查、提高增量发现可靠性：
  1. `cloud_cid`：云下载目录 cid（下次优先从该 cid 探查，不必先从 root `cid=0` 找）
  2. `latest_delegated_mtime`：上一轮成功委托给 aria2 的最晚文件更新时间（水位）
- 使用约定：
  - 每次成功委托后更新该文件中的水位时间
  - 每次探查前先读取该文件，默认以 `cloud_cid` 作为起点并参考水位做增量判断

- 专门使用 `memory/aria2c_links.md` 记录 aria2c 的连接参数、RPC 地址、认证方式和容器标识
- 该文件只存放 aria2c 专用信息，不与常规任务记忆混写
- 当前已知连接信息：
  - RPC 主机：`<ARIA2_RPC_HOST>`
  - RPC 端口：`6800`
  - RPC 路径：`/jsonrpc`
  - 容器/镜像标识：`<YOUR_ARIA2_CONTAINER>`
- 若后续 aria2c 参数变化，优先更新该专用记忆文件

## 推荐流程

### A. 保存并检查 Cookie

```bash
.venv/bin/python active_skills/115_magnet_download/scripts/pipeline_115_magnet_download.py \
  save-cookie --cookie-text "<cookie>" --cookie-file tmp/115.cookies.current

.venv/bin/python -c "from pathlib import Path; import sys; sys.path.insert(0, 'active_skills/115_magnet_download/scripts'); from skill_115_common import build_session, ensure_login; s=build_session(Path('tmp/115.cookies.current')); ensure_login(s); print('Cookie登录状态: OK')"
```

### B. 管理磁链队列

查看统计：

```bash
.venv/bin/python active_skills/115_magnet_download/scripts/magnet_queue.py \
  stats --queue-file memory/jav_magnet_queue.toml
```

追加磁链：

```bash
.venv/bin/python active_skills/115_magnet_download/scripts/magnet_queue.py \
  add --queue-file memory/jav_magnet_queue.toml --magnet "magnet:?xt=urn:btih:..."
```

筛出待提交前 10 条：

```bash
.venv/bin/python active_skills/115_magnet_download/scripts/magnet_queue.py \
  list --queue-file memory/jav_magnet_queue.toml --status pending --offset 0 --limit 10
```

第二批可直接改 `--offset 10 --limit 10`。

`list` 的标准输出结构：

```json
{
  "queue_file": "memory/jav_magnet_queue.toml",
  "count": 123,
  "offset": 0,
  "limit": 10,
  "returned": 10,
  "filters": {
    "status": "pending",
    "keyword": "",
    "name": ""
  },
  "items": [
    {
      "time": "2026-03-29T11:00:00+08:00",
      "name": "ABP-123",
      "status": "pending",
      "remark": "",
      "magnet": "magnet:?xt=urn:btih:..."
    }
  ]
}
```

这意味着 Agent 可以灵活选择：

- 直接读标准输出
- 重定向到文件再分析
- 把 `items` 作为 JSON 文件/标准输入，再交给 `apply-json` 批量写回状态

用 JSON 批量写回状态的两种方式：

```bash
.venv/bin/python active_skills/115_magnet_download/scripts/magnet_queue.py \
  apply-json --queue-file memory/jav_magnet_queue.toml --payload-file plans/batch_result.json
```

```bash
cat plans/batch_result.json | .venv/bin/python active_skills/115_magnet_download/scripts/magnet_queue.py \
  apply-json --queue-file memory/jav_magnet_queue.toml --stdin-json
```

清理已完成条目：

```bash
.venv/bin/python active_skills/115_magnet_download/scripts/magnet_queue.py \
  cleanup-status --queue-file memory/jav_magnet_queue.toml --status finished
```

### C. 分批提交 pending 到 115

```bash
.venv/bin/python active_skills/115_magnet_download/scripts/pipeline_115_magnet_download.py \
  submit-pending \
  --queue-file memory/jav_magnet_queue.toml \
  --cookie-file tmp/115.cookies.current \
  --limit 10 \
  --result-json plans/115_submit_batch_01.json
```

`submit-pending` 只负责做两件事：

- 真正提交选中的 pending 磁链到 115
- 打印摘要并把详情 JSON 写到文件，供 Agent 后续判断与批量写回队列状态

**提交成功后，必须再执行队列状态回写：**

- 将本批次中 `success=true` 的条目标记为 `submitted`
- 若 `duplicate_as_success=true`，同样视为 `submitted`
- 这一步是提交流程的一部分，不能省略

推荐顺序：

1. 先 `submit-pending`
2. 再用 `apply-json` 或等价脚本把成功项写回 `submitted`
3. 最后再做下一批

`result-json` 里会包含：

- `total_pending_selected`
- `submit_ok`
- `submit_fail`
- `details`

其中 `details` 每项至少含：

- `name`
- `magnet`
- `success`
- `duplicate_as_success`
- `reason`

示例回写：

```bash
.venv/bin/python active_skills/115_magnet_download/scripts/magnet_queue.py \
  apply-json --queue-file memory/jav_magnet_queue.toml --payload-file plans/115_submit_batch_01.json
```

或将结果重定向后再回写。
- `raw`

规则说明：

- 115 返回“已存在/重复”时，脚本按成功处理，即 `duplicate_as_success=true`
- 队列状态写回可以由 Agent 读取该 JSON 后，调用 `magnet_queue.py apply-json` 完成
- 这样更符合技能原则：脚本提供稳定接口，Agent 决定如何编排

### D. 探索真实目录树

从根目录探索：

```bash
.venv/bin/python active_skills/115_magnet_download/scripts/explore_115_tree.py \
  --cookie-file tmp/115.cookies.current \
  --cid 0 \
  --max-depth 1 \
  --pace-sec 0.3 \
  --output-json plans/115_root_probe.json
```

从某个可疑节点继续下钻：

```bash
.venv/bin/python active_skills/115_magnet_download/scripts/explore_115_tree.py \
  --cookie-file tmp/115.cookies.current \
  --cid <目标cid> \
  --max-depth 1 \
  --pace-sec 0.3 \
  --output-json plans/115_subtree_probe.json
```

### E. 确认最终文件 pickcode 后再下载

先说明清楚：下载不是靠目录名，不是靠磁链名，也不是靠父层 pickcode；而是靠**最终文件行上的 pickcode**。

当你已经从遍历结果里拿到目标文件 pickcode 后，再走下载：

```bash
.venv/bin/python active_skills/115_magnet_download/scripts/pipeline_115_magnet_download.py \
  queue-by-plan \
  --plan-json plans/115_download_plan.json \
  --cookie-file tmp/115.cookies.current \
  --aria2-rpc http://127.0.0.1:6800/jsonrpc \
  --aria2-secret <ARIA2_SECRET> \
  --wait-before-downurl 30
```

## 对“寻找磁链对应文件”的明确约束

- 这个技能**不再提供**“按磁链名直接猜目录并一次性认定目标文件”的方法说明。
- `explore_115_tree.py` 的职责只有：遍历、列举、输出事实。
- `magnet_queue.py` 的职责只有：提供可组合的队列读写接口，不替 Agent 固化批次策略。
- 是否某个文件与某次磁链对应，必须建立在真实目录树结果之上，由人或 Agent 结合名称、大小、更新时间、内容结构再判断。
- 若探索结果不够，就继续对具体 `cid` 下钻，而不是回到“猜路径”。

## 输出字段约定

`explore_115_tree.py` 输出重点字段：

- `name`
- `path`
- `cid`
- `fid`
- `parent_cid`
- `pickcode`
- `raw_m`
- `is_dir`
- `is_file`
- `expandable`
- `size`
- `sha`
- `mtime`
- `mtime_unix`
- `depth`

## 列表查询排序经验（已固化到脚本）

- 已确认在 `webapi.115.com/files` 上，以下参数组合可稳定用于按更新时间排序并分页：
  - `aid=1`
  - `cid=<目录cid>`
  - `o=user_utime`
  - `asc=1`（按你当前实测：更新时间逆序，越新越靠前）
  - `offset=<分页偏移>`
  - `limit=<每页条数>`
  - 其余保留稳定参数：`show_dir=1,natsort=1,record_open_time=1,count_folders=1,format=json` 等

- 当前技能脚本已统一优先使用该参数组合，目标是：
  - 每次查询都按“更新越晚越在前面”的顺序返回
  - 支持明确分页（`offset+limit`）

## 常见判断规则

- 有 `fid` 或明确 `size/sha`：通常是最终文件。
- `m=0` 且 `size=0`、`fid` 空：不要立刻当文件，优先尝试继续列举其 `cid`。
- `expandable=true`：说明脚本已实测该节点还能继续取子项。
- 更新时间优先看 `te`。

## aria2 与下载注意事项

- 115 直链有时效，401/403 需重取。
- `url=false` 常见原因是拿错 pickcode，尤其是用了目录或父节点的 pickcode。
- NFS 场景必须用 `file-allocation=none`，否则可能报 `errorCode=17`。

## 低噪声工作方式

- 一次只验证一个假设。
- 先探浅层，再探目标子树。
- 遇到短时异常，优先原地重试，不并发切多条探索路径。
- 如果不确定字段语义或目录行为，再读 `reference/115_CLOUD_EXPLORE_METHOD.md`。
