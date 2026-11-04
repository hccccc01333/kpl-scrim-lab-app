#!/usr/bin/env python3
"""libGameCore.so 只读静态契约图（不加载库、不启动游戏、不接触设备进程）。

用途：
  1. 列出 libGameCore 的 C 导出桩 -> 槽位 -> 实现地址（RELA RELATIVE 物化）；
  2. 打印本方案依赖的关键全局对象链（CS FIFO / databin 注册表 / 视口缓冲）；
  3. --check 校验 docs/simulation_plan.md 引用的静态事实，防止版本漂移。

依赖：pyelftools、capstone（本地已有，见 requirements.txt 之外的离线分析环境）。
运行：python tools/gc_export_map.py --check
      python tools/gc_export_map.py --symbol PushCsBuffer --symbol DT_Count
      python tools/gc_export_map.py --json out.json

注意：只读取 data/replays/_analysis/libGameCore.so；不写任何二进制产物。
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
from elftools.elf.elffile import ELFFile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SO = ROOT / "data" / "replays" / "_analysis" / "libGameCore.so"

# 方案中直接引用的全局/槽位。数值来自 5069040/12.1.1.8 构建的 libGameCore.so。
KEY_SLOTS = [
    ("0x4ff4520", "主 context 入口槽；0x51ea4d0/0x52717b0 两跳后取真实 context"),
    ("0x51ea4d0", "context 持有者槽；静态指向 0x52717b0"),
    ("0x52717b0", "context 持有者对象（BSS）；首字段在上下文创建后指向真实 context"),
    ("0x4ff5de8", "CS FIFO 槽（PushCsBuffer 第 1 跳）"),
    ("0x52488b8", "CS FIFO 第二跳；静态指向 0x52c3250"),
    ("0x52c3250", "CS FIFO 8 路对象指针数组基址（BSS；Push/Commit 取 array[0]）"),
    ("0x52742a0", "databin 表对象指针数组槽（mem_databin.c 的 arrAddr；DT_* 目标注册表）"),
    ("0x5274280", "原生 loader 的源表对象数组指针槽（BSS；loader 从 0x5118818 取它）"),
    ("0x5118810", "DT_* 使用的注册表入口；静态指向 &0x52742a0"),
    ("0x5118818", "原生 loader 的源数组入口；静态指向 &0x5274280"),
    ("0x4ff57b0", "GameDataWrapper_GetTable 的名字表管理器"),
    ("0x542a7b0", "原生 databin DB 句柄（DatabinManager 运行时写）"),
    ("0x542a7f8", "databin 每表 CRC 数组指针"),
    ("0x542a800", "databin CRC 数组长度"),
    ("0x542a804", "SGameSetEnableDatabinCrcFromFile 的 1 字节开关"),
    ("0x542a8a8", "SFNtfRunningGameCoreThreadID 写入的线程 ID"),
    ("0x544d3a8", "databin 表数量（原生 loader 读取）"),
    ("0x542f4b0", "ModuleInit 传入的 BSS 上下文块；+0x48 = 只初始化一次标志"),
]

# 导出名 -> 期望实现地址（--check 用）。None 表示只记录不校验。
EXPECTED_IMPL = {
    "ModuleInit": 0x46AD0CC,
    "PushCsBuffer": 0x460A3AC,
    "CommitCsBuffer": 0x460A3E4,
    "ResetCsBuffer": 0x460A40C,
    "PushViewBuffer": 0x46B7F9C,
    "CommitViewBuffer": 0x46B7FF0,
    "ResetViewBuffer": 0x46B8030,
    "SGC_GetPlayerSettleData": 0x46AD0FC,
    "SGC_GetPlayerReportQuitACNTData": 0x46AD11C,
    "SGC_GetPlayerTLogData": 0x46AD13C,
    "SGC_GetPlayerMapExInfo": 0x46AD15C,
    "SGameSetEnableDatabinCrcFromFile": 0x4606AC8,
    "GameDataWrapper_GetTable": 0x4606F04,
    "DT_Count": 0x4606DA0,
    "DT_GetByIndex": 0x4606DD8,
    "DT_FindByKey": 0x4606D64,
    "SFNtfRunningGameCoreThreadID": 0x460A4C0,
    "QTSRegisterSystem": 0x45F3760,
    "QTSOpenFile": 0x45F3490,
}


class Core:
    def __init__(self, path: Path):
        self.path = path
        self.blob = path.read_bytes()
        self.elf = ELFFile(path.open("rb"))
        self.loads = [
            (ph["p_vaddr"], ph["p_filesz"], ph["p_offset"])
            for ph in self.elf.iter_segments()
            if ph["p_type"] == "PT_LOAD"
        ]
        self.sections = [
            (s["sh_addr"], s["sh_addr"] + s["sh_size"], s["sh_offset"])
            for s in self.elf.iter_sections()
            if s["sh_type"] == "SHT_PROGBITS"
        ]
        self.rel = {}
        for r in self.elf.get_section_by_name(".rela.dyn").iter_relocations():
            if r["r_info_type"] == 1027:  # R_AARCH64_RELATIVE
                self.rel[r["r_offset"]] = r["r_addend"]
        self.md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)

    def va2off(self, va: int):
        for sec_lo, sec_hi, off in self.sections:
            if sec_lo <= va < sec_hi:
                return off + (va - sec_lo)
        for seg_lo, seg_fsz, off in self.loads:
            if seg_lo <= va < seg_lo + seg_fsz:
                return off + (va - seg_lo)
        return None

    def q(self, va: int):
        if va in self.rel:
            return self.rel[va]
        off = self.va2off(va)
        if off is None:
            return None
        return struct.unpack_from("<Q", self.blob, off)[0]

    def u32(self, va: int):
        off = self.va2off(va)
        if off is None:
            return None
        return struct.unpack_from("<I", self.blob, off)[0]

    def dis(self, va: int, n: int):
        off = self.va2off(va)
        if off is None:
            return []
        return list(self.md.disasm(self.blob[off:off + n], va))

    def exports(self):
        out = []
        ds = self.elf.get_section_by_name(".dynsym")
        for s in ds.iter_symbols():
            if not s.name or s["st_shndx"] == "SHN_UNDEF":
                continue
            if s.name.startswith("_Z") or s.name.startswith("__"):
                continue
            if s["st_info"]["type"] not in ("STT_FUNC", "STT_OBJECT"):
                continue
            out.append((s.name, s["st_value"], s["st_size"], s["st_info"]["type"]))
        return sorted(out, key=lambda x: x[1])

    def resolve_stub(self, va: int):
        """返回 (slot, impl)。导出桩形如 adrp x8, page; ldr x8,[x8,#off]; br/blr x8。"""
        page = None
        for ins in self.dis(va, 24):
            if ins.mnemonic == "adrp":
                page = int(ins.op_str.split("#")[1], 16)
            elif ins.mnemonic == "ldr" and page is not None and "[" in ins.op_str:
                parts = ins.op_str.split("#")
                if len(parts) < 2:
                    continue
                try:
                    off = int(parts[1].rstrip("]"), 16)
                except ValueError:
                    continue
                slot = page + off
                return slot, self.rel.get(slot)
            elif ins.mnemonic in ("br", "blr"):
                break
        return None, None

    def export_rows(self):
        rows = []
        for name, va, size, typ in self.exports():
            slot, impl = self.resolve_stub(va)
            rows.append({"name": name, "stub": va, "size": size, "type": typ,
                         "slot": slot, "impl": impl})
        return rows


def fmt(v):
    return "-" if v is None else hex(v)


def check(core: Core):
    """校验方案引用的静态事实。返回 (ok, failures)。"""
    failures = []
    rows = {r["name"]: r for r in core.export_rows()}

    def need(name):
        r = rows.get(name)
        if r is None:
            failures.append(f"missing export {name}")
        return r

    for name, expected in EXPECTED_IMPL.items():
        r = need(name)
        if r and r["impl"] != expected:
            failures.append(f"{name}: impl {fmt(r['impl'])} != {fmt(expected)}")

    # SGC_* 是 4 字节桩 mov w0,#11; ret（0x52800160 0xd65f03c0）
    for name in ("SGC_GetPlayerSettleData", "SGC_GetPlayerReportQuitACNTData",
                 "SGC_GetPlayerTLogData", "SGC_GetPlayerMapExInfo"):
        r = rows.get(name)
        if not r or not r["impl"]:
            continue
        off = core.va2off(r["impl"])
        body = core.blob[off:off + 8]
        if body != bytes.fromhex("60018052c0035fd6"):
            failures.append(f"{name}: body {body.hex()} != mov w0,#11; ret")

    # SGameSetEnableDatabinCrcFromFile: 0x4606ac8 -> slot 0x522a3d8 -> 0x46064b4 -> strb
    r = rows.get("SGameSetEnableDatabinCrcFromFile")
    if r:
        if r["impl"] != 0x4606AC8:
            failures.append("SGameSetEnableDatabinCrcFromFile impl mismatch")
        if core.q(0x522A3D8) != 0x46064B4:
            failures.append("slot 0x522a3d8 != 0x46064b4")
        ins = core.dis(0x46064B4, 8)
        if len(ins) < 2 or ins[0].mnemonic != "adrp" or ins[1].mnemonic != "strb":
            failures.append("0x46064b4 is not adrp/strb (CRC flag setter)")

    # CS FIFO 静态链
    chain = [
        (0x4FF5DE8, 0x52488B8, "0x4ff5de8 -> 0x52488b8"),
        (0x52488B8, 0x52C3250, "0x52488b8 -> 0x52c3250"),
        (0x5118810, 0x52742A0, "0x5118810 -> 0x52742a0"),
        (0x5118818, 0x5274280, "0x5118818 -> 0x5274280"),
        (0x4FF57B0, 0x51187E8, "0x4ff57b0 -> 0x51187e8"),
        (0x4FF4520, 0x51EA4D0, "0x4ff4520 -> 0x51ea4d0"),
        (0x51EA4D0, 0x52717B0, "0x51ea4d0 -> 0x52717b0"),
    ]
    for slot, want, label in chain:
        got = core.q(slot)
        if got != want:
            failures.append(f"{label}: got {fmt(got)}")

    # DT_Count 的注册表取法：*(0x5118810) -> 0x52742a0 -> *arr -> table[index]
    ins = core.dis(0x4606DA0, 24)
    text = " ; ".join(f"{i.mnemonic} {i.op_str}" for i in ins)
    if "#0x810" not in text or "[x8]" not in text:
        failures.append("DT_Count no longer reads 0x5118810 -> [x8]")

    # 模块初始化标志/上下文
    if core.u32(0x542F4B0 + 0x48) is not None:
        pass  # BSS 静态为 0，运行期才置 1

    return (not failures), failures


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--so", type=Path, default=DEFAULT_SO)
    ap.add_argument("--json", type=Path, help="把导出/槽位表写成 JSON（只读分析产物）")
    ap.add_argument("--check", action="store_true", help="校验方案引用的静态事实")
    ap.add_argument("--symbol", action="append", default=[], help="打印指定导出的桩/实现反汇编")
    ap.add_argument("--globals", action="store_true", help="打印关键全局链")
    args = ap.parse_args(argv)

    if not args.so.exists():
        print(f"missing {args.so}", file=sys.stderr)
        return 2
    core = Core(args.so)

    if args.check:
        ok, failures = check(core)
        for f in failures:
            print("FAIL:", f)
        print("CHECK OK" if ok else f"CHECK FAILED ({len(failures)})")
        if not ok:
            return 1

    if args.globals:
        print("== key slots ==")
        for s, desc in KEY_SLOTS:
            va = int(s, 16)
            print(f"{s}  q={fmt(core.q(va))}  u32={fmt(core.u32(va))}  {desc}")

    if args.symbol:
        rows = {r["name"]: r for r in core.export_rows()}
        for name in args.symbol:
            r = rows.get(name)
            if not r:
                print(f"missing export {name}", file=sys.stderr)
                continue
            print(f"== {name} stub={r['stub']:#x} slot={fmt(r['slot'])} impl={fmt(r['impl'])}")
            if r["impl"]:
                for ins in core.dis(r["impl"], 0x60):
                    print(f"  {ins.address:#x}: {ins.mnemonic:<8} {ins.op_str}")

    if not (args.check or args.globals or args.symbol or args.json):
        print(f"== {args.so} C exports ==")
        for r in core.export_rows():
            print(f"{r['stub']:#010x} slot={fmt(r['slot']):>10} impl={fmt(r['impl']):>10} "
                  f"{r['type']:9} {r['name']}")

    if args.json:
        data = {
            "so": str(args.so),
            "exports": core.export_rows(),
            "key_slots": [
                {"slot": s, "q": core.q(int(s, 16)), "u32": core.u32(int(s, 16)), "desc": d}
                for s, d in KEY_SLOTS
            ],
        }
        args.json.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
