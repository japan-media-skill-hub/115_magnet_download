#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import time
try:
    import tomllib
except ModuleNotFoundError:  # py<3.11
    import tomli as tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from skill_115_common import (
    DEFAULT_HEADERS,
    add_tasks,
    build_session,
    cookie_header_value,
    ensure_login,
    extract_url_and_name,
    get_download_entry,
    get_sign_time,
    get_uid,
)

VIDEO_EXTS = {
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".wmv",
    ".flv",
    ".m4v",
    ".ts",
    ".m2ts",
    ".mpg",
    ".mpeg",
    ".rmvb",
}


@dataclass
class QueueItem:
    name: str
    magnet: str
    status: str
    time: str
    block: str


def parse_queue_toml(queue_text: str) -> list[QueueItem]:
    items: list[QueueItem] = []
    for raw in queue_text.split("[[queue]]"):
        if "name" not in raw or "magnet" not in raw:
            continue
        name_m = re.search(r'^name\s*=\s*"([^"]+)"', raw, flags=re.M)
        magnet_m = re.search(r'^magnet\s*=\s*"([^"]+)"', raw, flags=re.M)
        status_m = re.search(r'^status\s*=\s*"([^"]+)"', raw, flags=re.M)
        time_m = re.search(r'^time\s*=\s*"([^"]+)"', raw, flags=re.M)
        if not name_m or not magnet_m or not status_m or not time_m:
            continue
        items.append(
            QueueItem(
                name=name_m.group(1),
                magnet=magnet_m.group(1),
                status=status_m.group(1),
                time=time_m.group(1),
                block="[[queue]]" + raw,
            )
        )
    return items


def replace_status_once(queue_text: str, item: QueueItem, new_status: str) -> str:
    old = item.block
    new = old.replace(f'status = "{item.status}"', f'status = "{new_status}"', 1)
    return queue_text.replace(old, new, 1)


def update_updated_at(queue_text: str) -> str:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    return re.sub(
        r'^updated_at\s*=\s*"[^"]*"', f'updated_at = "{now}"', queue_text, flags=re.M
    )


def chunked(seq: list[str], n: int) -> list[list[str]]:
    return [seq[i : i + n] for i in range(0, len(seq), n)]


def is_duplicate_offline_result(row: dict[str, Any]) -> bool:
    text = " ".join(
        str(row.get(key) or "")
        for key in ["error_msg", "message", "msg", "errcode", "name"]
    ).lower()
    markers = ["exist", "exists", "重复", "已存在", "already"]
    return any(marker in text for marker in markers)


def iso_from_unix(ts: Any) -> str:
    try:
        v = int(str(ts))
        if v <= 0:
            return ""
        return datetime.fromtimestamp(v).astimezone().isoformat(timespec="seconds")
    except Exception:
        return ""


def unix_from_iso(iso_text: str) -> int:
    try:
        return int(datetime.fromisoformat(iso_text).timestamp())
    except Exception:
        return 0


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
    return f"MAGNET-{int(time.time())}"


def sanitize_dir_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r"[\\/:*?\"<>|]", "-", name)
    name = re.sub(r"\.mp4$|\.mkv$|\.avi$|\.mov$|\.wmv$", "", name, flags=re.I)
    return name.strip(" .-") or "unknown"


def detect_series_key(base_text: str) -> str:
    # 例如 IPX-811-1 / IPX-811-2 => IPX-811
    m = re.search(r"([A-Za-z]{2,10})[-_ ]?(\d{2,6})[-_ ](\d{1,2})$", base_text)
    if m:
        return f"{m.group(1).upper()}-{m.group(2)}"
    m2 = re.search(r"([A-Za-z]{2,10})[-_ ]?(\d{2,6})", base_text)
    if m2:
        return f"{m2.group(1).upper()}-{m2.group(2)}"
    return sanitize_dir_name(base_text)


def build_cookie_session(cookie_file: Path) -> tuple[requests.Session, str]:
    session = build_session(cookie_file)
    ensure_login(session)
    return session, cookie_header_value(session.cookies)


