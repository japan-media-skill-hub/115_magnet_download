#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_DESCRIPTION = (
    "JAV 磁链队列（磁链保存地址：memory/jav_magnet_queue.toml；"
    "队列内磁链状态统一可标记为 pending/submitted/finished/failed）"
)


@dataclass
class QueueItem:
    time: str
    name: str
    magnet: str
    status: str
    remark: str
    block: str


def item_to_dict(item: QueueItem) -> dict[str, Any]:
    return {
        "time": item.time,
        "name": item.name,
        "status": item.status,
        "remark": item.remark,
        "magnet": item.magnet,
    }


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def ensure_queue_file(queue_file: Path) -> None:
    if queue_file.exists():
        return
    queue_file.parent.mkdir(parents=True, exist_ok=True)
    queue_file.write_text(
        "# JAV 磁链队列\n"
        "# 用途：记录用户准备下载的磁链任务\n"
        "# 说明：\n"
        "# - 仅做队列存储，不执行下载\n"
        "# - 所有字段都可直接被 Python 读取\n"
        "# - 磁链按顺序保存，即队列顺序\n"
        "# - 后续下载流程按此顺序消费\n"
        "# - 文件内容只追加，不随意重排\n\n"
        'version = "1"\n'
        f'updated_at = "{now_iso()}"\n'
        f'description = "{DEFAULT_DESCRIPTION}"\n',
        encoding="utf-8",
    )


def read_text(queue_file: Path) -> str:
    ensure_queue_file(queue_file)
    return queue_file.read_text(encoding="utf-8")


def parse_queue_toml(queue_text: str) -> list[QueueItem]:
    items: list[QueueItem] = []
    for raw in queue_text.split("[[queue]]"):
        if "name" not in raw or "magnet" not in raw:
            continue
        name_m = re.search(r'^name\s*=\s*"([^"]+)"', raw, flags=re.M)
        magnet_m = re.search(r'^magnet\s*=\s*"([^"]+)"', raw, flags=re.M)
        status_m = re.search(r'^status\s*=\s*"([^"]+)"', raw, flags=re.M)
        time_m = re.search(r'^time\s*=\s*"([^"]+)"', raw, flags=re.M)
        remark_m = re.search(r'^remark\s*=\s*"([^"]*)"', raw, flags=re.M)
        if not name_m or not magnet_m or not status_m or not time_m:
            continue
        items.append(
            QueueItem(
                time=time_m.group(1),
                name=name_m.group(1),
                magnet=magnet_m.group(1),
                status=status_m.group(1),
                remark=remark_m.group(1) if remark_m else "",
                block="[[queue]]" + raw,
            )
        )
    return items


def update_updated_at(queue_text: str) -> str:
    updated = f'updated_at = "{now_iso()}"'
    if re.search(r'^updated_at\s*=\s*"[^"]*"', queue_text, flags=re.M):
        return re.sub(r'^updated_at\s*=\s*"[^"]*"', updated, queue_text, flags=re.M)
    return queue_text.rstrip() + "\n" + updated + "\n"


def write_text(queue_file: Path, queue_text: str) -> None:
    queue_file.write_text(update_updated_at(queue_text), encoding="utf-8")


def parse_name_from_magnet(magnet: str) -> str:
    dn = ""
    m = re.search(r"[?&]dn=([^&]+)", magnet)
    if m:
        from urllib.parse import unquote

        dn = unquote(m.group(1))
    text = dn or magnet
    id_m = re.search(r"([A-Za-z]{2,10})[-_ ]?(\d{2,6})([-_ ]?[A-Za-z0-9]{1,4})?", text)
    if id_m:
        prefix = id_m.group(1).upper()
        num = id_m.group(2)
        suffix = (id_m.group(3) or "").replace("_", "-").replace(" ", "").strip("-")
        return f"{prefix}-{num}" + (f"-{suffix.upper()}" if suffix else "")
    return f"MAGNET-{int(datetime.now().timestamp())}"


def build_block(
    time_text: str, name: str, magnet: str, status: str, remark: str
) -> str:
    return (
        "\n[[queue]]\n"
        f'time = "{time_text}"\n'
        f'name = "{name}"\n'
        f'magnet = "{magnet}"\n'
        f'status = "{status}"\n'
        f'remark = "{remark}"\n'
    )


