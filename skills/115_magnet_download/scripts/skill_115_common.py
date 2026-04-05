#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib
import json
import time
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import quote

import requests
from requests.cookies import RequestsCookieJar


DEFAULT_HEADERS = {
    "Connection": "keep-alive",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Origin": "https://115.com",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/83.0.4103.61 Safari/537.36 115Browser/23.9.3.6"
    ),
    "Referer": "https://115.com/?cid=0&offset=0&mode=wangpan",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
}

G_KTS = [
    240,
    229,
    105,
    174,
    191,
    220,
    191,
    138,
    26,
    69,
    232,
    190,
    125,
    166,
    115,
    184,
    222,
    143,
    231,
    196,
    69,
    218,
    134,
    196,
    155,
    100,
    139,
    20,
    106,
    180,
    241,
    170,
    56,
    1,
    53,
    158,
    38,
    105,
    44,
    134,
    0,
    107,
    79,
    165,
    54,
    52,
    98,
    166,
    42,
    150,
    104,
    24,
    242,
    74,
    253,
    189,
    107,
    151,
    143,
    77,
    143,
    137,
    19,
    183,
    108,
    142,
    147,
    237,
    14,
    13,
    72,
    62,
    215,
    47,
    136,
    216,
    254,
    254,
    126,
    134,
    80,
    149,
    79,
    209,
    235,
    131,
    38,
    52,
    219,
    102,
    123,
    156,
    126,
    157,
    122,
    129,
    50,
    234,
    182,
    51,
    222,
    58,
    169,
    89,
    52,
    102,
    59,
    170,
    186,
    129,
    96,
    72,
    185,
    213,
    129,
    156,
    248,
    108,
    132,
    119,
    255,
    84,
    120,
    38,
    95,
    190,
    232,
    30,
    54,
    159,
    52,
    128,
    92,
    69,
    44,
    155,
    118,
    213,
    27,
    143,
    204,
    195,
    184,
    245,
]
G_KEY_S = [0x29, 0x23, 0x21, 0x5E]
G_KEY_L = [120, 6, 173, 76, 51, 134, 93, 24, 76, 1, 63, 70]
RSA_N = int(
    "8686980c0f5a24c4b9d43020cd2c22703ff3f450756529058b1cf88f09b8602136477198"
    "a6e2683149659bd122c33592fdb5ad47944ad1ea4d36c6b172aad6338c3bb6ac6227502d01"
    "0993ac967d1aef00f0c8e038de2e4d3bc2ec368af2e9f10a6f1eda4f7262f136420c07c331"
    "b871bf139f74f3010e3c4fe57df3afb71683",
    16,
)
RSA_E = 0x10001


def parse_cookie_text(cookie_text: str) -> RequestsCookieJar:
    cookie_dict: dict[str, str] = {}
    for raw in cookie_text.split(";"):
        pair = raw.strip()
        if not pair or "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        cookie_dict[k.strip()] = v.strip()
    return requests.utils.cookiejar_from_dict(cookie_dict)


def load_cookie_jar(cookie_file: Path) -> RequestsCookieJar:
    text = cookie_file.read_text(encoding="utf-8")
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        lines.append(stripped)
    return parse_cookie_text(";".join(lines))


def require_cookie_keys(jar: RequestsCookieJar) -> None:
    required = {"UID", "CID", "SEID"}
    present = set(jar.keys())
    missing = sorted(required - present)
    if missing:
        raise ValueError(f"Cookie缺少关键字段: {', '.join(missing)}")


def build_session(cookie_file: Path) -> requests.Session:
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    session.cookies = load_cookie_jar(cookie_file)
    require_cookie_keys(session.cookies)
    return session


def get_json(session: requests.Session, url: str, timeout: int = 20) -> dict[str, Any]:
    response = session.get(url, timeout=timeout, allow_redirects=True)
    response.raise_for_status()
    return response.json()


def is_login(session: requests.Session) -> bool:
    data = get_json(session, "https://my.115.com/?ct=guide&ac=status")
    return data.get("state") is True


def ensure_login(session: requests.Session) -> None:
    if not is_login(session):
        raise RuntimeError("Cookie 登录失败或已过期")


def get_uid(session: requests.Session) -> int:
    data = get_json(session, "https://my.115.com/?ct=ajax&ac=get_user_aq")
    if data.get("state") is not True:
        raise RuntimeError(f"获取UID失败: {data}")
    uid = data.get("data", {}).get("uid")
    if not uid:
        raise RuntimeError(f"响应中缺少uid: {data}")
    return int(uid)


