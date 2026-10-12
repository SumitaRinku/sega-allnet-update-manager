#!/usr/bin/env python3
"""Key lookup and IV guessing tools for Sega images."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from Crypto.Cipher import AES

APP_KEYS = {
    "SDEZ": "d136eba05d40e82682e6aad8d9e8688c",
    "SDDT": "3f7658728b9517d3314e684fa2e2a045",
    "SDGS": "a5150cc5065d2c59ee2f8f332cbd29d5",
    "SDHD": "3abd00d7a820ce862eaf474bf6c8f33e",
    "SDFE": "f61719c371e5bca6788c139a53091617",
    "SDHJ": "985ea66ecb5b1f208c90e2b898f0b073",
    "SDGB": "7ca4e6b6f3d6e8b26472973887d7fa3a",
    "SDGT": "9d0bba20d1e84f2459399f5383beee72",
}
PACK_KEY = "e4281bcf48c4d28eb05772ce6f98587a"
OPT_KEY = "5c84a9e726eaa5dd351f2b0750c23697"

TARGET_NTFS = bytes.fromhex("eb52904e544653202020200010010000")
TARGET_EXFAT = bytes.fromhex("eb769045584641542020200000000000")


def parse_hex_16(raw: str, field_name: str) -> bytes:
    value = raw.strip().replace(" ", "")
    if value.startswith(("0x", "0X")):
        value = value[2:]
    try:
        data = bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} is not valid hex: {raw}") from exc
    if len(data) != 16:
        raise ValueError(f"{field_name} must be exactly 16 bytes")
    return data


def dump_output(obj: dict, output: str | None) -> None:
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    print(text)


def normalize_file_type(raw: str) -> str:
    value = raw.strip().lower()
    mapping = {
        "0": "pack",
        "1": "app",
        "2": "opt",
        "pack": "pack",
        "app": "app",
        "opt": "opt",
    }
    if value not in mapping:
        raise ValueError("file type must be one of: 0/1/2 or pack/app/opt")
    return mapping[value]


def cmd_key(args: argparse.Namespace) -> int:
    file_type = normalize_file_type(args.file_type)

    if file_type == "pack":
        key_hex = PACK_KEY
        source = "GetPackAesKey"
    elif file_type == "opt":
        key_hex = OPT_KEY
        source = "GetOptAesKey"
    else:
        game_id = (args.game_id or "").strip().upper()
        if not game_id:
            raise ValueError("--game-id is required for app file type")
        if game_id not in APP_KEYS:
            raise ValueError(f"game id not found in preset map: {game_id}")
        key_hex = APP_KEYS[game_id]
        source = "GetAesKey"

    out = {
        "file_type": file_type,
        "game_id": (args.game_id or "").strip().upper() or None,
        "key_hex": key_hex.upper(),
        "source": source,
    }
    dump_output(out, args.output)
    return 0


def cmd_guess_iv(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    if not input_path.exists() or not input_path.is_file():
        raise FileNotFoundError(f"input file does not exist: {input_path}")

    key = parse_hex_16(args.key, "key")
    fs = args.fs.strip().lower()
    if fs == "ntfs":
        target = TARGET_NTFS
    elif fs == "exfat":
        target = TARGET_EXFAT
    else:
        raise ValueError("--fs must be ntfs or exfat")

    offset = int(args.offset, 0)
    if offset < 0:
        raise ValueError("offset must be >= 0")

    with input_path.open("rb") as f:
        f.seek(offset)
        block = f.read(16)
    if len(block) != 16:
        raise ValueError("failed to read 16-byte encrypted block at requested offset")

    zero = bytes(16)
    dec = AES.new(key, AES.MODE_CBC, iv=zero).decrypt(block)
    iv = bytes(a ^ b for a, b in zip(dec, target))

    out = {
        "input": str(input_path),
        "fs": fs,
        "offset": offset,
        "iv_hex": iv.hex().upper(),
    }
    dump_output(out, args.output)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sega key and IV helper")
    sub = parser.add_subparsers(dest="command", required=True)

    p_key = sub.add_parser("key", help="Lookup preset key")
    p_key.add_argument("--file-type", required=True, help="0/1/2 or pack/app/opt")
    p_key.add_argument("--game-id", help="Required when file-type is app")
    p_key.add_argument("--output", help="Optional JSON file path")
    p_key.set_defaults(func=cmd_key)

    p_iv = sub.add_parser("guess-iv", help="Guess IV from first payload block")
    p_iv.add_argument("--input", required=True, help="Image file path")
    p_iv.add_argument("--key", required=True, help="16-byte AES key in hex")
    p_iv.add_argument("--fs", required=True, choices=["ntfs", "exfat"], help="Target filesystem")
    p_iv.add_argument("--offset", default="0x200000", help="Encrypted block offset (default: 0x200000)")
    p_iv.add_argument("--output", help="Optional JSON file path")
    p_iv.set_defaults(func=cmd_guess_iv)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())