"""Name the 27 AdvanceFrameCommands dispatch types from metadata + libil2cpp.

Read-only static analysis. Build 5247758 (王者 12.1.1.1 / Res 12.1.1.26).

What is established here
------------------------
`GameLogicHelper.AdvanceFrameCommands` (thunk file 0x6e04fa4) forwards to the
implementation at static VA 0x664cf7c (file 0x664bf7c).  The implementation
loops over `frapInfo+0xc` commands, reads a u8 type at `command+0xc`, and
dispatches through the 27-entry table at file 0x19be5ac.  The switch performs
`type-1 <= 26`, i.e. exactly the values 1..27.

`CSProtocol.BOOTFRAP_TYPEDEF` in global-metadata.dat has values 0..27
(MAX=28) with one name per value.  Values 1..27 line up one-for-one with the
switch, and the payload field offsets read by the processing functions match
the packed `CSProtocol.CSDT_FRAPBOOT_*` structs at a +0xc payload base.
Therefore:

    runtime type N  ==  BOOTFRAP_TYPEDEF value N   (1 <= N <= 27)

The tool emits the type -> BOOTFRAP name -> CSDT payload struct -> candidate
C# command class / FRAMEPKG command table.  Method-body names are not used:
the local method-pointer/name maps in this repository are known to be
unreliable for this obfuscated build, so all naming below comes from metadata
tables, relocations, field offsets and call-site constants.

Run:
    python tools/advance_frame_names.py
    python tools/advance_frame_names.py --json
"""
from __future__ import annotations

import argparse
import csv
import json
import struct
from pathlib import Path

from elftools.elf.elffile import ELFFile

try:
    from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
    from capstone.arm64 import ARM64_OP_IMM, ARM64_OP_MEM, ARM64_OP_REG
except ImportError:  # pragma: no cover - capstone is already a repo dependency
    Cs = None

ROOT = Path(__file__).resolve().parents[1]
AN = ROOT / "data" / "replays" / "_analysis"
META = AN / "global-metadata.dat"
LIB = AN / "libil2cpp.so"
OUT_CSV = AN / "datasets" / "advance_frame_names.csv"

# Static VA of the implementation is 0x664cf7c; the runtime capture in
# docs/advance_frame_binding.md is 0x40002c84cf7c.  The capture-derived load
# base is therefore 0x400026200000 (page aligned).
LOAD_BASE = 0x400026200000
IMPL_STATIC = 0x664CF7C
IMPL_RUNTIME = LOAD_BASE + IMPL_STATIC
DISPATCH_TABLE_FILE = 0x19BE5AC
JUMP_BASE_RUNTIME = 0x40002C84D03C
DEFAULT_HANDLER_RUNTIME = 0x40002C84D03C
SKIP_HANDLER_RUNTIME = 0x40002C84D050
# Tail-slot page: handler tails load [0x40003374b000 + imm]; the same page
# holds the processing-function pointers as RELA addends.
PROC_SLOT_PAGE_STATIC = 0xD54B000
PROC_SLOT_PAGE_RUNTIME = LOAD_BASE + PROC_SLOT_PAGE_STATIC
BOOTFRAP_ENUM = ("BOOTFRAP_TYPEDEF", "CSProtocol")
FRAME_CMD_ID_ENUM = ("FRAMECMD_ID_DEF", "CSProtocol")
FRAME_CMD_INFO = ("FRAME_CMD_INFO", "CSProtocolWrapper")

# Primitive Il2CppType indices observed in this metadata (see
# data/replays/_analysis/tools/decode_packed_inputs.py and FRAMECMD structs).
PRIMITIVE_WIDTH = {
    42908: ("Boolean/Byte", 1),
    42911: ("System.Byte", 1),
    94463: ("System.SByte", 1),
    102451: ("System.UInt16", 2),
    79255: ("System.Int16", 2),
    79278: ("System.Int32", 4),
    102469: ("System.UInt32", 4),
    102472: ("System.UInt32", 4),
    102482: ("System.Int32", 4),
    79304: ("System.Int32", 4),
    102486: ("System.UInt32", 4),
    79300: ("System.Int32", 4),
    102498: ("System.UInt64", 8),
    99432: ("System.String", 8),
    99577: ("System.String", 8),
    36784: ("String/byte[]", 8),
    37861: ("String/byte[]", 8),
}
# Field type indices whose target is a class/array/struct we do not fully
# resolve; treat as a 4-byte-aligned pointer for offsets but mark approximate.
OPAQUE_WIDTH = 8