def load_sync_state(sync_state_file: Path) -> dict[str, Any]:
    if not sync_state_file.exists():
        return {}
    try:
        return tomllib.loads(sync_state_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_aria2_safe_output_root(sync_state_file: Path, fallback_root: str) -> str:
    state = load_sync_state(sync_state_file)
    aria2_conf = state.get("aria2", {}) if isinstance(state, dict) else {}
    allowed_roots = aria2_conf.get("allowed_output_roots", [])
    if isinstance(allowed_roots, list) and allowed_roots:
        first = str(allowed_roots[0]).strip()
        if first:
            return first
    host_mount = str(aria2_conf.get("host_mount_root") or "").strip()
    if host_mount:
        return host_mount
    return fallback_root


def get_allowed_output_roots(sync_state_file: Path) -> list[str]:
    state = load_sync_state(sync_state_file)
    aria2_conf = state.get("aria2", {}) if isinstance(state, dict) else {}
    roots = aria2_conf.get("allowed_output_roots", [])
    out: list[str] = []
    if isinstance(roots, list):
        for r in roots:
            s = str(r).strip()
            if s:
                out.append(s.rstrip("/"))
    return out


def ensure_dest_dir_allowed(dest_dir: str, allowed_roots: list[str]) -> tuple[bool, str]:
    d = str(dest_dir).strip().rstrip("/")
    if not d:
        return False, "empty_dest_dir"
    if not allowed_roots:
        return False, "allowed_output_roots_not_configured"
    for root in allowed_roots:
        if d == root or d.startswith(root + "/"):
            return True, ""
    return False, f"dest_dir_not_allowed: {d}"


def list_children(
    session: requests.Session, cid: str, limit: int = 200
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    offset = 0
    while True:
        rows: list[dict[str, Any]] = []
        for attempt in range(3):
            try:
                url = (
                    "https://webapi.115.com/files"
                    f"?aid=1&cid={cid}"
                    "&o=user_utime&asc=1"
                    f"&offset={offset}"
                    "&show_dir=1"
                    f"&limit={limit}"
                    "&code=&scid=&snap=0&natsort=1&record_open_time=1&count_folders=1"
                    "&type=&source=&format=json&star=&is_share=&suffix=&custom_order=&fc_mix="
                )
                r = session.get(url, timeout=15)
                r.raise_for_status()
                rows = r.json().get("data", [])
                if not rows:
                    alt_url = (
                        "https://aps.115.com/natsort/files.php"
                        f"?aid=1&cid={cid}&o=file_name&asc=1&offset={offset}"
                        f"&show_dir=1&limit={limit}&code=&scid=&snap=0&natsort=1"
                        "&record_open_time=1&count_folders=1&type=&source=&format=json"
                    )
                    r = session.get(alt_url, timeout=15)
                    r.raise_for_status()
                    rows = r.json().get("data", [])
                break
            except Exception:
                if attempt == 2:
                    return out
                time.sleep(1 + attempt)
        if not rows:
            break
        out.extend(rows)
        offset += limit
        if len(rows) < limit:
            break
    return out


def get_cloud_cid(session: requests.Session) -> str:
    rows = list_children(session, "0")
    for x in rows:
        if x.get("n") == "云下载":
            return str(x.get("cid"))
    raise RuntimeError("未找到云下载目录")


def to_entry(row: dict[str, Any], parent_cid: str, level: int) -> dict[str, Any]:
    is_dir = int(row.get("m", 0)) == 1
    return {
        "name": str(row.get("n", "")),
        "cid": str(row.get("cid", "")),
        "pc": str(row.get("pc", "")),
        "is_dir": is_dir,
        "size": int(row.get("s") or 0),
        "mtime_unix": str(row.get("te") or row.get("t") or ""),
        "mtime": iso_from_unix(row.get("te") or row.get("t") or ""),
        "parent_cid": parent_cid,
        "level": level,
    }


def recurse_tree(
    session: requests.Session, cid: str, level: int, max_depth: int
) -> list[dict[str, Any]]:
    if level > max_depth:
        return []
    rows = list_children(session, cid)
    out: list[dict[str, Any]] = []
    for r in rows:
        e = to_entry(r, cid, level)
        out.append(e)
        if e["is_dir"]:
            out.extend(recurse_tree(session, e["cid"], level + 1, max_depth))
    return out


def is_video_file(name: str, size: int) -> bool:
    ext = Path(name).suffix.lower()
    if ext in VIDEO_EXTS:
        return True
    return size > 300 * 1024 * 1024


def aria2_call(
    rpc_url: str, rpc_secret: str, method: str, params: list[Any]
) -> dict[str, Any]:
    payload = {
        "jsonrpc": "2.0",
        "id": f"115-{int(time.time() * 1000)}",
        "method": method,
        "params": [f"token:{rpc_secret}"] + params,
    }
    r = requests.post(rpc_url, json=payload, timeout=20)
    r.raise_for_status()
    return r.json()


def cmd_save_cookie(args: argparse.Namespace) -> int:
    path = Path(args.cookie_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(args.cookie_text.strip() + "\n", encoding="utf-8")
    print(f"saved={path}")
    return 0


def cmd_add_magnets(args: argparse.Namespace) -> int:
    queue_file = Path(args.queue_file)
    queue_file.parent.mkdir(parents=True, exist_ok=True)
    text = (
        queue_file.read_text(encoding="utf-8")
        if queue_file.exists()
        else 'version = "1"\n'
    )

    magnets: list[str] = []
    magnets.extend([m.strip() for m in (args.magnet or []) if m.strip()])
    if args.magnet_file:
        for line in Path(args.magnet_file).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("magnet:?xt=urn:btih:"):
                magnets.append(line)
    if not magnets:
        print("add=0")
        return 0

    now = datetime.now().astimezone().isoformat(timespec="seconds")
    parts = []
    for mg in magnets:
        name = parse_name_from_magnet(mg)
        parts.append(
            "\n[[queue]]\n"
            f'time = "{now}"\n'
            f'name = "{name}"\n'
            f'magnet = "{mg}"\n'
            'status = "pending"\n'
            'remark = ""\n'
        )
    text += "".join(parts)
    text = update_updated_at(text)
    queue_file.write_text(text, encoding="utf-8")
    print(f"add={len(magnets)}")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    queue_file = Path(args.queue_file)
    items = parse_queue_toml(queue_file.read_text(encoding="utf-8"))
    plan = {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "queue_file": str(queue_file),
        "counts": {
            "pending": len([x for x in items if x.status == "pending"]),
            "submitted": len([x for x in items if x.status == "submitted"]),
            "finished": len([x for x in items if x.status == "finished"]),
        },
        "pending": [
            {"name": x.name, "magnet": x.magnet} for x in items if x.status == "pending"
        ],
        "submitted": [
            {"name": x.name, "time": x.time} for x in items if x.status == "submitted"
        ],
    }
    plan_dir = Path(args.plan_dir)
    plan_dir.mkdir(parents=True, exist_ok=True)
    out = (
        plan_dir
        / f"115_magnet_download_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)
    return 0


def cmd_submit_pending(args: argparse.Namespace) -> int:
    queue_file = Path(args.queue_file)
    cookie_file = Path(args.cookie_file)
    queue_text = queue_file.read_text(encoding="utf-8")
    items = parse_queue_toml(queue_text)
    pending = [i for i in items if i.status == "pending"]
    limit = int(args.limit)
    if limit > 0:
        pending = pending[:limit]
    if not pending:
        print("pending=0")
        return 0

    session = build_session(cookie_file)
    ensure_login(session)

    success_magnets: set[str] = set()
    detail_rows: list[dict[str, Any]] = []
    pending_by_magnet = {x.magnet: x for x in pending}
    for chunk in chunked([x.magnet for x in pending], 15):
        sign, ts = get_sign_time(session)
        uid = get_uid(session)
        _, rows = add_tasks(session, chunk, uid=uid, sign=sign, ts=ts, cid="")
        for row in rows:
            mg = str(row.get("url") or "")
            queue_item = pending_by_magnet.get(mg)
            success = row.get("state") is True or is_duplicate_offline_result(row)
            if success and mg:
                success_magnets.add(mg)
            detail_rows.append(
                {
                    "name": queue_item.name if queue_item else "",
                    "magnet": mg,
                    "success": success,
                    "duplicate_as_success": bool(
                        row.get("state") is not True
                        and is_duplicate_offline_result(row)
                    ),
                    "reason": str(row.get("error_msg") or row.get("message") or ""),
                    "raw": row,
                }
            )

    for item in pending:
        if item.magnet in success_magnets:
            queue_text = replace_status_once(queue_text, item, "submitted")
    queue_text = update_updated_at(queue_text)
    queue_file.write_text(queue_text, encoding="utf-8")

    ok_count = len(success_magnets)
    fail_count = len(pending) - ok_count
    result_payload = {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "queue_file": str(queue_file),
        "cookie_file": str(cookie_file),
        "limit": limit,
        "total_pending_selected": len(pending),
        "submit_ok": ok_count,
        "submit_fail": fail_count,
        "details": detail_rows,
    }
    if args.result_json:
        out = Path(args.result_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(result_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(
        json.dumps(
            {
                "submit_ok": ok_count,
                "submit_fail": fail_count,
                "result_json": args.result_json or "",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if fail_count == 0 else 1


def cmd_inspect_cloud(args: argparse.Namespace) -> int:
    queue_file = Path(args.queue_file)
    cookie_file = Path(args.cookie_file)
    out_json = Path(args.output_json)

    session, _ = build_cookie_session(cookie_file)
    cloud_cid = args.cid or get_cloud_cid(session)

    items = parse_queue_toml(queue_file.read_text(encoding="utf-8"))
    filtered = [x for x in items if x.status in args.status_filter.split(",")]
    target_names = [x.name for x in filtered]
    queue_time_map = {x.name: unix_from_iso(x.time) for x in filtered}

    root_rows = list_children(session, cloud_cid)
    matched: list[dict[str, Any]] = []
    for row in root_rows:
        row_name = str(row.get("n", ""))
        hit = [t for t in target_names if t in row_name]
        hit_by = "name" if hit else ""
        time_hit = ""
        delta_sec = None
        if not hit:
            row_ts = 0
            try:
                row_ts = int(str(row.get("te") or row.get("t") or 0))
            except Exception:
                row_ts = 0
            if row_ts > 0 and queue_time_map:
                best_name = ""
                best_delta = 10**18
                for qn, qts in queue_time_map.items():
                    if qts <= 0:
                        continue
                    d = abs(row_ts - qts)
                    if d < best_delta:
                        best_delta = d
                        best_name = qn
                if best_name and best_delta <= int(args.time_window_sec):
                    hit = [best_name]
                    hit_by = "time"
                    time_hit = best_name
                    delta_sec = int(best_delta)
        if not hit and args.only_matched:
            continue
        e = to_entry(row, cloud_cid, 0)
        e["matched_queue_names"] = hit
        e["match_by"] = hit_by
        e["time_match_name"] = time_hit
        e["time_delta_sec"] = delta_sec
        # 115 存在“m=0 但 cid 可继续列出内容”的特殊条目，这里统一尝试展开。
        e["children"] = recurse_tree(session, e["cid"], 1, int(args.max_depth))
        e["pseudo_container"] = (not e["is_dir"]) and bool(e["children"])
        matched.append(e)

    result = {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "cloud_cid": cloud_cid,
        "queue_file": str(queue_file),
        "status_filter": args.status_filter,
        "entries": matched,
    }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(out_json)
    return 0


def cmd_propose_downloads(args: argparse.Namespace) -> int:
    inspect_json = Path(args.inspect_json)
    output_plan = Path(args.output_plan)
    sync_state_file = Path(args.sync_state_file)
    safe_root = get_aria2_safe_output_root(sync_state_file, args.output_root)
    output_root = Path(safe_root)

    data = json.loads(inspect_json.read_text(encoding="utf-8"))
    entries = data.get("entries", [])

    proposals: list[dict[str, Any]] = []
    for e in entries:
        candidates: list[dict[str, Any]] = []
        if e.get("is_dir") or e.get("children"):
            for c in e.get("children", []):
                if c.get("is_dir"):
                    continue
                if not c.get("pc"):
                    continue
                if is_video_file(str(c.get("name", "")), int(c.get("size") or 0)):
                    candidates.append(c)
        else:
            if e.get("pc") and is_video_file(
                str(e.get("name", "")), int(e.get("size") or 0)
            ):
                candidates.append(e)

        if not candidates:
            continue
        candidates.sort(key=lambda x: int(x.get("size") or 0), reverse=True)
        selected = candidates[0]
        file_name = str(selected.get("name", ""))
        matched_names = e.get("matched_queue_names", [])
        base_text = matched_names[0] if matched_names else file_name
        series_key = detect_series_key(base_text)
        # 要求：每个大视频文件放在独立目录（目录名默认取文件名去扩展）
        unique_dir = sanitize_dir_name(Path(file_name).stem)
        proposals.append(
            {
                "queue_name": matched_names[0] if matched_names else "",
                "cloud_entry_name": e.get("name", ""),
                "selected_file_name": file_name,
                "selected_file_size": int(selected.get("size") or 0),
                "pickcode": selected.get("pc", ""),
                "mtime": selected.get("mtime", ""),
                "series_key": series_key,
                "dest_dir": str(output_root / unique_dir),
                "dest_out": file_name,
                "reason": "largest-video-file",
            }
        )

    out = {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inspect_json": str(inspect_json),
        "items": proposals,
    }
    output_plan.parent.mkdir(parents=True, exist_ok=True)
    output_plan.write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(output_plan)
    return 0


def cmd_queue_by_plan(args: argparse.Namespace) -> int:
    cookie_file = Path(args.cookie_file)
    plan_json = Path(args.plan_json)
    sync_state_file = Path(args.sync_state_file)
    session, cookie_header = build_cookie_session(cookie_file)

    data = json.loads(plan_json.read_text(encoding="utf-8"))
    items = data.get("items", [])
    ok = 0
    fail = 0

    allowed_roots = get_allowed_output_roots(sync_state_file)
    if not allowed_roots:
        print(f"FAIL sync_state missing allowed_output_roots: {sync_state_file}")
        return 1

    if int(args.wait_before_downurl) > 0:
        time.sleep(int(args.wait_before_downurl))

    for item in items:
        pickcode = str(item.get("pickcode") or "")
        if not pickcode:
            fail += 1
            continue
        entry: dict[str, Any] = {}
        for idx in range(max(1, int(args.retry_on_empty) + 1)):
            entry = get_download_entry(session, pickcode)
            if entry.get("url"):
                break
            if idx < int(args.retry_on_empty):
                time.sleep(int(args.retry_interval))
        if not entry.get("url"):
            print(f"MISS {item.get('queue_name', '')} downurl_empty")
            fail += 1
            continue
        direct_url, file_name = extract_url_and_name(entry, fallback_name=pickcode)
        out_dir_text = str(item.get("dest_dir") or args.output_root)
        allowed, reason = ensure_dest_dir_allowed(out_dir_text, allowed_roots)
        if not allowed:
            print(f"FAIL {item.get('queue_name', '')} {reason}")
            fail += 1
            continue
        out_dir = Path(out_dir_text)
        out_name = str(item.get("dest_out") or file_name)

        # 115 直链在部分 aria2 环境里对 header 传法较敏感：
        # - 优先使用 aria2 原生 referer / user-agent 字段（稳定）
        # - 兼容保留 header（但不再强塞 Cookie，避免跨端 Cookie 导致 403）
        options = {
            "dir": str(out_dir),
            "out": out_name,
            "continue": "true",
            "split": str(args.split),
            "max-connection-per-server": str(args.split),
            "min-split-size": "1M",
            "file-allocation": "none",
            "referer": "https://115.com/",
            "user-agent": DEFAULT_HEADERS["User-Agent"],
            "header": [
                "Accept: */*",
            ],
        }
        body = aria2_call(
            args.aria2_rpc, args.aria2_secret, "aria2.addUri", [[direct_url], options]
        )
        if "error" in body:
            print(f"FAIL {item.get('queue_name', '')} {body['error']}")
            fail += 1
            continue
        gid = body.get("result", "")
        item["aria2_gid"] = gid
        item["queued_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        print(f"OK {item.get('queue_name', '')} gid={gid} out={out_name}")
        ok += 1

    data["items"] = items
    data["queue_result"] = {"ok": ok, "fail": fail}
    plan_json.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"queue_ok={ok} fail={fail}")
    return 0 if fail == 0 else 1


def cmd_monitor(args: argparse.Namespace) -> int:
    fields = [
        "gid",
        "status",
        "errorCode",
        "errorMessage",
        "totalLength",
        "completedLength",
        "downloadSpeed",
    ]
    g = aria2_call(args.aria2_rpc, args.aria2_secret, "aria2.getGlobalStat", [])
    active = aria2_call(args.aria2_rpc, args.aria2_secret, "aria2.tellActive", [fields])
    waiting = aria2_call(
        args.aria2_rpc,
        args.aria2_secret,
        "aria2.tellWaiting",
        [0, int(args.limit), fields],
    )
    stopped = aria2_call(
        args.aria2_rpc,
        args.aria2_secret,
        "aria2.tellStopped",
        [0, int(args.limit), fields],
    )

    report = {
        "time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "global": g.get("result", {}),
        "active": active.get("result", []),
        "waiting": waiting.get("result", []),
        "stopped": stopped.get("result", []),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def cmd_submit_discover(args: argparse.Namespace) -> int:
    submit_args = argparse.Namespace(
        queue_file=args.queue_file, cookie_file=args.cookie_file
    )
    cmd_submit_pending(submit_args)
    time.sleep(int(args.wait_after_submit))

    inspect_args = argparse.Namespace(
        queue_file=args.queue_file,
        cookie_file=args.cookie_file,
        output_json=args.output_json,
        status_filter=args.status_filter,
        max_depth=args.max_depth,
        only_matched=True,
        time_window_sec=args.time_window_sec,
    )
    cmd_inspect_cloud(inspect_args)

    propose_args = argparse.Namespace(
        inspect_json=args.output_json,
        output_plan=args.output_plan,
        output_root=args.output_root,
        sync_state_file="memory/115_sync_state.toml",
    )
    cmd_propose_downloads(propose_args)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="115 磁链到 aria2 全流程脚本")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("save-cookie", help="保存115 cookie到文件")
    p.add_argument("--cookie-text", required=True)
    p.add_argument("--cookie-file", required=True)
    p.set_defaults(func=cmd_save_cookie)

    p = sub.add_parser("add-magnets", help="追加磁链到队列文件")
    p.add_argument("--queue-file", required=True)
    p.add_argument("--magnet", nargs="*", default=[])
    p.add_argument("--magnet-file")
    p.set_defaults(func=cmd_add_magnets)

    p = sub.add_parser("plan", help="生成队列计划快照")
    p.add_argument("--queue-file", required=True)
    p.add_argument("--plan-dir", default="plans")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("submit-pending", help="提交pending到115云下载")
    p.add_argument("--queue-file", required=True)
    p.add_argument("--cookie-file", required=True)
    p.add_argument("--limit", default="0", help="本次最多提交多少条，0 表示全部")
    p.add_argument("--result-json", default="", help="提交详情输出 JSON 文件")
    p.set_defaults(func=cmd_submit_pending)

    p = sub.add_parser(
        "inspect-cloud", help="探查云下载目录结构/大小/pickcode/更新时间"
    )
    p.add_argument("--queue-file", required=True)
    p.add_argument("--cookie-file", required=True)
    p.add_argument("--output-json", required=True)
    p.add_argument("--status-filter", default="submitted")
    p.add_argument("--max-depth", default="3")
    p.add_argument("--time-window-sec", default="5400")
    p.add_argument("--cid", default="", help="云下载目录cid（留空自动寻找）")
    p.add_argument("--only-matched", action="store_true")
    p.set_defaults(func=cmd_inspect_cloud)

    p = sub.add_parser("propose-downloads", help="根据探查结果生成下载建议计划")
    p.add_argument("--inspect-json", required=True)
    p.add_argument("--output-plan", required=True)
    p.add_argument("--output-root", required=True)
    p.add_argument("--sync-state-file", default="memory/115_sync_state.toml")
    p.set_defaults(func=cmd_propose_downloads)

    p = sub.add_parser("queue-by-plan", help="按下载计划托管到aria2")
    p.add_argument("--plan-json", required=True)
    p.add_argument("--cookie-file", required=True)
    p.add_argument("--aria2-rpc", required=True)
    p.add_argument("--aria2-secret", required=True)
    p.add_argument("--output-root", default="")
    p.add_argument("--sync-state-file", default="memory/115_sync_state.toml")
    p.add_argument("--split", default="16")
    p.add_argument("--wait-before-downurl", default="30")
    p.add_argument("--retry-on-empty", default="1")
    p.add_argument("--retry-interval", default="20")
    p.set_defaults(func=cmd_queue_by_plan)

    p = sub.add_parser("monitor", help="监控aria2任务状态")
    p.add_argument("--aria2-rpc", required=True)
    p.add_argument("--aria2-secret", required=True)
    p.add_argument("--limit", default="30")
    p.set_defaults(func=cmd_monitor)

    p = sub.add_parser(
        "submit-discover",
        help="提交pending后等待并主动探查云下载，再生成下载建议",
    )
    p.add_argument("--queue-file", required=True)
    p.add_argument("--cookie-file", required=True)
    p.add_argument("--output-json", required=True)
    p.add_argument("--output-plan", required=True)
    p.add_argument("--output-root", required=True)
    p.add_argument("--wait-after-submit", default="30")
    p.add_argument("--status-filter", default="submitted")
    p.add_argument("--max-depth", default="3")
    p.add_argument("--time-window-sec", default="5400")
    p.set_defaults(func=cmd_submit_discover)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
