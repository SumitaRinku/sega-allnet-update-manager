#!/usr/bin/env python3
"""OrderOpt helper that can build and directly send hello/order requests."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


LITE_DEFAULT_ENDPOINT = "http://at.sys-allnet.cn/net/delivery/instruction"
V1_DEFAULT_ENDPOINT = "http://naominet.jp/sys/servlet/DownloadOrder"

try:
    from Crypto.Cipher import AES as _PyCryptoAes  # type: ignore
except Exception:  # pragma: no cover
    _PyCryptoAes = None

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes  # type: ignore
except Exception:  # pragma: no cover
    Cipher = None
    algorithms = None
    modes = None


@dataclass(frozen=True)
class LiteConfig:
    key_text: str
    key_chip: str
    endpoint: str = LITE_DEFAULT_ENDPOINT
    ua_game: str | None = None


@dataclass(frozen=True)
class V1Config:
    key_chip: str
    endpoint: str = V1_DEFAULT_ENDPOINT


LITE_CONFIG: dict[str, LiteConfig] = {
    "SDGB": LiteConfig("2F3F6A6F2B224C265C437239283D6B47", ""),
    "SDJJ": LiteConfig("6E443F6F375268666665703D7B545F62", ""),
    "SDHJ": LiteConfig("2D61353755583479392F6828496D4151", ""),
}

V1_CONFIG: dict[str, V1Config] = {
    "SDGA": V1Config(""),
    "SDGS": V1Config(""),
    "SDDT": V1Config(""),
    "SDED": V1Config(""),
    "SDGT": V1Config(""),
    "SDFT": V1Config(""),
    "SDEJ": V1Config(""),
}


def _local_config_candidates(filename: str) -> list[Path]:
    """本地扩展配置的查找位置：exe 同目录（打包运行）/ 模块上一级目录即仓库根（源码运行）。"""
    import sys as _sys
    candidates = []
    if getattr(_sys, "frozen", False):
        candidates.append(Path(_sys.executable).parent / filename)
    here = Path(__file__).resolve().parent
    candidates.append(here.parent / filename)
    candidates.append(here / filename)
    return candidates


def _load_local_games() -> None:
    """从本地 games.json 合并自定义游戏定义（该文件不随仓库分发）。

    格式示例：
    {
      "XXXX": {"protocol": "lite", "key_text": "...", "key_chip": "...",
               "endpoint": "...", "ua_game": "SDGB"},
      "YYYY": {"protocol": "v1", "key_chip": "...", "endpoint": "..."}
    }
    """
    for p in _local_config_candidates("games.json"):
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return
        for gid, cfg in data.items():
            gid = str(gid).strip().upper()
            if not gid or not isinstance(cfg, dict):
                continue
            proto = str(cfg.get("protocol", "")).lower()
            if proto == "lite":
                LITE_CONFIG[gid] = LiteConfig(
                    key_text=cfg.get("key_text", ""),
                    key_chip=cfg.get("key_chip", ""),
                    endpoint=cfg.get("endpoint", LITE_DEFAULT_ENDPOINT),
                    ua_game=cfg.get("ua_game"),
                )
            elif proto == "v1":
                V1_CONFIG[gid] = V1Config(
                    key_chip=cfg.get("key_chip", ""),
                    endpoint=cfg.get("endpoint", V1_DEFAULT_ENDPOINT),
                )
        return


_load_local_games()


def _load_keychip_overrides() -> dict[str, str]:
    """从本地 keychips.json 加载加密狗号（该文件不随仓库分发，避免泄露）。

    查找位置：exe 同目录（打包运行）/ 模块上一级目录即仓库根（源码运行）。
    格式示例：{"SDGA": "XXXXXXXXXX", ...}
    """
    import sys as _sys
    candidates = []
    if getattr(_sys, "frozen", False):
        candidates.append(Path(_sys.executable).parent / "keychips.json")
    here = Path(__file__).resolve().parent
    candidates.append(here.parent / "keychips.json")
    candidates.append(here / "keychips.json")
    for p in candidates:
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                return {str(k).strip().upper(): str(v).strip()
                        for k, v in data.items() if str(v).strip()}
            except Exception:
                continue
    return {}


_KEYCHIP_OVERRIDES = _load_keychip_overrides()


def resolve(game_id: str) -> dict:
    if game_id in LITE_CONFIG:
        cfg = LITE_CONFIG[game_id]
        return {
            "protocol": "lite",
            "game_id": game_id,
            "key_text": cfg.key_text,
            "key_chip": _KEYCHIP_OVERRIDES.get(game_id.upper()) or cfg.key_chip,
            "endpoint": cfg.endpoint,
            "user_agent": f"{(cfg.ua_game or game_id)};Windows/Lite",
        }
    if game_id in V1_CONFIG:
        cfg = V1_CONFIG[game_id]
        return {
            "protocol": "v1",
            "game_id": game_id,
            "key_chip": _KEYCHIP_OVERRIDES.get(game_id.upper()) or cfg.key_chip,
            "endpoint": cfg.endpoint,
            "headers": {"Pragma": "DFI"},
        }
    return {"protocol": "unsupported", "game_id": game_id}


def build_lite_content(game_id: str, title_version: str, timestamp: int | None) -> dict:
    resolved = resolve(game_id)
    if resolved["protocol"] != "lite":
        raise ValueError(f"{game_id} is not a Lite game id")
    unix = int(time.time()) if timestamp is None else timestamp
    content = (
        f"title_id={game_id}&title_ver={title_version}&"
        f"client_id={resolved['key_chip']}&token={unix}"
    )
    return {
        **resolved,
        "timestamp": unix,
        "content": content,
        "note": "Lite flow encrypts this content with AES-CBC before POST.",
    }


def build_v1_body(game_id: str, title_version: str, key_chip_override: str | None = None) -> dict:
    resolved = resolve(game_id)
    if resolved["protocol"] != "v1":
        raise ValueError(f"{game_id} is not a V1 game id")
    key_chip = key_chip_override or resolved["key_chip"]
    raw = f"game_id={game_id}&ver={title_version}&serial={key_chip}".encode(
        "utf-8"
    )
    # Use zlib-wrapped deflate semantics for V1.
    compressed = zlib.compress(raw, level=0)
    b64_body = base64.b64encode(compressed).decode("ascii")
    return {
        **resolved,
        "key_chip": key_chip,
        "raw_payload": raw.decode("utf-8"),
        "base64_body": b64_body,
    }


def parse_hello(protocol: str, text: str) -> dict:
    protocol = protocol.lower()
    if protocol == "lite":
        kv = dict(
            pair.split("=", 1)
            for pair in text.split("&")
            if "=" in pair and not pair.startswith("=")
        )
        uri = kv.get("uri", "")
        return {
            "protocol": "lite",
            "result": kv.get("result"),
            "uri_raw": uri,
            "uris": [u for u in uri.split("|") if u],
        }

    if protocol == "v1":
        kv = dict(
            pair.split("=", 1)
            for pair in text.split("&")
            if "=" in pair and not pair.startswith("=")
        )
        uri = kv.get("uri", "")
        return {
            "protocol": "v1",
            "stat": kv.get("stat"),
            "serial": kv.get("serial"),
            "uri_raw": uri,
            "uris": [u for u in uri.split("|") if u],
        }

    raise ValueError("protocol must be lite or v1")


def parse_order_text(order_text: str) -> dict:
    installs = [m.group(1) for m in re.finditer(r"INSTALL\d+=(.+)", order_text, re.M)]
    # 订单元数据：配信时间 / 公开时间 / 描述等
    meta: dict[str, str] = {}
    for field in ("ORDER_TIME", "RELEASE_TIME", "GAME_DESC", "GAME_ID", "DLFORMAT"):
        m = re.search(rf"^{field}=(.*)$", order_text, re.M)
        if m:
            meta[field] = m.group(1).strip().strip('"')
    return {"install_values": installs, "meta": meta}


def classify_uris(uri_raw: str) -> list[dict]:
    rows: list[dict] = []
    for index, value in enumerate(uri_raw.split("|")):
        if not value or value.strip().lower() in ("null", "none"):
            # 服务器无可用更新时会返回字面量 "null"，跳过而非当作 URL。
            continue
        rows.append(
            {
                "index": index,
                "type": "OPT" if "option" in value else "APP",
                "uri": value,
            }
        )
    return rows


def _pkcs7_pad(data: bytes, block_size: int = 16) -> bytes:
    pad = block_size - (len(data) % block_size)
    if pad == 0:
        pad = block_size
    return data + bytes([pad]) * pad


def _pkcs7_unpad(data: bytes, block_size: int = 16) -> bytes:
    if not data or len(data) % block_size != 0:
        raise ValueError("Invalid padded data length")
    pad = data[-1]
    if pad < 1 or pad > block_size:
        raise ValueError("Invalid PKCS7 padding")
    if data[-pad:] != bytes([pad]) * pad:
        raise ValueError("Bad PKCS7 padding bytes")
    return data[:-pad]


def _aes_encrypt_cbc(key: bytes, iv: bytes, data: bytes) -> bytes:
    if _PyCryptoAes is not None:
        return _PyCryptoAes.new(key, _PyCryptoAes.MODE_CBC, iv).encrypt(data)
    if Cipher is not None and algorithms is not None and modes is not None:
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        encryptor = cipher.encryptor()
        return encryptor.update(data) + encryptor.finalize()
    raise RuntimeError(
        "AES backend not found. Install 'pycryptodome' or 'cryptography' to use Lite execute."
    )


def _aes_decrypt_cbc(key: bytes, iv: bytes, data: bytes) -> bytes:
    if _PyCryptoAes is not None:
        return _PyCryptoAes.new(key, _PyCryptoAes.MODE_CBC, iv).decrypt(data)
    if Cipher is not None and algorithms is not None and modes is not None:
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        return decryptor.update(data) + decryptor.finalize()
    raise RuntimeError(
        "AES backend not found. Install 'pycryptodome' or 'cryptography' to use Lite execute."
    )


def _http_post_bytes(url: str, data: bytes, headers: dict[str, str], timeout: float) -> tuple[bytes, int]:
    req = urllib.request.Request(url=url, data=data, method="POST")
    for key, value in headers.items():
        req.add_header(key, value)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(), int(getattr(resp, "status", 200))


def _http_get_text(url: str, headers: dict[str, str], timeout: float) -> tuple[str, int]:
    req = urllib.request.Request(url=url, method="GET")
    for key, value in headers.items():
        req.add_header(key, value)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        status = int(getattr(resp, "status", 200))
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    return text, status


def send_lite_hello(game_id: str, title_version: str, timeout: float, timestamp: int | None = None) -> dict:
    request_info = build_lite_content(game_id, title_version, timestamp)
    key = binascii.unhexlify(request_info["key_text"])
    iv = bytes([0] * 16)
    content = request_info["content"].encode("utf-8")

    # Keep compatibility with existing Lite endpoint behavior.
    pre_padded = _pkcs7_pad(iv + content, 16)
    post_body = _aes_encrypt_cbc(key, iv, _pkcs7_pad(pre_padded, 16))

    response_bytes, status = _http_post_bytes(
        request_info["endpoint"],
        post_body,
        {"User-Agent": request_info["user_agent"], "Pragma": "DFI"},
        timeout=timeout,
    )
    if len(response_bytes) < 17:
        raise ValueError("Lite hello response is too short")
    resp_iv = response_bytes[:16]
    resp_cipher = response_bytes[16:]
    plain = _pkcs7_unpad(_aes_decrypt_cbc(key, resp_iv, resp_cipher), 16)
    return {
        "http_status": status,
        "hello_text": plain.decode("utf-8", errors="replace"),
        "request_info": request_info,
        "post_body_b64": base64.b64encode(post_body).decode("ascii"),
    }


def _inflate_v1(data: bytes) -> bytes:
    try:
        # Prefer zlib-wrapped stream first.
        return zlib.decompress(data)
    except zlib.error:
        # Fallback for servers that still return raw deflate.
        return zlib.decompress(data, wbits=-zlib.MAX_WBITS)


def send_v1_hello(game_id: str, title_version: str, timeout: float, key_chip_override: str | None = None) -> dict:
    request_info = build_v1_body(game_id, title_version, key_chip_override)
    request_body = request_info["base64_body"].encode("ascii")
    response_bytes, status = _http_post_bytes(
        request_info["endpoint"],
        request_body,
        # 部分游戏要求 User-Agent 为该游戏对应的加密狗号（keychip），统一携带。
        {"Pragma": "DFI", "User-Agent": request_info["key_chip"]},
        timeout=timeout,
    )
    response_b64 = response_bytes.decode("utf-8", errors="replace").strip()
    compressed = base64.b64decode(response_b64)
    plain = _inflate_v1(compressed).decode("utf-8", errors="replace")
    return {
        "http_status": status,
        "hello_text": plain,
        "request_info": request_info,
    }


def fetch_orders(uri_entries: list[dict], user_agent: str, timeout: float) -> list[dict]:
    rows: list[dict] = []
    for entry in uri_entries:
        row: dict[str, Any] = {
            "index": entry["index"],
            "type": entry["type"],
            "uri": entry["uri"],
        }
        try:
            order_text, status = _http_get_text(
                entry["uri"],
                headers={"User-Agent": user_agent},
                timeout=timeout,
            )
            row["http_status"] = status
            parsed = parse_order_text(order_text)
            row["install_values"] = parsed["install_values"]
            row["meta"] = parsed["meta"]
            row["order_text_preview"] = order_text[:300]
        except urllib.error.HTTPError as err:
            row["http_status"] = err.code
            row["error"] = f"HTTPError: {err.reason}"
        except Exception as err:  # pragma: no cover
            row["error"] = f"{type(err).__name__}: {err}"
        rows.append(row)
    return rows


def execute(
    game_id: str,
    title_version: str,
    timeout: float,
    fetch_order_files: bool,
    dry_run: bool,
    timestamp: int | None = None,
    key_chip_override: str | None = None,
) -> dict:
    resolved = resolve(game_id)
    # 订单文件请求的 User-Agent：优先使用自定义加密狗号。
    order_ua = key_chip_override or resolved.get("key_chip") or game_id
    result: dict[str, Any] = {
        "game_id": game_id,
        "title_version": title_version,
        "protocol": resolved["protocol"],
        "request": {},
        "hello": {},
        "orders": [],
        "diagnostics": [],
    }
    if resolved["protocol"] == "unsupported":
        result["diagnostics"].append("Unsupported game id")
        return result

    if resolved["protocol"] == "lite":
        request_preview = build_lite_content(game_id, title_version, timestamp)
        result["request"] = {
            "endpoint": request_preview["endpoint"],
            "headers": {"User-Agent": request_preview["user_agent"], "Pragma": "DFI"},
            "content": request_preview["content"],
            "timestamp": request_preview["timestamp"],
        }
        if dry_run:
            return result
        try:
            hello_result = send_lite_hello(game_id, title_version, timeout, timestamp)
        except Exception as err:
            result["diagnostics"].append(f"Lite hello failed: {type(err).__name__}: {err}")
            return result
        parsed = parse_hello("lite", hello_result["hello_text"])
        parsed["uri_entries"] = classify_uris(parsed["uri_raw"])
        parsed["http_status"] = hello_result["http_status"]
        result["hello"] = parsed
        if parsed.get("result") != "1":
            result["diagnostics"].append(f"Hello failed with result={parsed.get('result')}")
            return result
        if fetch_order_files:
            result["orders"] = fetch_orders(parsed["uri_entries"], order_ua, timeout)
        return result

    request_preview = build_v1_body(game_id, title_version, key_chip_override)
    result["request"] = {
        "endpoint": request_preview["endpoint"],
        "headers": {"Pragma": "DFI", "User-Agent": request_preview["key_chip"]},
        "raw_payload": request_preview["raw_payload"],
        "base64_body": request_preview["base64_body"],
    }
    if dry_run:
        return result
    try:
        hello_result = send_v1_hello(game_id, title_version, timeout, key_chip_override)
    except Exception as err:
        result["diagnostics"].append(f"V1 hello failed: {type(err).__name__}: {err}")
        return result
    parsed = parse_hello("v1", hello_result["hello_text"])
    parsed["uri_entries"] = classify_uris(parsed["uri_raw"])
    parsed["http_status"] = hello_result["http_status"]
    result["hello"] = parsed
    if parsed.get("stat") != "1":
        result["diagnostics"].append(f"Hello failed with stat={parsed.get('stat')}")
        return result
    if fetch_order_files:
        result["orders"] = fetch_orders(parsed["uri_entries"], order_ua, timeout)
    return result


def print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="OrderOpt model skill helper with execute mode")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_resolve = sub.add_parser("resolve", help="Resolve protocol and config by game id")
    p_resolve.add_argument("--game-id", required=True)

    p_lite = sub.add_parser("build-lite-content", help="Build Lite plaintext content")
    p_lite.add_argument("--game-id", required=True)
    p_lite.add_argument("--title-version", required=True)
    p_lite.add_argument("--timestamp", type=int)

    p_v1 = sub.add_parser("build-v1-body", help="Build V1 deflate+base64 body")
    p_v1.add_argument("--game-id", required=True)
    p_v1.add_argument("--title-version", required=True)

    p_hello = sub.add_parser("parse-hello", help="Parse hello response text")
    p_hello.add_argument("--protocol", required=True, choices=["lite", "v1"])
    p_hello.add_argument("--text", required=True)

    p_order = sub.add_parser("parse-order", help="Extract INSTALL entries")
    p_order.add_argument("--text")
    p_order.add_argument("--file")

    p_exec = sub.add_parser("execute", help="Send hello request and optionally fetch order files")
    p_exec.add_argument("--game-id", required=True)
    p_exec.add_argument("--title-version", required=True)
    p_exec.add_argument("--timeout", type=float, default=15.0)
    p_exec.add_argument("--timestamp", type=int)
    p_exec.add_argument("--no-fetch-orders", action="store_true")
    p_exec.add_argument("--dry-run", action="store_true")
    p_exec.add_argument("--key-chip", help="Override keychip serial / User-Agent (dongle number)")

    args = parser.parse_args()

    if args.cmd == "resolve":
        print_json(resolve(args.game_id))
        return 0

    if args.cmd == "build-lite-content":
        print_json(build_lite_content(args.game_id, args.title_version, args.timestamp))
        return 0

    if args.cmd == "build-v1-body":
        print_json(build_v1_body(args.game_id, args.title_version))
        return 0

    if args.cmd == "parse-hello":
        print_json(parse_hello(args.protocol, args.text))
        return 0

    if args.cmd == "parse-order":
        if not args.text and not args.file:
            raise ValueError("provide --text or --file")
        text = args.text or Path(args.file).read_text(encoding="utf-8")
        print_json(parse_order_text(text))
        return 0

    if args.cmd == "execute":
        payload = execute(
            game_id=args.game_id,
            title_version=args.title_version,
            timeout=float(args.timeout),
            fetch_order_files=not args.no_fetch_orders,
            dry_run=bool(args.dry_run),
            timestamp=args.timestamp,
            key_chip_override=args.key_chip,
        )
        print_json(payload)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
