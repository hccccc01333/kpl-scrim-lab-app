# G7 状态类定位（2026-11-04，元数据 + 活体类指针）

## 1. 回放 UI 的逐人 KDA 状态

```text
Assets.Scripts.GameLogic.stHeroKDAInfo
    objID:u32  heroID:u32  killSoldier:u32  kill:u8  dead:u8  assist:u8

Assets.Scripts.GameLogic.CKdaHeroPtr
    heroKda: stHeroKDAInfo          (唯一字段)

持有者（元数据实证）：
  Assets.Scripts.GameSystem.HeroInfoItem._kdaHero      ← 团队面板每行（十人）
  Assets.Scripts.GameSystem.HeroInfoSideItem._kdaHero
  Assets.Scripts.GameSystem.HeroInfoHud._pickedKdaHero
  Assets.Scripts.GameSystem.NewTeamFightItem._kdaHero
  Assets.Scripts.GameSystem.TaoShaWatchHeroInfo.heroKdaInfo
  .CCustomKDALogic.m_viewData                          ← KDA 逻辑视图数据
```

**对象布局（推导）**：`CKdaHeroPtr` 实例 = `{klass@0x10, monitor@0x18, heroKda@0x20}`
其中 stHeroKDAInfo 为内联结构：objID@0x20, heroID@0x24, killSoldier@0x28,
kill@0x2c, dead@0x2d, assist@0x2e。

## 2. 30 秒团队经济快照（G9 真值同源）

```text
CSProtocol.COMDT_GAME_30SEC_INFO
    dwGhostLevel, dwKillCnt, wKillDarkCnt, dwKillDragonCnt, dwKillMonsterCnt,
    dwKillEnemyMonsterCnt, dwKillSoldierCnt, dwCoinCnt, dwCoinIntervalCnt,
    dwRedBuffCnt, dwBlueBuffCnt, dwYellowBuffCnt, iXPos, iZPos
```

这是客户端每 30 秒同步包（SCPKG_GAME_30SEC_INFO）的载荷 —— 与营地
"30 秒团队金币"同源，可直接作为 G9 对拍基准。

## 3. 其它状态类

```text
Assets.Scripts.GameLogic.GamePlayerCenter   ← 玩家注册表（_hostPlayer/playersCache）
Assets.Scripts.GameLogic.Player (196 字段)  ← 玩家档案（PlayerId/heroConfigIDList/...）
Assets.Scripts.GameLogic.Dimension.DS.Network.*  ← DS 锁步传输层（见 g5 文档）
```

## 4. 活体类指针（pid 2135 实测）

```text
CKdaHeroPtr       0x7311b2cde270 / 0x73136cb4ca90
HeroInfoItem      0x73136cb53390
GamePlayerCenter  0x7313cc24f120 / 0x73146c754da0
（CCustomKDALogic 未加载 —— UI 逻辑类，未打开对应界面）
```

## 5. 活体实例读取的阻塞

- 实例扫描需 ~30-50 分钟（GC 堆 ~5.4GB），MuMu 的游戏每 ~10-30 分钟
  崩溃/重启一次 → 扫描目标进程消失，读数为 0。
- **优化方案（下次执行）**：先解析类指针，再只扫含托管对象的热点区域
  （从元数据命中地址 0x73136c08…/0x73146c11… 所在 region 反推，约数百 MB，
  5 分钟内完成）。
- 游戏暂停时状态稳定，但模拟器本身仍会崩；建议缩短单次扫描窗口。

## 6. 活体 KDA 读取成功（2026-11-04，pid 2023，回放播放中）

定向扫描（2 分钟类解析 + 4 分钟热点扫描）在 `CKdaHeroPtr` 实例上直接读出
十人 KDA。对象布局实测：

```text
CKdaHeroPtr 实例（0x20 B）:
  +0x00 klass
  +0x08 u32 objID      +0x0c u32 heroID
  +0x10 u32 killSoldier
  +0x14 u8 kill, u8 dead, u8 assist, u8 pad
```

实测数据（回放约 3 分钟处，游戏播放中）：

```text
objID=37  heroID=153 killSoldier= 4 K/D/A=1/3/1
objID=51  heroID=156 killSoldier= 5 K/D/A=0/3/2
objID=25  heroID=109 killSoldier=23 K/D/A=3/1/1
objID=44  heroID=196 killSoldier=21 K/D/A=1/0/2
objID=12  heroID=175 killSoldier= 4 K/D/A=1/0/4
objID=33  heroID=199 killSoldier=11 K/D/A=0/2/1
objID=65  heroID=167 killSoldier= 7 K/D/A=3/1/3
objID=20  heroID=141 killSoldier=15 K/D/A=0/1/2
objID=58  heroID=140 killSoldier=12 K/D/A=4/1/2
objID= 8  heroID=123 killSoldier=14 K/D/A=2/3/1
```

（同一进程两次读取 killSoldier 变化 → 数据是活的）

同时命中：
- `HeroInfoItem` ×10 实例（camp/pos 对：(2,4)..(2,0),(1,4)..(1,0)，间距 0xF0）
- `HeroInfoSideItem` ×10
- `GamePlayerCenter` ×3

产物：`host/build/g5/kda_live.json`、`host/build/g5/kda_inst2.json`

## 7. 待完成

- 金币：`COM_GAME_30SEC_INFO.dwCoinCnt`（30s 快照）或 UI 金币字段
- HP/等级/装备/位置：`ActorData`/`Player` 相关类
- objID → `.abc` entity/英雄 映射（英雄配置表）
- 与终局真值（27:6 面板）对拍