def replace_item_block(queue_text: str, old_item: QueueItem, new_block: str) -> str:
    return queue_text.replace(old_item.block, new_block, 1)


def filter_items(
    items: list[QueueItem],
    status: str = "",
    keyword: str = "",
    name: str = "",
) -> list[QueueItem]:
    out = items
    if status:
        allow = {x.strip() for x in status.split(",") if x.strip()}
        out = [x for x in out if x.status in allow]
    if keyword:
        low = keyword.lower()
        out = [
            x
            for x in out
            if low in x.name.lower()
            or low in x.magnet.lower()
            or low in x.remark.lower()
        ]
    if name:
        low = name.lower()
        out = [x for x in out if x.name.lower() == low]
    return out


def paginate_items(
    items: list[QueueItem], offset: int, limit: int
) -> tuple[list[QueueItem], int]:
    total = len(items)
    start = max(offset, 0)
    if limit <= 0:
        return items[start:], total
    return items[start : start + limit], total


def load_json_input(payload_file: str, use_stdin: bool) -> Any:
    if payload_file:
        return json.loads(Path(payload_file).read_text(encoding="utf-8"))
    if use_stdin:
        return json.loads(sys.stdin.read())
    raise ValueError("需要通过 --payload-file 或 --stdin-json 提供 JSON 输入")


def locate_items(
    items: list[QueueItem], payload_items: list[dict[str, Any]]
) -> list[tuple[QueueItem, dict[str, Any]]]:
    matched: list[tuple[QueueItem, dict[str, Any]]] = []
    used_indexes: set[int] = set()
    for payload in payload_items:
        target_magnet = str(payload.get("magnet") or "")
        target_name = str(payload.get("name") or "")
        target_time = str(payload.get("time") or "")
        for idx, item in enumerate(items):
            if idx in used_indexes:
                continue
            if target_magnet and item.magnet == target_magnet:
                matched.append((item, payload))
                used_indexes.add(idx)
                break
            if (
                target_name
                and target_time
                and item.name == target_name
                and item.time == target_time
            ):
                matched.append((item, payload))
                used_indexes.add(idx)
                break
    return matched


