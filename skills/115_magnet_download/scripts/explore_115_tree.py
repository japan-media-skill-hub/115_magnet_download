#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
import sys
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from skill_115_common import build_session, ensure_login


def iso_from_unix(ts: Any) -> str:
    try:
        v = int(str(ts))
        if v <= 0:
            return ""
        return datetime.fromtimestamp(v).astimezone().isoformat(timespec="seconds")
    except Exception:
        return ""


def normalize_entry(
    row: dict[str, Any], parent_cid: str, depth: int, path: str
) -> dict[str, Any]:
    ts = row.get("te") or row.get("tu") or row.get("t") or ""
    name = str(row.get("n", ""))
    cid = str(row.get("cid", "") or "")
    fid = str(row.get("fid", "") or "")
    size = int(row.get("s") or 0)
    pickcode = str(row.get("pc", "") or "")
    is_dir_flag = int(row.get("m", 0)) == 1
    is_file_fact = bool(fid) or size > 0 or bool(row.get("sha"))
    return {
        "name": name,
        "path": f"{path}/{name}" if path else name,
        "cid": cid,
        "fid": fid,
        "parent_cid": parent_cid,
        "pickcode": pickcode,
        "raw_m": int(row.get("m", 0) or 0),
        "is_dir": is_dir_flag,
        "is_file": is_file_fact,
        "size": size,
        "sha": str(row.get("sha", "") or ""),
        "mtime_unix": str(ts),
        "mtime": iso_from_unix(ts),
        "depth": depth,
    }


def fetch_page(session, url: str, pace_sec: float, timeout: int) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(3):
        if pace_sec > 0:
            time.sleep(pace_sec)
        try:
            response = session.get(url, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_error = exc
            time.sleep(min(2 + attempt, 4))
    raise RuntimeError(f"请求失败: {url} | {last_error}")


def list_children(
    session,
    cid: str,
    limit: int = 200,
    pace_sec: float = 1.0,
    timeout: int = 20,
    use_fallback_api: bool = True,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    offset = 0
    while True:
        rows: list[dict[str, Any]] = []
        webapi_url = (
            "https://webapi.115.com/files"
            f"?aid=1&cid={cid}"
            "&o=user_utime&asc=1"
            f"&offset={offset}"
            "&show_dir=1"
            f"&limit={limit}"
            "&code=&scid=&snap=0&natsort=1&record_open_time=1&count_folders=1"
            "&type=&source=&format=json&star=&is_share=&suffix=&custom_order=&fc_mix="
        )
        payload = fetch_page(session, webapi_url, pace_sec=pace_sec, timeout=timeout)
        rows = payload.get("data", []) or []
        if not rows and use_fallback_api:
            alt_url = (
                "https://aps.115.com/natsort/files.php"
                f"?aid=1&cid={cid}&o=file_name&asc=1&offset={offset}"
                f"&show_dir=1&limit={limit}&code=&scid=&snap=0&natsort=1"
                "&record_open_time=1&count_folders=1&type=&source=&format=json"
            )
            payload = fetch_page(session, alt_url, pace_sec=pace_sec, timeout=timeout)
            rows = payload.get("data", []) or []
        if not rows:
            break
        out.extend(rows)
        offset += limit
        if len(rows) < limit:
            break
    return out


def can_descend(entry: dict[str, Any]) -> bool:
    cid = str(entry.get("cid") or "")
    if not cid:
        return False
    if bool(entry.get("is_dir")):
        return True
    if bool(entry.get("is_file")):
        return False
    return True


def probe(
    session,
    root_cid: str,
    max_depth: int,
    updated_within_hours: int,
    pace_sec: float,
    timeout: int,
    page_limit: int,
    hard_cap: int,
) -> tuple[list[dict[str, Any]], bool, str]:
    now = int(time.time())
    min_ts = now - updated_within_hours * 3600 if updated_within_hours > 0 else 0
    out: list[dict[str, Any]] = []
    q: list[tuple[str, int, str, list[dict[str, Any]] | None]] = [
        (root_cid, 0, "", None)
    ]
    visited: set[str] = set()
    capped = False
    cap_reason = ""

    while q:
        if hard_cap > 0 and len(out) >= hard_cap:
            capped = True
            cap_reason = (
                f"已触发全局条目上限 hard_cap={hard_cap}；为避免下钻过深/请求异常，本轮提前停止。"
            )
            break
        cid, depth, path, prefetched_rows = q.pop(0)
        if cid in visited:
            continue
        visited.add(cid)
        rows = (
            prefetched_rows
            if prefetched_rows is not None
            else list_children(
                session, cid, limit=page_limit, pace_sec=pace_sec, timeout=timeout
            )
        )
        for row in rows:
            if hard_cap > 0 and len(out) >= hard_cap:
                capped = True
                cap_reason = (
                    f"已触发全局条目上限 hard_cap={hard_cap}；为避免下钻过深/请求异常，本轮提前停止。"
                )
                break
            e = normalize_entry(row, cid, depth, path)
            try:
                ts = int(e["mtime_unix"] or 0)
            except Exception:
                ts = 0
            e["within_window"] = bool(min_ts == 0 or ts == 0 or ts >= min_ts)
            out.append(e)
            if depth < max_depth and can_descend(e):
                child_rows = list_children(
                    session,
                    e["cid"],
                    limit=page_limit,
                    pace_sec=pace_sec,
                    timeout=timeout,
                )
                if child_rows:
                    e["expandable"] = True
                    q.append((e["cid"], depth + 1, e["path"], child_rows))
                else:
                    e["expandable"] = False
            else:
                e["expandable"] = False
        if capped:
            break
    return out, capped, cap_reason


def main() -> int:
    parser = argparse.ArgumentParser(
        description="低频遍历 115 目录树，只输出事实，不猜目标文件"
    )
    parser.add_argument("--cookie-file", required=True)
    parser.add_argument("--cid", required=True, help="起始 cid；根目录用 0")
    parser.add_argument("--max-depth", default="2")
    parser.add_argument("--updated-within-hours", default="0")
    parser.add_argument("--max-entries", default="0")
    parser.add_argument("--pace-sec", default="0.3")
    parser.add_argument("--page-limit", default="200")
    parser.add_argument("--timeout", default="20")
    parser.add_argument("--output-json", required=True)
    args = parser.parse_args()

    session = build_session(Path(args.cookie_file))
    ensure_login(session)
    hard_cap = 200
    rows, capped, cap_reason = probe(
        session=session,
        root_cid=args.cid.strip(),
        max_depth=int(args.max_depth),
        updated_within_hours=int(args.updated_within_hours),
        pace_sec=max(float(args.pace_sec), 0.0),
        timeout=max(int(args.timeout), 1),
        page_limit=max(1, min(int(args.page_limit), 1150)),
        hard_cap=hard_cap,
    )
    max_entries = int(args.max_entries)
    if max_entries > 0:
        rows = rows[: min(max_entries, hard_cap)]
    payload = {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "root_cid": args.cid.strip(),
        "max_depth": int(args.max_depth),
        "updated_within_hours": int(args.updated_within_hours),
        "pace_sec": max(float(args.pace_sec), 0.0),
        "hard_cap": hard_cap,
        "entry_count": len(rows),
        "capped": capped,
        "cap_reason": cap_reason,
        "entries": rows,
    }
    out = Path(args.output_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if capped:
        print(
            f"[WARN] 探查已提前停止：{cap_reason} 输出仅前 {len(rows)} 条。"
        )
    else:
        print(f"[INFO] 探查完成：输出 {len(rows)} 条。")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
