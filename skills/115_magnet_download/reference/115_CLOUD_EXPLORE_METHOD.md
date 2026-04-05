# 115 网盘递归探索有效方法

这份说明只解决一件事：怎样稳定、低频率地，从任意 `cid` 开始，递归探索 115 网盘目录树，并拿到每个节点的名称、路径、大小、pickcode、更新时间，以及是否还能继续展开。

## 结论先说

有效方法不是“只看父目录列表里的 `m` 字段”，而是：

1. 用 cookie 建立 `requests.Session()`。
2. 调 `https://webapi.115.com/files?cid=<cid>&offset=<offset>&limit=<limit>` 列当前层。
3. 空结果或异常时，再回退到 `https://aps.115.com/natsort/files.php?...&cid=<cid>...`。
4. 对每个条目记录：`cid/fid/n/pc/s/sha/te/t/m/pid`。
5. 递归时不要只认 `m==1`：
   - `m==1` 一定继续探。
   - `m==0` 但没有 `fid`、没有 `size`、没有 `sha` 的条目，也要继续探。
   - 只有当条目已有明确文件事实时，才视为真正文件叶子。
6. 下载必须使用最终文件节点的 `pickcode`，不是父层条目的 `pickcode`。

## 为什么以前会错

- 把 `m=0` 当成“肯定是文件”，会漏掉大量伪目录。
- 把父层条目的 `pickcode` 当成最终文件 pickcode，会得到 `url=false` 或空直链。
- 手工覆盖 `Host` 头，在当前环境里会诱发 `my.115.com` 登录检查异常。
- 并发或无边界扫描太激进，容易把短时接口波动误判成“目录不存在”。

## 真实字段解释

- `cid`：目录型节点的展开入口；伪目录也常靠它继续探。
- `fid`：文件事实标记；出现它时，通常说明当前行就是最终文件。
- `pc`：pickcode；真正下载时要取最终文件行上的 `pc`。
- `s`：大小；父层伪目录常为空，子文件层才有真实字节数。
- `te`：更新时间 Unix 时间戳，优先用它。
- `t`：有时是字符串格式时间，有时也是时间戳，作为次选。
- `m`：官方目录标记，但不能单独作为是否继续递归的依据。

## 推荐探索节奏

- `pace_sec=1.0`：每次请求前至少等 1 秒。
- 单次先探 `max_depth=1` 或 `2`。
- 确认目标路径后，再对目标 `cid` 单独继续下钻。
- 不做高并发、不做全盘同时 BFS。

## 当前可直接使用的命令

从根目录开始探一层：

```bash
.venv/bin/python active_skills/115_magnet_download/scripts/explore_115_tree.py \
  --cookie-file tmp/115.cookies.current \
  --cid 0 \
  --max-depth 1 \
  --pace-sec 1.0 \
  --output-json plans/115_root_probe.json
```

从云下载目录继续探：

```bash
.venv/bin/python active_skills/115_magnet_download/scripts/explore_115_tree.py \
  --cookie-file tmp/115.cookies.current \
  --cid 1329509633840119134 \
  --max-depth 1 \
  --updated-within-hours 72 \
  --pace-sec 1.0 \
  --output-json plans/115_cloud_tree.json
```

对某个伪目录继续下钻，拿真实文件：

```bash
.venv/bin/python active_skills/115_magnet_download/scripts/explore_115_tree.py \
  --cookie-file tmp/115.cookies.current \
  --cid 3393703699380436550 \
  --max-depth 1 \
  --pace-sec 1.0 \
  --output-json plans/115_probe_fc2ppv_demo.json
```

## 输出结构怎么读

`explore_115_tree.py` 会输出这些核心字段：

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
- `mtime` / `mtime_unix`
- `depth`

## 一个实测事实

在当前账号里：

- 根目录下的 `最近接收`、`手机相册`、`SONE-684-C` 等条目，父层看起来都是 `m=0`，但实际上都能继续展开。
- `云下载/FC2PPV-4025269-C` 这一层父节点也是 `m=0`，继续探后才出现真正文件 `FC2PPV-4025269-C.mp4`，它的文件 pickcode 是 `dh970aijfnmecxxug`，而不是父节点 pickcode。

这就是 115 探索里最关键的坑。
