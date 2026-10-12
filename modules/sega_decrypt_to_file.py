#!/usr/bin/env python3
"""Decrypt Sega image payload to a plain output file.

This script follows the documented payload decryption contract:
- Skip encrypted header (default 0x200000)
- Decrypt in 0x1000-byte CBC blocks
- Derive per-block IV from (base IV, payload block offset)
"""

from __future__ import annotations

import argparse
from pathlib import Path

from Crypto.Cipher import AES

U128_MASK = (1 << 128) - 1


def parse_hex_16(raw: str, field_name: str) -> bytes:
    value = raw.strip().replace(" ", "")
    if value.startswith(("0x", "0X")):
        value = value[2:]
    try:
        data = bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} is not valid hex: {raw}") from exc
    if len(data) != 16:
        raise ValueError(f"{field_name} must be exactly 16 bytes (32 hex chars), got {len(data)}")
    return data


def transform_iv(base_iv: bytes, payload_offset: int) -> bytes:
    pos64 = payload_offset & ((1 << 64) - 1)
    pos_u128 = (pos64 << 64) | pos64
    iv_u128 = int.from_bytes(base_iv, byteorder="little", signed=False)
    mixed = (pos_u128 ^ iv_u128) & U128_MASK
    return mixed.to_bytes(16, byteorder="little", signed=False)


def decrypt_image_to_file(
    input_path: Path,
    output_path: Path,
    key: bytes,
    iv: bytes,
    header_size: int,
    block_size: int,
    force_overwrite: bool,
    progress=None,
) -> int:
    if block_size <= 0 or block_size % 16 != 0:
        raise ValueError("block_size must be > 0 and a multiple of 16")
    if header_size < 0:
        raise ValueError("header_size must be >= 0")

    file_size = input_path.stat().st_size
    if file_size < header_size:
        raise ValueError(f"input file is smaller than header_size: {file_size} < {header_size}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_mode = "wb" if force_overwrite else "xb"

    payload_total = max(file_size - header_size, 1)
    written = 0
    payload_offset = 0

    with input_path.open("rb") as src, output_path.open(output_mode) as dst:
        src.seek(header_size)

        while True:
            enc = src.read(block_size)
            if not enc:
                break

            if len(enc) % 16 != 0:
                raise ValueError(
                    "encrypted payload chunk length is not a multiple of 16 bytes; "
                    "cannot AES-CBC decrypt safely"
                )

            block_iv = transform_iv(iv, payload_offset)
            dec = AES.new(key, AES.MODE_CBC, iv=block_iv).decrypt(enc)
            dst.write(dec)

            payload_offset += len(enc)
            written += len(dec)

            # 每 ~8MB 汇报一次进度: progress(done_bytes, total_bytes)
            if progress is not None and (written % (8 << 20)) < block_size:
                progress(written, payload_total)

    if progress is not None:
        progress(written, payload_total)
    return written


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Decrypt Sega .pack/.app/.opt payload into a plain output file."
    )
    parser.add_argument("--input", required=True, help="Encrypted image file path")
    parser.add_argument("--output", required=True, help="Decrypted output file path")
    parser.add_argument("--key", required=True, help="AES key hex (16 bytes)")
    parser.add_argument("--iv", required=True, help="Base IV hex (16 bytes)")
    parser.add_argument(
        "--header-size",
        default="0x200000",
        help="Encrypted header size to skip (default: 0x200000)",
    )
    parser.add_argument(
        "--block-size",
        default="0x1000",
        help="CBC decrypt block size in bytes (default: 0x1000)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite output file if it already exists",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    if not input_path.exists():
        raise FileNotFoundError(f"input file does not exist: {input_path}")
    if not input_path.is_file():
        raise ValueError(f"input path is not a file: {input_path}")

    key = parse_hex_16(args.key, "key")
    iv = parse_hex_16(args.iv, "iv")
    header_size = int(args.header_size, 0)
    block_size = int(args.block_size, 0)

    written = decrypt_image_to_file(
        input_path=input_path,
        output_path=output_path,
        key=key,
        iv=iv,
        header_size=header_size,
        block_size=block_size,
        force_overwrite=args.force,
    )

    print(f"ok: wrote {written} bytes -> {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())