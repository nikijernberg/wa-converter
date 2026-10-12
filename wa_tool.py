import argparse
import json
import re
import sys
from pathlib import Path

from lupa.luajit21 import LuaRuntime

ROOT = Path(__file__).resolve().parent

LUA_ERRORS = {
    "invalid string type",
    "invalid string len",
    "unsupported wa version",
    "failed to decode",
    "failed to decompress",
    "deserialization failed",
    "failed to decode JSON to lua table",
    "failed to serialize lua table",
    "failed to compress serialized lua table",
    "failed to encode compressed serialized lua table",
}


def run_lua(action: str, input_string: str) -> str:
    """Decode a WeakAuras string to JSON, or encode JSON back to a string."""
    if action not in ("decode", "encode"):
        raise ValueError("action must be 'decode' or 'encode'")

    lua_file = ROOT / "lua" / f"{action}.lua"
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua_func = lua.eval(lua_file.read_text(encoding="utf-8"))
    lua_output = lua_func(input_string, ROOT.as_posix())
    if not isinstance(lua_output, str) or lua_output in LUA_ERRORS or lua_output.startswith("failed to"):
        raise RuntimeError(f"{action} failed: {lua_output}")
    return lua_output


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig").strip()


def extract_wa_string(text: str) -> str:
    compact = "".join(text.split())
    match = re.search(r"!WA:\d+!.+", compact)
    if not match:
        raise ValueError("no !WA: string found in the file")
    return match.group(0)


def aura_label(data: dict) -> str:
    display = data.get("d") if isinstance(data, dict) else None
    if isinstance(display, dict) and display.get("id"):
        return str(display["id"])
    return "(unnamed)"


def command_decode(input_path: Path, output_path: Path | None) -> Path:
    encoded = extract_wa_string(read_text(input_path))
    decoded = run_lua("decode", encoded)
    data = json.loads(decoded)
    destination = output_path or input_path.with_suffix(".json")
    destination.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {destination}")
    print(f"Aura: {aura_label(data)}")
    return destination


def command_encode(input_path: Path, output_path: Path | None) -> Path:
    raw = read_text(input_path)
    json.loads(raw)
    encoded = run_lua("encode", raw)
    destination = output_path or input_path.with_name(f"{input_path.stem}-import.txt")
    destination.write_text(encoded + "\n", encoding="utf-8")
    print(f"Wrote {destination}")
    print(f"Import string length: {len(encoded)}")
    return destination


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Decode a WeakAuras export to JSON, or encode that JSON back to an import string."
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    decode_parser = subparsers.add_parser("decode", help="write the aura as a JSON text file")
    decode_parser.add_argument("input", type=Path, help="text file containing a !WA:2! string")
    decode_parser.add_argument("-o", "--output", type=Path, help="JSON file to write (default: <input>.json)")

    encode_parser = subparsers.add_parser("encode", help="write a WeakAuras import string from a JSON file")
    encode_parser.add_argument("input", type=Path, help="JSON file produced by decode")
    encode_parser.add_argument("-o", "--output", type=Path, help="import string file (default: <input>-import.txt)")
    return parser


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    if args.action == "decode":
        command_decode(args.input, args.output)
    else:
        command_encode(args.input, args.output)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
