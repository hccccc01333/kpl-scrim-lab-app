# GameCore Host workspace

This directory is the productized entry for the GameCore offline host plan.

- Plan: `docs/gamecore_host.md`
- Existing low-level probes: `data/replays/_analysis/_host`
- Device target: MuMu `127.0.0.1:16384`, root ADB, `/data/local/tmp/gc`
- The host runs in its own process. It does not attach to the game, log in, or modify game files.

## Quick run

```bash
# H0: dlopen + ModuleInit
MSYS_NO_PATHCONV=1 bash host/scripts/run_probe.sh boot

# H1: one hosted databin table (83 svr2GamecoreCfg)
MSYS_NO_PATHCONV=1 bash host/scripts/run_probe.sh sim0

# H2: all 825 hosted databin tables
MSYS_NO_PATHCONV=1 bash host/scripts/run_probe.sh sim0b
```

The script pushes the prebuilt ARM64 probes and the required libraries. Rebuilds need
Android NDK r28b and the source under `data/replays/_analysis/_host`.

## H5 probe: real frame payloads -> CS slot0 -> consumer

`host/src/h5_probe.c` pushes each `.abc` frame command buffer verbatim into the
real CS slot0 (`PushCsBuffer` / `CommitCsBuffer`) and calls the real consumer
(`0x46B80E8`, split into `0x49CBC0C` drain + `0x46B8070` parse). One frame per
forked child keeps a faulting handler from killing the batch.

```bash
# extract real payloads from the sample .abc
python host/scripts/extract_frame_payloads.py \
  data/replays/samples/20261102_161129/*.abc

# run 200 frames with the captured command table
MSYS_NO_PATHCONV=1 bash host/scripts/run_h5_probe.sh \
  --mode isolated --limit 200 --skip-empty

# summarize the JSONL
python host/scripts/summarize_h5_probe.py host/build/h5probe/run_200.jsonl
```

`host/scripts/capture_cmd_table.py` re-captures the live command table if the
build or process state changes. Full design, evidence, and limits:
`docs/h5_consumer_probe.md`.

## Productized harness skeleton

Device run (after build):

```bash
MSYS_NO_PATHCONV=1 bash host/scripts/run_harness.sh
```

Current verified baseline:

```text
installed=825 verified=825 count_bad=0 row_bad=0 total_rows=205149
```

H4 context-init / H5 frame-tick / H6 state-output remain fail-closed stubs in
`gchost`. The separate H5 probe above exercises the real slot0 and consumer but
does not advance frames or emit player state.


`host/src/gchost.c` wraps the validated H0-H2 path: dependency/GameCore loading,
`ModuleInit`, fixture `meta.json` verification, and databin registration/verification.
Context construction, frame ticking, and state output are explicit fail-closed stubs.

```bash
NDK=/path/to/android-ndk-r28b bash host/scripts/build_host.sh
python host/scripts/validate_fixture.py host/fixtures/20261102_161129
```

See `docs/host_harness.md` for device run commands, arguments, exit codes, and the
stage-by-stage verification scope. The low-level probes above are unchanged.