def get_sign_time(session: requests.Session) -> tuple[str, int]:
    data = get_json(session, "https://115.com/?ct=offline&ac=space")
    sign = data.get("sign")
    ts = data.get("time")
    if data.get("state") is not True or not sign or not ts:
        raise RuntimeError(f"获取sign/time失败: {data}")
    return str(sign), int(ts)


def add_tasks(
    session: requests.Session,
    urls: Sequence[str],
    uid: int,
    sign: str,
    ts: int,
    cid: str,
) -> tuple[int, list[dict[str, Any]]]:
    base_data = {
        "savepath": "",
        "wp_path_id": cid,
        "uid": uid,
        "sign": sign,
        "time": ts,
    }
    if len(urls) == 1:
        payload = {**base_data, "url": urls[0]}
        endpoint = "https://115.com/web/lixian/?ct=lixian&ac=add_task_url"
    else:
        payload = dict(base_data)
        for idx, item in enumerate(urls):
            payload[f"url[{idx}]"] = item
        endpoint = "https://115.com/web/lixian/?ct=lixian&ac=add_task_urls"

    response = session.post(endpoint, data=payload, timeout=30)
    response.raise_for_status()
    result = response.json()
    if result.get("state") is not True:
        raise RuntimeError(f"添加离线任务失败: {result}")
    if len(urls) == 1:
        return 1, [result]
    rows = result.get("result", [])
    ok_count = sum(1 for row in rows if row.get("state") is True)
    return ok_count, rows


def torrent_to_magnet(torrent_file: Path) -> str:
    try:
        bencodepy = importlib.import_module("bencodepy")
    except ImportError as exc:
        raise RuntimeError(
            "解析.torrent需要安装 bencodepy: pip install bencodepy"
        ) from exc
    decoded = bencodepy.bread(torrent_file)
    if not isinstance(decoded, dict) or b"info" not in decoded:
        raise RuntimeError(f"无效torrent文件: {torrent_file}")
    info_encoded = bencodepy.encode(decoded[b"info"])
    info_hash_hex = hashlib.sha1(info_encoded).hexdigest()
    name = decoded[b"info"].get(b"name", b"download").decode("utf-8", errors="ignore")
    trackers: list[str] = []
    if b"announce" in decoded:
        trackers.append(decoded[b"announce"].decode("utf-8", errors="ignore"))
    if b"announce-list" in decoded:
        for tier in decoded[b"announce-list"]:
            for item in tier:
                if isinstance(item, (bytes, bytearray)):
                    trackers.append(item.decode("utf-8", errors="ignore"))
    tr_args = "".join(f"&tr={quote(t)}" for t in dict.fromkeys(trackers) if t)
    return f"magnet:?xt=urn:btih:{info_hash_hex}&dn={quote(name)}{tr_args}"


def pretty_print_result(rows: Iterable[dict[str, Any]]) -> None:
    for idx, row in enumerate(rows, start=1):
        state = row.get("state")
        name = row.get("name", "")
        error_msg = row.get("error_msg", "")
        if state is True:
            print(f"[{idx}] OK {name}")
        else:
            print(f"[{idx}] FAIL {name} {error_msg}".strip())


def cookie_header_value(jar: RequestsCookieJar) -> str:
    return "; ".join(f"{k}={v}" for k, v in jar.items())


def m115_getkey(length: int, key: Sequence[int] | None) -> list[int]:
    if key is not None:
        return [
            ((key[i] + G_KTS[length * i]) & 0xFF) ^ G_KTS[length * (length - 1 - i)]
            for i in range(length)
        ]
    return G_KEY_L[:] if length == 12 else G_KEY_S[:]


def xor115_enc(src: Sequence[int], key: Sequence[int]) -> list[int]:
    src_len = len(src)
    key_len = len(key)
    mod4 = src_len % 4
    ret: list[int] = []
    if mod4 != 0:
        for i in range(mod4):
            ret.append(src[i] ^ key[i % key_len])
    for i in range(mod4, src_len):
        ret.append(src[i] ^ key[(i - mod4) % key_len])
    return ret


def m115_sym_encode(
    src: Sequence[int], key1: Sequence[int], key2: Sequence[int] | None
) -> list[int]:
    k1 = m115_getkey(4, key1)
    k2 = m115_getkey(12, key2)
    ret = xor115_enc(src, k1)
    ret.reverse()
    ret = xor115_enc(ret, k2)
    return ret