# type -> curated candidate.  Every entry is derived from BOOTFRAP_TYPEDEF,
# the matching CSDT_FRAPBOOT_* struct, and (where present) a GameLogic command
# class whose metadata fields mirror the wire struct.
CANDIDATES = {
    1: dict(
        cls="(CC frame-command container)",
        attrs="",
        frame_id=None,
        frame_name="(CC batch)",
        framepkg="CmdCompressPlayerInfo / compressInfo_*",
        stcmd="(multiple compressed commands)",
        confidence="medium",
        evidence="BOOTFRAP_TYPE_CC; CSDT_FRAPBOOT_CC{wObjID,wSyncInfo}; "
                 "processing reads child at +0x10; no single C# command class.",
    ),
    2: dict(
        cls="(CS frame-command container)",
        attrs="",
        frame_id=None,
        frame_name="(CS batch)",
        framepkg="(multiple CS-sync commands)",
        stcmd="(multiple)",
        confidence="medium",
        evidence="BOOTFRAP_TYPE_CS; CSDT_FRAPBOOT_CS{wObjID=u16,stSyncInfo}; "
                 "processing reads u16 +0xc and passes &stSyncInfo(+0x10).",
    ),
    3: dict(
        cls="SvrRunawayCommand / SvrDisconnectCommand / SvrReconnectCommand "
            "(FRAME_EXTEND_QUIT: SvrNtfPlayerQuitFrameExtendCommand)",
        attrs="FrameSCSYNC",
        frame_id=None,
        frame_name="(account state change notification)",
        framepkg="CS_FRAPBOOT_ACNTSTATE_*",
        stcmd="(server notify)",
        confidence="high",
        evidence="BOOTFRAP_TYPE_ACNTSTATECHG; CSDT_FRAPBOOT_ACNTSTATE"
                 "{dwObjID,bStateChgType}; state enum CS_FRAPBOOT_ACNTSTATE_"
                 "DISCONN/RECONN/RUNAWAY/FRAME_EXTEND_QUIT.",
    ),
    4: dict(
        cls="AssistStateChgCommand",
        attrs="CompilerGenerated",
        frame_id=None,
        frame_name="(assist state change)",
        framepkg="CSDT_FRAPBOOT_ASSISTSTATE",
        stcmd="(server notify)",
        confidence="high",
        evidence="BOOTFRAP_TYPE_ASSISTSTATECHG; class fields "
                 "m_chgType/m_aiPlayerID/m_masterPlayerID match "
                 "bType/dwAiPlayerObjID/dwMasterObjID.",
    ),
    5: dict(
        cls="AutoAIChgCommand",
        attrs="FrameSCSYNC",
        frame_id=11,
        frame_name="FRAME_CMD_SWITCHAOUTAI",
        framepkg="FRAMEPKG_CMD_SWITCH_AI",
        stcmd="stCmdPlayerSwithAutoAI",
        confidence="high",
        evidence="BOOTFRAP_TYPE_AISTATECHG; class AutoAIChgCommand fields "
                 "m_autoType/m_playerID match bType/dwPlayerObjID.",
    ),
    6: dict(
        cls="SvrNtfGameOverCommand",
        attrs="CompilerGenerated",
        frame_id=None,
        frame_name="(game over notification)",
        framepkg="CSDT_FRAPBOOT_GAMEOVERNTF",
        stcmd="(server notify)",
        confidence="high",
        evidence="BOOTFRAP_TYPE_GAMEOVERNTF; class m_bWinCamp matches "
                 "bWinCamp; processing reads u8 +0xc.",
    ),
    7: dict(
        cls="PauseResumeGameCommand / PauseResumeGameCCCommand",
        attrs="FrameSCSYNC / FrameCommandClass",
        frame_id=158,
        frame_name="FRAME_CMD_PAUSE_RESUME_GAME",
        framepkg="FRAMEPKG_CMD_PAUSE_RESUME_GAME",
        stcmd="stCmdPauseResumeGame",
        confidence="high",
        evidence="BOOTFRAP_TYPE_PAUSE; class fields PauseCommand/PauseByCamp/"
                 "CampPauseTimes mirror bType/bCamp/szCampPauseNum.",
    ),
    8: dict(
        cls="CampStateCommand",
        attrs="FrameSCSYNC",
        frame_id=None,
        frame_name="(camp state notification)",
        framepkg="CSDT_FRAPBOOT_CAMPSTATE",
        stcmd="(server notify)",
        confidence="high",
        evidence="BOOTFRAP_TYPE_CAMPSTATE; class fields camp/state match "
                 "bCamp/bState; processing reads u8 +0xc and +0xd.",
    ),
    9: dict(
        cls="CampSurrenderCommand",
        attrs="FrameSCSYNC",
        frame_id=None,
        frame_name="(camp surrender notification)",
        framepkg="CSDT_FRAPBOOT_CAMP_SURRENDER",
        stcmd="(server notify)",
        confidence="high",
        evidence="BOOTFRAP_TYPE_CAMP_SURRENDER; class field camp matches "
                 "bCamp; processing reads u8 +0xc.",
    ),
    10: dict(
        cls="SvrNtfTransportCmd (candidate)",
        attrs="(registered by name)",
        frame_id=None,
        frame_name="(move-to-born notification)",
        framepkg="CSDT_FRAPBOOT_MOVETOBORN",
        stcmd="(server notify)",
        confidence="medium",
        evidence="BOOTFRAP_TYPE_MOVETOBORN; wire struct bObjType/dwObjID/stPos; "
                 "SvrNtfTransportCmd fields destPosition/playerId/playerType "
                 "are the same values in a different order.  Uses default handler.",
    ),
    11: dict(
        cls="SvrNtfPlayerQuitBattleCmd",
        attrs="FrameSCSYNC",
        frame_id=None,
        frame_name="(quit battle notification)",
        framepkg="CSDT_FRAPBOOT_QUITBATTLENTF",
        stcmd="(server notify)",
        confidence="high",
        evidence="BOOTFRAP_TYPE_QUITBATTLENTF; class playerId/times match "
                 "dwObjID/dwTimes; processing loads u32 +0x10/+0x14.",
    ),
    12: dict(
        cls="SvrNtfPlayerBornFollowCmd",
        attrs="(registered by name)",
        frame_id=None,
        frame_name="(born follow notification)",
        framepkg="CSDT_FRAPBOOT_BORNFOLLOW",
        stcmd="(server notify)",
        confidence="high",
        evidence="BOOTFRAP_TYPE_BORNFOLLOW; class playerId/followPlayerId/"
                 "state match dwObjectID/dwFollowObjID/bState.  Default handler.",
    ),
    13: dict(
        cls="PVEObjNtfCommand",
        attrs="(registered by name)",
        frame_id=None,
        frame_name="(PVE object notification)",
        framepkg="CSDT_FRAPBOOT_PVEOBJNTF",
        stcmd="(server notify)",
        confidence="high",
        evidence="BOOTFRAP_TYPE_PVEOBJNTF; class m_playerId/m_dieOrRevive/"
                 "m_CouponsReviveCnt match dwObjID/bDieOrRevive/"
                 "bCouponsReviveCnt.  Default handler.",
    ),
    14: dict(
        cls="CustomEffectCommand",
        attrs="FrameSCSYNC",
        frame_id=None,
        frame_name="(custom room effect)",
        framepkg="CSDT_FRAPBOOT_CUSTOMROOM_EFFECT",
        stcmd="(server notify)",
        confidence="high",
        evidence="BOOTFRAP_TYPE_CUSTOMROOM_EFFECT; processing reads "
                 "dwStrParam1Len +0x14, szStrParam1 +0x18, dwStrParam2Len "
                 "+0x20, szStrParam2 +0x28, iIntParam1..4 +0x30/+0x38, "
                 "dwEffectID +0xc; class fields m_effectID/m_strParam1/2/"
                 "m_intParam1..5 match the struct.",
    ),
    15: dict(
        cls="(auto-chess only; skip path)",
        attrs="",
        frame_id=None,
        frame_name="(auto chess bounty add coin)",
        framepkg="CSDT_FRAPBOOT_AUTOCHESS_BOUNTYMATCH_ADDCOIN",
        stcmd="(mode-specific notify)",
        confidence="high",
        evidence="BOOTFRAP_TYPE_AUTOCHESSBOUNTYMATCH_ADDCOIN; jump table "
                 "points at the skip stub.  Struct dwObjID/dwCoinNum.",
    ),
    16: dict(
        cls="SvrNtfBeginFrameExtendCommand",
        attrs="FrameSCSYNC",
        frame_id=None,
        frame_name="(begin frame extend)",
        framepkg="CSDT_FRAPBOOT_BEGIN_FRAME_EXTEND",
        stcmd="(server notify)",
        confidence="high",
        evidence="BOOTFRAP_TYPE_BEGIN_FRAME_EXTEND; class m_bWinCamp matches "
                 "bWinCamp; processing reads u8 +0xc.",
    ),
    17: dict(
        cls="PlayPaintCommand",
        attrs="FrameSCSYNC",
        frame_id=132,
        frame_name="FRAME_CMD_PLAYER_SET_PAINT (input counterpart)",
        framepkg="FRAMEPKG_CMD_PLAYER_SET_PAINT",
        stcmd="stCmdPlayerSetPaint",
        confidence="high",
        evidence="BOOTFRAP_TYPE_USE_PAINT; class paintId/positionX/Y/Z match "
                 "dwPaintID/iPositionX/Y/Z; processing loads u32 +0xc/+0x10 "
                 "(dwObjID/dwPaintID).",
    ),
    18: dict(
        cls="PlayerSCMoveDirCommand",
        attrs="FrameSCSYNC",
        frame_id=1,
        frame_name="FRAME_CMD_PLAYERMOVE",
        framepkg="FRAMEPKG_CMD_PLAYERMOVE",
        stcmd="stCmdPlayerMove",
        confidence="high",
        evidence="BOOTFRAP_TYPE_PLAYER_MOVE; CSDT_FRAPBOOT_PLAYER_MOVE"
                 "{wMoveInfo:u16}; class info:u16 matches; processing reads "
                 "u16 +0xc.  .abc BOOT tag 18 carries wMoveInfo.",
    ),
    19: dict(
        cls="PlayerSCCommonAttackCommand",
        attrs="FrameSCSYNC",
        frame_id=28,
        frame_name="FRAME_CMD_PLAYCOMMONATTACKTMODE",
        framepkg="FRAMEPKG_CMD_PLAYCOMMONATTACKTMODE",
        stcmd="stCmdPlayCommonAttackMode",
        confidence="high",
        evidence="BOOTFRAP_TYPE_PLAYER_ATTACK; CSDT_FRAPBOOT_PLAYER_ATTACK"
                 "{bAttack:u8}; class field start:u8 matches; processing reads "
                 "u8 +0xc.  .abc BOOT tag 19 carries bAttack.",
    ),
    20: dict(
        cls="PlayerSCCommonAttackCommand",
        attrs="FrameSCSYNC",
        frame_id=5,
        frame_name="FRAME_CMD_ATTACKACTOR",
        framepkg="FRAMEPKG_CMD_ATTACKACTOR",
        stcmd="stCmdPlayerAttackPlayer",
        confidence="high",
        evidence="BOOTFRAP_TYPE_PLAYER_ATTACKWITHOBJ; struct bAttack:u8 + "
                 "wObjID:u16; class start:u8/objID:u16 matches; processing "
                 "reads u8 +0xc and u16 +0xe.  .abc BOOT tag 20.",
    ),
    21: dict(
        cls="(unresolved; skip path)",
        attrs="",
        frame_id=None,
        frame_name="(player same)",
        framepkg="(no CSDT_FRAPBOOT_PLAYER_SAME found)",
        stcmd="(none)",
        confidence="unresolved",
        evidence="BOOTFRAP_TYPE_PLAYER_SAME; jump table points at the skip "
                 "stub; no matching CSDT struct or GameLogic command class in "
                 "this metadata.",
    ),
    22: dict(
        cls="PlayerChangeCommand",
        attrs="FrameSCSYNC",
        frame_id=None,
        frame_name="(player change)",
        framepkg="CSDT_FRAPBOOT_PLAYER_CHANGE",
        stcmd="(player info change)",
        confidence="high",
        evidence="BOOTFRAP_TYPE_PLAYER_CHANGE; class field data:struct matches "
                 "the 16-field CSDT_FRAPBOOT_PLAYER_CHANGE payload; processing "
                 "passes the payload to the command converter.",
    ),
    23: dict(
        cls="SvrNtfPlayerReqQuitBattleCmd",
        attrs="CompilerGenerated",
        frame_id=None,
        frame_name="(request quit battle)",
        framepkg="CSDT_FRAPBOOT_REQ_QUITBATTLE",
        stcmd="(server notify)",
        confidence="high",
        evidence="BOOTFRAP_TYPE_REQ_QUITBATTLE; class playerId/times match "
                 "dwObjID/dwTimes; processing loads u32 +0x10/+0x14.",
    ),
    24: dict(
        cls="(no C# command class found; wire-only)",
        attrs="",
        frame_id=None,
        frame_name="(switch control object)",
        framepkg="CSDT_FRAPBOOT_SWITCH_CONTROL_OBJ",
        stcmd="(server notify)",
        confidence="medium",
        evidence="BOOTFRAP_TYPE_SWITCH_CONTROL_OBJ; struct dwOriginObjID/"
                 "dwCurrControlObjID/dwToControlObjID; no matching "
                 "Assets.Scripts.GameLogic class; CSPKG_SWITCH_CONTROL_OBJ_REQ "
                 "exists on the CS side.",
    ),
    25: dict(
        cls="(gameplay goal system; skip path)",
        attrs="",
        frame_id=None,
        frame_name="(gem effect)",
        framepkg="CSDT_FRAPBOOT_GAMEPLAY_GOAL_SYSTEM_GEM_EFFECT",
        stcmd="(mode-specific notify)",
        confidence="high",
        evidence="BOOTFRAP_TYPE_GAMEPLAY_GOAL_SYSTEM_GEM_EFFECT; jump table "
                 "points at the skip stub; struct dwObjID/dwEffectType/"
                 "dwEffectParam.",
    ),
    26: dict(
        cls="InBattleEffectBuyCommand",
        attrs="FrameSCSYNC",
        frame_id=None,
        frame_name="(in-battle effect buy)",
        framepkg="CSDT_FRAPBOOT_IN_BATTLE_EFFECT_BUY",
        stcmd="(server notify)",
        confidence="high",
        evidence="BOOTFRAP_TYPE_IN_BATTLE_EFFECT_BUY; class dwObjID/"
                 "dwEffectType/dwEffectID/dwBuffID/dwPosIndex match the wire "
                 "struct plus stBuyInfo.  Default handler.",
    ),
    27: dict(
        cls="InGameItemUseCommand",
        attrs="FrameSCSYNC",
        frame_id=None,
        frame_name="(in-game item use)",
        framepkg="CSDT_FRAPBOOT_INGAME_ITEM_USE",
        stcmd="(item use)",
        confidence="high",
        evidence="BOOTFRAP_TYPE_INGAME_ITEM_USE; class dwItemType/dwItemId/"
                 "iItemNum match stItemInfo; processing reads dwObjID +0xc "
                 "and the item sub-object at +0x10 (u32s +0x10/+0x14).",
    ),
}