def cmd_stats(args: argparse.Namespace) -> int:
    items = parse_queue_toml(read_text(Path(args.queue_file)))
    counts: dict[str, int] = {}
    for item in items:
        counts[item.status] = counts.get(item.status, 0) + 1
    payload = {
        "queue_file": args.queue_file,
        "total": len(items),
        "counts": counts,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    items = parse_queue_toml(read_text(Path(args.queue_file)))
    items = filter_items(
        items,
        status=args.status,
        keyword=args.keyword,
        name=args.name,
    )
    page_items, total = paginate_items(items, int(args.offset), int(args.limit))
    payload = {
        "queue_file": args.queue_file,
        "count": total,
        "offset": int(args.offset),
        "limit": int(args.limit),
        "returned": len(page_items),
        "filters": {
            "status": args.status,
            "keyword": args.keyword,
            "name": args.name,
        },
        "items": [item_to_dict(x) for x in page_items],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    queue_file = Path(args.queue_file)
    queue_text = read_text(queue_file)
    items = parse_queue_toml(queue_text)
    seen = {x.magnet for x in items}

    magnets: list[str] = [m.strip() for m in (args.magnet or []) if m.strip()]
    if args.magnet_file:
        for line in Path(args.magnet_file).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("magnet:?xt=urn:btih:"):
                magnets.append(line)

    added = 0
    skipped = 0
    now = now_iso()
    for magnet in magnets:
        if magnet in seen:
            skipped += 1
            continue
        name = (
            args.name
            if args.name and len(magnets) == 1
            else parse_name_from_magnet(magnet)
        )
        queue_text += build_block(now, name, magnet, args.status, args.remark)
        seen.add(magnet)
        added += 1

    write_text(queue_file, queue_text)
    print(
        json.dumps({"added": added, "skipped": skipped}, ensure_ascii=False, indent=2)
    )
    return 0


def cmd_set_status(args: argparse.Namespace) -> int:
    queue_file = Path(args.queue_file)
    queue_text = read_text(queue_file)
    items = parse_queue_toml(queue_text)
    matched = filter_items(
        items,
        status=args.from_status,
        keyword=args.keyword,
        name=args.name,
    )
    matched, _ = paginate_items(matched, int(args.offset), int(args.limit))
    changed = 0
    for item in matched:
        new_block = build_block(
            item.time,
            item.name,
            item.magnet,
            args.to_status,
            args.remark if args.remark_set else item.remark,
        )
        queue_text = replace_item_block(queue_text, item, new_block)
        changed += 1
    write_text(queue_file, queue_text)
    print(
        json.dumps(
            {"changed": changed, "to_status": args.to_status},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_apply_json(args: argparse.Namespace) -> int:
    queue_file = Path(args.queue_file)
    queue_text = read_text(queue_file)
    items = parse_queue_toml(queue_text)
    payload = load_json_input(args.payload_file, args.stdin_json)
    payload_items = (
        payload.get("items", payload) if isinstance(payload, dict) else payload
    )
    if not isinstance(payload_items, list):
        raise ValueError("输入 JSON 必须是数组，或包含 items 数组")

    matched = locate_items(items, payload_items)
    changed = 0
    for item, row in matched:
        new_status = str(row.get("status") or item.status)
        new_remark = item.remark
        if args.remark_from_json and "remark" in row:
            new_remark = str(row.get("remark") or "")
        elif args.remark:
            new_remark = args.remark
        new_block = build_block(
            item.time, item.name, item.magnet, new_status, new_remark
        )
        queue_text = replace_item_block(queue_text, item, new_block)
        changed += 1

    write_text(queue_file, queue_text)
    print(
        json.dumps(
            {
                "changed": changed,
                "matched": len(matched),
                "input_items": len(payload_items),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_cleanup_status(args: argparse.Namespace) -> int:
    queue_file = Path(args.queue_file)
    queue_text = read_text(queue_file)
    items = parse_queue_toml(queue_text)
    remove_statuses = {x.strip() for x in args.status.split(",") if x.strip()}
    kept: list[QueueItem] = [x for x in items if x.status not in remove_statuses]
    removed = len(items) - len(kept)

    header_lines: list[str] = []
    for line in queue_text.splitlines():
        if line.startswith("[[queue]]"):
            break
        header_lines.append(line)
    new_text = "\n".join(header_lines).rstrip() + "\n"
    for item in kept:
        new_text += build_block(
            item.time, item.name, item.magnet, item.status, item.remark
        )
    write_text(queue_file, new_text.rstrip() + "\n")
    print(
        json.dumps(
            {"removed": removed, "kept": len(kept)}, ensure_ascii=False, indent=2
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="管理 JAV 磁链队列文件")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("stats", help="查看队列统计")
    p.add_argument("--queue-file", required=True)
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("list", help="筛选列出队列条目")
    p.add_argument("--queue-file", required=True)
    p.add_argument("--status", default="")
    p.add_argument("--keyword", default="")
    p.add_argument("--name", default="")
    p.add_argument("--offset", default="0")
    p.add_argument("--limit", default="0")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("add", help="追加磁链到队列")
    p.add_argument("--queue-file", required=True)
    p.add_argument("--magnet", nargs="*", default=[])
    p.add_argument("--magnet-file")
    p.add_argument("--name", default="")
    p.add_argument("--status", default="pending")
    p.add_argument("--remark", default="")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("set-status", help="批量更新状态")
    p.add_argument("--queue-file", required=True)
    p.add_argument("--to-status", required=True)
    p.add_argument("--from-status", default="")
    p.add_argument("--keyword", default="")
    p.add_argument("--name", default="")
    p.add_argument("--offset", default="0")
    p.add_argument("--limit", default="0")
    p.add_argument("--remark", default="")
    p.add_argument("--remark-set", action="store_true")
    p.set_defaults(func=cmd_set_status)

    p = sub.add_parser("cleanup-status", help="删除指定状态条目")
    p.add_argument("--queue-file", required=True)
    p.add_argument("--status", required=True, help="如 finished 或 finished,failed")
    p.set_defaults(func=cmd_cleanup_status)

    p = sub.add_parser("apply-json", help="根据 JSON 批量写回状态/备注")
    p.add_argument("--queue-file", required=True)
    p.add_argument("--payload-file", default="")
    p.add_argument("--stdin-json", action="store_true")
    p.add_argument("--remark", default="")
    p.add_argument("--remark-from-json", action="store_true")
    p.set_defaults(func=cmd_apply_json)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