def m115_sym_decode(
    src: Sequence[int], key1: Sequence[int], key2: Sequence[int] | None
) -> list[int]:
    k1 = m115_getkey(4, key1)
    k2 = m115_getkey(12, key2)
    ret = xor115_enc(src, k2)
    ret.reverse()
    ret = xor115_enc(ret, k1)
    return ret


def pkcs1pad2(raw: str, block_size: int) -> int:
    if block_size < len(raw) + 11:
        raise ValueError("pkcs1pad2: message too long")
    ba = [0] * block_size
    i = len(raw) - 1
    n = block_size
    while i >= 0 and n > 0:
        n -= 1
        ba[n] = ord(raw[i])
        i -= 1
    n -= 1
    ba[n] = 0
    while n > 2:
        n -= 1
        ba[n] = 0xFF
    n -= 1
    ba[n] = 2
    n -= 1
    ba[n] = 0
    return int("".join(f"{b:02x}" for b in ba), 16)


def pkcs1unpad2(num: int) -> str:
    hex_text = f"{num:x}"
    if len(hex_text) % 2 != 0:
        hex_text = f"0{hex_text}"
    raw = bytes.fromhex(hex_text)
    i = 1
    while i < len(raw) and raw[i] != 0:
        i += 1
    if i >= len(raw):
        return ""
    return raw[i + 1 :].decode("latin1")


def rsa_encrypt_block(raw: str) -> str:
    m = pkcs1pad2(raw, 0x80)
    c = pow(m, RSA_E, RSA_N)
    return f"{c:0256x}"


def rsa_decrypt_block(raw: bytes) -> str:
    c = int(raw.hex(), 16)
    m = pow(c, RSA_E, RSA_N)
    return pkcs1unpad2(m)


def m115_asym_encode(src: Sequence[int]) -> str:
    block_plain = 128 - 11
    ret_hex = ""
    total = len(src)
    count = (total + block_plain - 1) // block_plain
    for i in range(count):
        piece = src[i * block_plain : min((i + 1) * block_plain, total)]
        ret_hex += rsa_encrypt_block("".join(chr(v) for v in piece))
    return base64.b64encode(bytes.fromhex(ret_hex)).decode("ascii")


def m115_asym_decode(src: Sequence[int]) -> list[int]:
    block_cipher = 128
    total = len(src)
    count = (total + block_cipher - 1) // block_cipher
    out = ""
    for i in range(count):
        piece = bytes(src[i * block_cipher : min((i + 1) * block_cipher, total)])
        out += rsa_decrypt_block(piece)
    return [ord(ch) for ch in out]


def m115_encode(src: str, timestamp: int) -> tuple[str, list[int]]:
    key = [
        ord(c)
        for c in hashlib.md5(f"!@###@#{timestamp}DFDR@#@#".encode("utf-8")).hexdigest()
    ]
    tmp = [ord(c) for c in src]
    tmp = m115_sym_encode(tmp, key, None)
    tmp = key[:16] + tmp
    return m115_asym_encode(tmp), key


def m115_decode(src: str, key: Sequence[int]) -> str:
    tmp = list(base64.b64decode(src))
    tmp = m115_asym_decode(tmp)
    plain = m115_sym_decode(tmp[16:], key, tmp[:16])
    return "".join(chr(x) for x in plain)


def get_download_entry(session: requests.Session, pickcode: str) -> dict[str, Any]:
    timestamp = int(time.time())
    payload = json.dumps({"pickcode": pickcode}, separators=(",", ":"))
    data, key = m115_encode(payload, timestamp)
    response = session.post(
        f"https://proapi.115.com/app/chrome/downurl?t={timestamp}",
        data={"data": data},
        timeout=30,
    )
    response.raise_for_status()
    content = response.json()
    if not content.get("state"):
        raise RuntimeError(f"获取直链失败: {content}")
    decoded = json.loads(m115_decode(content["data"], key))
    if not isinstance(decoded, dict) or not decoded:
        raise RuntimeError(f"解码响应异常: {decoded}")
    first_key = next(iter(decoded.keys()))
    entry = decoded[first_key]
    if not isinstance(entry, dict):
        raise RuntimeError(f"直链数据结构异常: {decoded}")
    return entry


def extract_url_and_name(entry: dict[str, Any], fallback_name: str) -> tuple[str, str]:
    url_field = entry.get("url")
    direct_url = ""
    if isinstance(url_field, dict):
        direct_url = str(url_field.get("url", ""))
    elif isinstance(url_field, str):
        direct_url = url_field
    if not direct_url:
        raise RuntimeError(f"未找到下载直链字段: {entry}")
    file_name = str(entry.get("file_name") or entry.get("name") or fallback_name)
    return direct_url, file_name