# ---------------------------------------------------------------------------
# metadata


class Metadata:
    """Minimal v29 reader for the tables this analysis needs (read-only)."""

    def __init__(self, blob: bytes):
        self.blob = blob
        magic, version = struct.unpack_from("<Ii", blob, 0)
        if magic != 0xFAB11BAF or version != 29:
            raise ValueError(f"unexpected metadata header {magic:#x} v{version}")
        self._strings = None
        self._typedefs = None

    def pair(self, index: int) -> tuple[int, int]:
        return struct.unpack_from("<ii", self.blob, index * 8)

    def _string_table(self):
        if self._strings is None:
            start, size = self.pair(3)
            self._strings = self.blob[start:start + size]
        return self._strings

    def string(self, offset: int) -> str:
        table = self._string_table()
        end = table.find(b"\0", offset)
        return table[offset:end].decode("utf-8", "replace")

    def typedefs(self) -> list[dict]:
        start, size = self.pair(20)
        rows = []
        for i in range(size // 88):
            v = struct.unpack_from("<16i8H2I", self.blob, start + i * 88)
            rows.append({
                "index": i,
                "name": self.string(v[0]),
                "namespace": self.string(v[1]),
                "byval_type_index": v[2],
                "parent": v[5],
                "flags": v[7],
                "field_start": v[8],
                "method_start": v[9],
                "method_count": v[16],
                "field_count": v[18],
                "bitfield": v[24],
                "token": v[25],
            })
        return rows

    def fields(self, typedef: dict) -> list[dict]:
        start, _ = self.pair(12)
        rows = []
        for k in range(typedef["field_start"],
                       typedef["field_start"] + typedef["field_count"]):
            name_index, type_index, token = struct.unpack_from(
                "<2iI", self.blob, start + k * 12)
            rows.append({
                "index": k,
                "name": self.string(name_index),
                "type_index": type_index,
                "token": token,
            })
        return rows

    def methods(self, typedef: dict) -> list[dict]:
        start, _ = self.pair(6)
        rows = []
        for k in range(typedef["method_start"],
                       typedef["method_start"] + typedef["method_count"]):
            v = struct.unpack_from("<6i4H", self.blob, start + k * 32)
            rows.append({
                "index": k,
                "name": self.string(v[0]),
                "declaring_type": v[1],
                "return_type": v[2],
                "parameter_start": v[3],
                "token": v[5],
                "flags": v[6],
                "parameter_count": v[9],
            })
        return rows

    def enum_values(self, typedef: dict) -> list[tuple[str, int | None]]:
        """Return (name, zigzag-decoded default) for enum members."""
        default_start, default_size = self.pair(8)
        data_start, _ = self.pair(9)
        defaults: dict[int, int] = {}
        for i in range(default_size // 12):
            field_index, _type_index, data_index = struct.unpack_from(
                "<3i", self.blob, default_start + i * 12)
            defaults.setdefault(field_index, data_index)

        def compressed_int(offset: int) -> int:
            head = self.blob[offset]
            if head < 0x80:
                value, width = head, 1
            elif head < 0xC0:
                value, width = ((head & 0x3F) << 8) | self.blob[offset + 1], 2
            elif head < 0xE0:
                value, width = (
                    ((head & 0x1F) << 24)
                    | (self.blob[offset + 1] << 16)
                    | (self.blob[offset + 2] << 8)
                    | self.blob[offset + 3]
                ), 4
            elif head == 0xF0:
                value, width = struct.unpack_from("<I", self.blob, offset + 1)[0], 5
            else:
                raise ValueError(f"unsupported compressed int {head:#x}")
            del width
            return (value >> 1) ^ -(value & 1)

        rows = []
        for field in self.fields(typedef):
            data_index = defaults.get(field["index"])
            value = None
            if data_index is not None:
                value = compressed_int(data_start + data_index)
            rows.append((field["name"], value))
        return rows

    def type_name(self, type_index: int, byval: dict[int, int],
                  typedefs: list[dict]) -> str:
        if type_index in PRIMITIVE_WIDTH:
            return PRIMITIVE_WIDTH[type_index][0]
        for delta in (1, 2, 3, 0, 4):
            typedef_index = byval.get(type_index - delta)
            if typedef_index is not None:
                t = typedefs[typedef_index]
                prefix = f"{t['namespace']}." if t["namespace"] else ""
                return prefix + t["name"]
        return f"?Il2CppType{type_index}"

    def width(self, type_index: int, byval: dict[int, int],
              typedefs: list[dict]) -> int:
        if type_index in PRIMITIVE_WIDTH:
            return PRIMITIVE_WIDTH[type_index][1]
        return OPAQUE_WIDTH


def find_type(typedefs: list[dict], name: str,
              namespace: str | None = None) -> dict | None:
    for t in typedefs:
        if t["name"] == name and (namespace is None or t["namespace"] == namespace):
            return t
    return None


# ---------------------------------------------------------------------------
# libil2cpp


class Binary:
    def __init__(self, path: Path):
        self.blob = path.read_bytes()
        with path.open("rb") as handle:
            elf = ELFFile(handle)
            self._segments = [
                (p["p_vaddr"], p["p_vaddr"] + p["p_filesz"], p["p_offset"])
                for p in elf.iter_segments() if p["p_type"] == "PT_LOAD"
            ]
            dynamic = elf.get_section_by_name(".dynamic")
            self._tags = {tag.entry.d_tag: tag.entry.d_val for tag in dynamic.iter_tags()}
        self.relocations = self._read_relocations()

    def _read_relocations(self) -> dict[int, int]:
        start = self._tags.get("DT_RELA", 0)
        size = self._tags.get("DT_RELASZ", 0)
        relocations: dict[int, int] = {}
        for pos in range(start, start + size, 24):
            offset, _info, addend = struct.unpack_from("<QQq", self.blob, pos)
            relocations[offset] = addend
        return relocations

    def file_offset(self, static_va: int) -> int | None:
        for start, end, offset in self._segments:
            if start <= static_va < end:
                return offset + static_va - start
        return None

    def read(self, static_va: int, size: int) -> bytes:
        offset = self.file_offset(static_va)
        if offset is None:
            return b""
        return self.blob[offset:offset + size]

    def u16(self, file_offset: int) -> int:
        return struct.unpack_from("<H", self.blob, file_offset)[0]


def runtime_to_static(runtime_va: int) -> int:
    return runtime_va - LOAD_BASE


def disassemble(binary: Binary, static_va: int, size: int) -> list:
    if Cs is None:
        raise RuntimeError("capstone is required")
    offset = binary.file_offset(static_va)
    if offset is None:
        return []
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.detail = True
    return list(md.disasm(binary.blob[offset:offset + size], static_va))


TAIL_MIN_STATIC = 0x664D560
TAIL_MAX_STATIC = 0x664D7E4


def _tail_slot(binary: Binary, start_static: int) -> int | None:
    adrp_x8: int | None = None
    for ins in disassemble(binary, start_static, 0x20):
        if ins.mnemonic == "adrp" and ins.op_str.startswith("x8, #"):
            adrp_x8 = int(ins.op_str.split("#")[1], 16)
        elif ins.mnemonic == "ldr" and ins.op_str.startswith("x8, [x8, #"):
            if adrp_x8 is not None and adrp_x8 in (
                    PROC_SLOT_PAGE_RUNTIME, PROC_SLOT_PAGE_STATIC):
                imm = int(ins.op_str.split("#")[1].rstrip("]"), 16)
                return PROC_SLOT_PAGE_STATIC + imm
    return None


def handler_processing(binary: Binary, handler_static: int) -> tuple[int | None, int | None]:
    """Return (processing static VA, tail slot static VA) for one handler."""
    targets = []
    for ins in disassemble(binary, handler_static, 0x50):
        if ins.mnemonic.startswith("b") and ins.operands:
            last = ins.operands[-1]
            if getattr(last, "type", None) == ARM64_OP_IMM:
                target = last.imm
                if TAIL_MIN_STATIC <= target < TAIL_MAX_STATIC:
                    targets.append(target)
    for target in targets:
        slot = _tail_slot(binary, target)
        if slot is not None:
            return binary.relocations.get(slot), slot
    return None, None


def observed_reads(binary: Binary, processing_static: int, limit: int = 0xC0) -> list[tuple[int, int]]:
    """Collect loads from the payload pointer (x1) in the processing function."""
    instructions = disassemble(binary, processing_static, limit)
    if not instructions:
        return []
    taint: dict[str, int] = {"x1": 0}
    reads: list[tuple[int, int]] = []
    for ins in instructions:
        ops = ins.operands
        mnemonic = ins.mnemonic
        if mnemonic == "ret":
            break
        if mnemonic in ("mov", "movz") and len(ops) == 2 \
                and ops[0].type == ARM64_OP_REG and ops[1].type == ARM64_OP_REG:
            dst = ins.reg_name(ops[0].reg)
            src = ins.reg_name(ops[1].reg)
            if src in taint:
                taint[dst] = taint[src]
            else:
                taint.pop(dst, None)
        elif mnemonic == "add" and len(ops) == 3 \
                and ops[0].type == ARM64_OP_REG and ops[1].type == ARM64_OP_REG \
                and ops[2].type == ARM64_OP_IMM:
            dst = ins.reg_name(ops[0].reg)
            src = ins.reg_name(ops[1].reg)
            if src in taint:
                taint[dst] = taint[src] + ops[2].imm
            else:
                taint.pop(dst, None)
        elif mnemonic in ("ldrb", "ldrh", "ldr", "ldur", "ldrsb", "ldrsh", "ldrsw") \
                and len(ops) >= 2 and ops[0].type == ARM64_OP_REG \
                and ops[1].type == ARM64_OP_MEM:
            mem = ops[1].mem
            base = ins.reg_name(mem.base) if mem.base else None
            if base in taint:
                size = {"ldrb": 1, "ldrh": 2, "ldrsb": 1, "ldrsh": 2, "ldrsw": 4}.get(mnemonic)
                if mnemonic in ("ldr", "ldur"):
                    size = 8 if ins.reg_name(ops[0].reg).startswith("x") else 4
                reads.append((taint[base] + mem.disp, size))
        elif mnemonic == "ldp" and len(ops) == 3 and ops[0].type == ARM64_OP_REG \
                and ops[1].type == ARM64_OP_REG and ops[2].type == ARM64_OP_MEM:
            mem = ops[2].mem
            base = ins.reg_name(mem.base) if mem.base else None
            if base in taint:
                size = 8 if ins.reg_name(ops[0].reg).startswith("x") else 4
                reads.append((taint[base] + mem.disp, size))
                reads.append((taint[base] + mem.disp + size, size))
        elif mnemonic.startswith("bl"):
            # Keep only callee-saved register taint across calls.
            for reg in list(taint):
                if reg.startswith("x") and reg[1:].isdigit() and 19 <= int(reg[1:]) <= 28:
                    continue
                if reg.startswith("w") and reg[1:].isdigit() and 19 <= int(reg[1:]) <= 28:
                    continue
                del taint[reg]
    # De-duplicate preserving order.
    seen = set()
    unique = []
    for offset, size in reads:
        if (offset, size) in seen:
            continue
        seen.add((offset, size))
        unique.append((offset, size))
    return unique


# ---------------------------------------------------------------------------
# table building


def struct_fields(metadata: Metadata, typedef: dict, byval: dict[int, int],
                  typedefs: list[dict]) -> list[dict]:
    rows = []
    offset = 0
    for field in metadata.fields(typedef):
        size = metadata.width(field["type_index"], byval, typedefs)
        align = min(size, 4)
        offset = (offset + align - 1) // align * align
        rows.append({
            "name": field["name"],
            "type": metadata.type_name(field["type_index"], byval, typedefs),
            "offset": offset,
            "size": size,
        })
        offset += size
    return rows


def match_struct(rows: list[dict], reads: list[tuple[int, int]]) -> list[dict]:
    """Match payload reads (payload base = +0xc) to struct field offsets."""
    matched = []
    for read_offset, size in reads:
        struct_offset = read_offset - 0xC
        for row in rows:
            if row["offset"] == struct_offset and row["size"] >= size:
                matched.append({"read": f"+0x{read_offset:x}/{size}B",
                                "field": row["name"],
                                "type": row["type"],
                                "offset": f"0x{row['offset']:x}"})
                break
    return matched


def build(metadata_path: Path, binary_path: Path) -> dict:
    metadata = Metadata(metadata_path.read_bytes())
    typedefs = metadata.typedefs()
    byval = {t["byval_type_index"]: t["index"] for t in typedefs}
    binary = Binary(binary_path)

    boot = find_type(typedefs, *BOOTFRAP_ENUM)
    if boot is None:
        raise SystemExit("BOOTFRAP_TYPEDEF not found")
    boot_values = {name: value for name, value in metadata.enum_values(boot) if value is not None}
    by_value = {value: name for name, value in boot_values.items() if name != "value__"}

    frame_cmds = find_type(typedefs, *FRAME_CMD_ID_ENUM)
    frame_cmd_id_count = 0
    if frame_cmds is not None:
        frame_cmd_id_count = sum(
            1 for name, _ in metadata.enum_values(frame_cmds) if name != "value__")
    frame_info = find_type(typedefs, *FRAME_CMD_INFO)
    frame_info_fields = metadata.fields(frame_info) if frame_info is not None else []

    rows = []
    for type_index in range(1, 28):
        raw = binary.u16(DISPATCH_TABLE_FILE + (type_index - 1) * 2)
        handler_runtime = JUMP_BASE_RUNTIME + raw * 4
        if handler_runtime == DEFAULT_HANDLER_RUNTIME:
            kind = "default"
        elif handler_runtime == SKIP_HANDLER_RUNTIME:
            kind = "skip"
        else:
            kind = "handler"

        processing_static = None
        slot_static = None
        if kind == "handler":
            processing_static, slot_static = handler_processing(
                binary, runtime_to_static(handler_runtime))
        elif kind == "default":
            slot_static = PROC_SLOT_PAGE_STATIC + 0xBC0
            processing_static = binary.relocations.get(slot_static)

        reads = observed_reads(binary, processing_static) if processing_static else []

        boot_name = by_value.get(type_index, f"BOOTFRAP_TYPE_UNKNOWN_{type_index}")
        struct_name = "CSDT_FRAPBOOT_" + boot_name.removeprefix("BOOTFRAP_TYPE_")
        struct_name = {
            "CSDT_FRAPBOOT_GAMEOVERNTF": "CSDT_FRAPBOOT_GAMEOVERNTF",
            "CSDT_FRAPBOOT_ACNTSTATECHG": "CSDT_FRAPBOOT_ACNTSTATE",
            "CSDT_FRAPBOOT_AISTATECHG": "CSDT_FRAPBOOT_AISTATE",
            "CSDT_FRAPBOOT_ASSISTSTATECHG": "CSDT_FRAPBOOT_ASSISTSTATE",
            "CSDT_FRAPBOOT_USE_PAINT": "CSDT_FRAPBOOT_USE_PAINT_NTF",
            "CSDT_FRAPBOOT_PLAYER_ATTACKWITHOBJ": "CSDT_FRAPBOOT_PLAYER_ATTACKWITHOBJ",
            "CSDT_FRAPBOOT_AUTOCHESSBOUNTYMATCH_ADDCOIN":
                "CSDT_FRAPBOOT_AUTOCHESS_BOUNTYMATCH_ADDCOIN",
        }.get(struct_name, struct_name)

        struct = find_type(typedefs, struct_name, "CSProtocol")
        fields = struct_fields(metadata, struct, byval, typedefs) if struct else []
        matched = match_struct(fields, reads)

        candidate = CANDIDATES.get(type_index, {})
        rows.append({
            "type": type_index,
            "bootfrap_value": type_index,
            "bootfrap_name": boot_name,
            "switch_kind": kind,
            "handler_runtime": f"0x{handler_runtime:016x}",
            "handler_file": (f"0x{runtime_to_static(handler_runtime) - 0x1000:x}"
                             if kind == "handler" else ""),
            "processing_runtime": (f"0x{LOAD_BASE + processing_static:016x}"
                                   if processing_static else ""),
            "processing_file": (f"0x{processing_static - 0x1000:x}"
                                if processing_static else ""),
            "observed_reads": ", ".join(f"+0x{o:x}:{s}B" for o, s in reads),
            "csdt_struct": struct_name,
            "csdt_fields": "; ".join(f"{f['name']}:{f['type']}" for f in fields),
            "matched_fields": "; ".join(f"{m['read']}={m['field']}" for m in matched),
            "candidate_command_class": candidate.get("cls", ""),
            "candidate_class_attrs": candidate.get("attrs", ""),
            "frame_cmd_id": candidate.get("frame_id") or "",
            "frame_cmd_name": candidate.get("frame_name", ""),
            "framepkg_cmd": candidate.get("framepkg", ""),
            "stcmd_field": candidate.get("stcmd", ""),
            "confidence": candidate.get("confidence", "unresolved"),
            "evidence": candidate.get("evidence", ""),
        })

    kinds = {row["switch_kind"] for row in rows}
    return {
        "metadata": str(metadata_path),
        "binary": str(binary_path),
        "impl_runtime": f"0x{IMPL_RUNTIME:016x}",
        "impl_static": f"0x{IMPL_STATIC:x}",
        "switch_values": "1..27",
        "bootfrap_max": boot_values.get("BOOTFRAP_TYPE_MAX"),
        "bootfrap_value_names": len([n for n in boot_values
                                     if n.startswith("BOOTFRAP_TYPE_")
                                     and not n.endswith("_MAX")]),
        "framecmd_id_count": frame_cmd_id_count,
        "frame_cmd_info_count": len(frame_info_fields),
        "frame_cmd_info_first": [f["name"] for f in frame_info_fields[:8]],
        "handler_count": sum(1 for row in rows if row["switch_kind"] == "handler"),
        "default_count": sum(1 for row in rows if row["switch_kind"] == "default"),
        "skip_count": sum(1 for row in rows if row["switch_kind"] == "skip"),
        "kinds": sorted(kinds),
        "rows": rows,
    }


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = list(rows[0])
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, default=META)
    parser.add_argument("--binary", type=Path, default=LIB)
    parser.add_argument("--out", type=Path, default=OUT_CSV)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = build(args.metadata, args.binary)
    write_csv(result["rows"], args.out)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"implementation: {result['impl_runtime']} static {result['impl_static']}")
    print(f"switch values: {result['switch_values']}; "
          f"BOOTFRAP_TYPE_MAX={result['bootfrap_max']}; "
          f"BOOTFRAP value names={result['bootfrap_value_names']}")
    print(f"FRAME_CMD_INFO members: {result['frame_cmd_info_count']}; "
          f"FRAMECMD_ID_DEF commands: {result['framecmd_id_count']}; "
          f"handlers/default/skip = {result['handler_count']}/"
          f"{result['default_count']}/{result['skip_count']}")
    print(f"{'type':>4} {'bootfrap':<45} {'kind':<8} {'confidence':<11} candidate")
    for row in result["rows"]:
        print(f"{row['type']:>4} {row['bootfrap_name']:<45} "
              f"{row['switch_kind']:<8} {row['confidence']:<11} "
              f"{row['candidate_command_class']}")
    print(f"wrote {args.out} ({len(result['rows'])} types)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
