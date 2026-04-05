#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path


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


def sanitize_dir_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r"[\\/:*?\"<>|]", "-", name)
    name = re.sub(r"\.mp4$|\.mkv$|\.avi$|\.mov$|\.wmv$", "", name, flags=re.I)
    return name.strip(" .-") or "unknown"


def detect_series_key(base_text: str) -> str:
    m = re.search(r"([A-Za-z]{2,10})[-_ ]?(\d{2,6})[-_ ](\d{1,2})$", base_text)
    if m:
        return f"{m.group(1).upper()}-{m.group(2)}"
    m2 = re.search(r"([A-Za-z]{2,10})[-_ ]?(\d{2,6})", base_text)
    if m2:
        return f"{m2.group(1).upper()}-{m2.group(2)}"
    return sanitize_dir_name(base_text)


def is_video(name: str, size: int) -> bool:
    ext = Path(name).suffix.lower()
    if ext in VIDEO_EXTS:
        return True
    return size > 300 * 1024 * 1024


def build_candidates(entries: list[dict]) -> dict[str, list[dict]]:
    by_container: dict[str, list[dict]] = {}
    for e in entries:
        if e.get("is_dir"):
            continue
        name = str(e.get("name", ""))
        size = int(e.get("size") or 0)
        pc = str(e.get("pickcode") or "")
        if not pc or not is_video(name, size):
            continue
        # 以 parent_cid 作为容器分组，适配“目录内文件”与“伪容器”结构
        key = str(e.get("parent_cid") or "")
        by_container.setdefault(key, []).append(e)
    return by_container


def main() -> int:
    parser = argparse.ArgumentParser(description="根据目录遍历结果生成下载计划")
    parser.add_argument("--probe-json", required=True)
    parser.add_argument("--output-plan", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--mode", default="largest", choices=["largest", "all"])
    parser.add_argument("--name-hints", default="")
    args = parser.parse_args()

    data = json.loads(Path(args.probe_json).read_text(encoding="utf-8"))
    entries = data.get("entries", [])
    hints = [x.strip() for x in args.name_hints.split(",") if x.strip()]

    by_container = build_candidates(entries)
    plan_items: list[dict] = []

    for _, files in by_container.items():
        files.sort(key=lambda x: int(x.get("size") or 0), reverse=True)
        selected = files if args.mode == "all" else files[:1]
        for f in selected:
            file_name = str(f.get("name", ""))
            base_text = file_name
            for h in hints:
                if h and h in file_name:
                    base_text = h
                    break
            series_key = detect_series_key(base_text)
            dir_name = sanitize_dir_name(series_key)
            plan_items.append(
                {
                    "cloud_path": f.get("path", ""),
                    "cloud_cid": f.get("cid", ""),
                    "pickcode": f.get("pickcode", ""),
                    "mtime": f.get("mtime", ""),
                    "size": int(f.get("size") or 0),
                    "selected_file_name": file_name,
                    "series_key": series_key,
                    "dest_dir": str(Path(args.output_root) / dir_name),
                    "dest_out": file_name,
                }
            )

    out = {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "probe_json": str(args.probe_json),
        "mode": args.mode,
        "items": plan_items,
    }
    op = Path(args.output_plan)
    op.parent.mkdir(parents=True, exist_ok=True)
    op.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(op)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
