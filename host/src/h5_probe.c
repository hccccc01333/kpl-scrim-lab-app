/* h5_probe.c — H5 probe: push real `.abc` frame payloads into CS slot0 and
 * call the real GameCore CS consumer (`base+0x46B80E8`).
 *
 * This runs as a private ARM64 host process on the device.  It does not attach
 * to the game, does not call game functions in the game process, and does not
 * modify game files.  Snapshot regions are copied read-only from a local
 * capture; the GameCore library is loaded by the host itself.
 *
 * What is real:
 *   - libGameCore + ModuleInit (H0 path);
 *   - the captured process snapshot and context (A1 path);
 *   - the CS ring object: either constructed with the real ctor/init
 *     (`0x49CBD88` / `0x49CBEF4`) or reused from the snapshot;
 *   - PushCsBuffer / CommitCsBuffer (real exports);
 *   - the CS consumer `0x46B80E8` (real code) and, optionally, the captured
 *     command dispatch table + BSS slots (`--cmd-table`).
 *
 * What is intentionally not claimed:
 *   - the `.abc` frame buffer is `CSDT_FRAPBOOT_INFO` bytes, not a proven
 *     native CS TDR stream; the probe measures what the consumer does with
 *     those exact bytes, it does not translate them;
 *   - a returned consumer does not prove frame advance or gameplay state.
 *
 * Crash isolation: in `--mode isolated` every frame runs in a forked child,
 * so a faulting consumer handler cannot kill the whole run.  The child reports
 * the faulting PC (base-relative) and the stream header that led to dispatch.
 */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <ucontext.h>
#include <unistd.h>
#include <dlfcn.h>

#ifndef MAP_FIXED_NOREPLACE
#define MAP_FIXED_NOREPLACE 0x100000
#endif

#define MAX_REGIONS 128
#define MAX_FRAMES 400000
#define LIB_END 0x544D478ULL
#define RESULT_MAGIC 0x48354652u   /* "H5FR" */
#define CRASH_MAGIC  0x48354352u   /* "H5CR" */
#define ALT_STACK_BYTES 32768

struct region { uintptr_t start, end; };
struct frame_meta { uint64_t index, seq, offset; uint32_t len, entries, parsed; };

struct slot_snap {
    uint32_t ring_size, pending, write, read, committed;
    uint64_t staging;
};

struct result {
    uint32_t magic, version;
    uint64_t frame_index, seq;
    uint32_t len;
    uint32_t preflight;      /* 0 short, 1 out-of-range, 2 in-range */
    uint32_t opcode, arg, flag, in_range;
    uint64_t handler;        /* absolute dispatch target, 0 if not dispatched */
    uint64_t staging;
    uint32_t pending;
    uint32_t commit_rc;
    struct slot_snap before, after_push, after_commit, after_consumer;
    uint64_t cons_base_before, cons_base_after;
    uint32_t cons_cap_before, cons_cap_after;
    uint32_t cons_used_before, cons_used_after;
    uint32_t drained;
    uint32_t bytes_match;
    uint32_t consumer_returned;
    uint32_t stage;          /* last completed stage */
    uint32_t reserved;
    uint32_t tick_returned;
    /* Dispatch trace, written by host table wrappers in the child. */
    uint32_t trace_total, trace_0d, trace_83, trace_84, trace_32, trace_other;
    uint32_t trace_39, trace_3a, trace_3b, trace_34, trace_48, trace_4d, trace_73;
    uint32_t trace_last_op, trace_last_arg;
    /* Context-region diff around one frame (optional --diff-context). */
    uint64_t ctx_start, ctx_size, ctx_hash_before, ctx_hash_after;
    uint64_t ctx_first_diff;
    uint32_t ctx_diff_bytes;
    uint32_t diff_n;
    uint64_t diff_addr[32], diff_old[32], diff_new[32];
};

typedef void (*cs_handler_fn)(void **, int, int);

struct crash {
    uint32_t magic, signo;
    uint64_t pc, fault, lr, sp, x0;
    uint32_t stage, opcode, arg, reserved;
    uint64_t x1, x2, x3, x4, x5, x6, x7, x8;
};

static uintptr_t g_base, g_old_base, g_old_end, g_context, g_binder;
static int g_no_publish_context;
static struct region g_regions[MAX_REGIONS];
static int g_nregions;
static uintptr_t g_slot0;
static int g_push_mode = 1, g_consumer_mode = 1, g_reuse_slot0 = 0, g_stock_init = 0;
static int g_init_slot1 = 0;
static int g_tick = 0;
static float g_tick_delta = 0.033f;
static int g_split_consumer = 1;
static uint32_t g_cmd_count;
static uintptr_t g_table_base;
static int g_child_fd = -1;
static volatile sig_atomic_t g_stage;
static volatile uint32_t g_last_opcode, g_last_arg;
static int g_verbose = 1;
static int g_trace_dispatch;
static int g_trace_print;
static int g_diff_context;
static struct result *g_trace_result;
static cs_handler_fn g_orig_handlers[65536];

static uint64_t fnv1a64(const void *p, size_t n) {
    const uint8_t *b = p;
    uint64_t h = 0xcbf29ce484222325ULL;
    for (size_t i = 0; i < n; i++) {
        h ^= b[i];
        h *= 0x100000001b3ULL;
    }
    return h;
}

static void say(const char *fmt, ...) {
    if (!g_verbose) return;
    va_list ap; va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    fputc('\n', stderr);
    fflush(stderr);
    va_end(ap);
}

static unsigned long long parse_u64(const char *s) {
    char *end = NULL;
    unsigned long long v = strtoull(s, &end, 0);
    if (!s[0] || (end && *end)) {
        say("invalid number: %s", s);
        exit(2);
    }
    return v;
}

static int read_all(int fd, void *dst, size_t size) {
    size_t off = 0;
    while (off < size) {
        ssize_t n = read(fd, (char *)dst + off, size - off);
        if (n < 0) {
            if (errno == EINTR) continue;
            return -1;
        }
        if (n == 0) break;
        off += (size_t)n;
    }
    return (int)off;
}

static int in_regions(uintptr_t addr) {
    for (int i = 0; i < g_nregions; i++)
        if (addr >= g_regions[i].start && addr < g_regions[i].end) return 1;
    return 0;
}

static int in_lib(uintptr_t addr) {
    return addr >= g_base && addr < g_base + LIB_END;
}

/* Check [addr, addr+size) is covered by a writable /proc/self/maps region. */
static int writable_range(uintptr_t addr, size_t size) {
    FILE *f = fopen("/proc/self/maps", "r");
    if (!f) return 0;
    char line[512];
    int ok = 0;
    while (fgets(line, sizeof line, f)) {
        unsigned long long lo, hi;
        char perms[8];
        if (sscanf(line, "%llx-%llx %7s", &lo, &hi, perms) != 3) continue;
        if (lo <= addr && addr + size <= hi && perms[1] == 'w') { ok = 1; break; }
    }
    fclose(f);
    return ok;
}

static void crash_handler(int sig, siginfo_t *si, void *ctx) {
    struct crash c;
    memset(&c, 0, sizeof c);
    c.magic = CRASH_MAGIC;
    c.signo = (uint32_t)sig;
    c.fault = (uint64_t)(uintptr_t)si->si_addr;
    if (ctx) {
        ucontext_t *uc = (ucontext_t *)ctx;
        c.pc = (uint64_t)uc->uc_mcontext.pc;
        c.lr = (uint64_t)uc->uc_mcontext.regs[30];
        c.sp = (uint64_t)uc->uc_mcontext.sp;
        c.x0 = (uint64_t)uc->uc_mcontext.regs[0];
        c.x1 = (uint64_t)uc->uc_mcontext.regs[1];
        c.x2 = (uint64_t)uc->uc_mcontext.regs[2];
        c.x3 = (uint64_t)uc->uc_mcontext.regs[3];
        c.x4 = (uint64_t)uc->uc_mcontext.regs[4];
        c.x5 = (uint64_t)uc->uc_mcontext.regs[5];
        c.x6 = (uint64_t)uc->uc_mcontext.regs[6];
        c.x7 = (uint64_t)uc->uc_mcontext.regs[7];
        c.x8 = (uint64_t)uc->uc_mcontext.regs[8];
    }
    c.stage = (uint32_t)g_stage;
    c.opcode = g_last_opcode;
    c.arg = g_last_arg;
    if (g_child_fd >= 0) {
        (void)!write(g_child_fd, &c, sizeof c);
    } else {
        char msg[320];
        unsigned long long pc = (unsigned long long)c.pc;
        unsigned long long pc_rel = pc;
        if (pc >= g_base && pc < g_base + LIB_END) pc_rel = pc - g_base;
        int n = snprintf(msg, sizeof msg,
                         "{\"event\":\"crash\",\"signal\":%u,\"pc\":\"0x%llx\","
                         "\"pc_abs\":\"0x%llx\",\"fault\":\"0x%llx\","
                         "\"stage\":%u,\"opcode\":%u,\"arg\":%u,"
                         "\"lr\":\"0x%llx\",\"sp\":\"0x%llx\",\"x0\":\"0x%llx\"}\n",
                         c.signo, pc_rel, pc, (unsigned long long)c.fault,
                         c.stage, c.opcode, c.arg, (unsigned long long)c.lr,
                         (unsigned long long)c.sp, (unsigned long long)c.x0);
        if (n > 0) (void)!write(STDOUT_FILENO, msg, (size_t)n);
    }
    _exit(128 + (sig & 0x7f));
}

static void install_crash_handlers(int for_child) {
    static char alt_stack[ALT_STACK_BYTES];
    stack_t ss;
    memset(&ss, 0, sizeof ss);
    ss.ss_sp = alt_stack;
    ss.ss_size = sizeof alt_stack;
    (void)sigaltstack(&ss, NULL);

    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_sigaction = crash_handler;
    sa.sa_flags = SA_SIGINFO | SA_ONSTACK;
    sigemptyset(&sa.sa_mask);
    int sigs[] = {SIGSEGV, SIGBUS, SIGILL, SIGFPE, SIGABRT, SIGALRM, SIGSYS};
    for (unsigned i = 0; i < sizeof sigs / sizeof sigs[0]; i++)
        (void)sigaction(sigs[i], &sa, NULL);
    (void)for_child;
}

static void *openlib(const char *dir, const char *name) {
    char path[512];
    snprintf(path, sizeof path, "%s/%s", dir, name);
    void *h = dlopen(path, RTLD_LAZY | RTLD_GLOBAL);
    if (!h) say("dlopen %s: %s", path, dlerror());
    return h;
}

static int read_file(const char *path, void *dst, size_t size) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) return -1;
    int n = read_all(fd, dst, size);
    close(fd);
    return n == (int)size ? 0 : -1;
}

static int map_snapshot(const char *dir, int *mapped_out, int *failed_out) {
    char path[1024];
    snprintf(path, sizeof path, "%s/regions.tsv", dir);
    FILE *f = fopen(path, "r");
    if (!f) { say("open %s: %s", path, strerror(errno)); return -1; }
    char line[4096];
    int mapped = 0, failed = 0;
    while (fgets(line, sizeof line, f)) {
        if (line[0] == 's' || line[0] == '#' || line[0] == '\n') continue;
        char start_s[64], end_s[64], perms[16], rpath[1024], file[1024], size_s[64], sha[128];
        if (sscanf(line, "%63s\t%63s\t%15s\t%1023s\t%1023s\t%63s\t%127s",
                   start_s, end_s, perms, rpath, file, size_s, sha) != 7) continue;
        uintptr_t start = (uintptr_t)parse_u64(start_s);
        uintptr_t end = (uintptr_t)parse_u64(end_s);
        size_t size = end > start ? end - start : 0;
        if (!size) continue;
        void *p = mmap((void *)start, size, PROT_READ | PROT_WRITE,
                       MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0);
        if (p == MAP_FAILED) {
            say("mmap %#lx-%#lx failed: %s", (unsigned long)start,
                (unsigned long)end, strerror(errno));
            failed++;
            continue;
        }
        char rp[1200];
        snprintf(rp, sizeof rp, "%s/%s", dir, file);
        if (read_file(rp, p, size) != 0) {
            say("read %s failed", rp);
            failed++;
            continue;
        }
        if (g_nregions < MAX_REGIONS) {
            g_regions[g_nregions].start = start;
            g_regions[g_nregions].end = end;
            g_nregions++;
        }
        mapped++;
    }
    fclose(f);
    *mapped_out = mapped;
    *failed_out = failed;
    return 0;
}

static void relocate_snapshot(uintptr_t old_base, uintptr_t old_end, uintptr_t new_base) {
    uint64_t count = 0;
    for (int i = 0; i < g_nregions; i++) {
        uint64_t *q = (uint64_t *)g_regions[i].start;
        size_t n = (g_regions[i].end - g_regions[i].start) / 8;
        for (size_t j = 0; j < n; j++) {
            uint64_t v = q[j];
            if (v >= old_base && v < old_end) {
                q[j] = v + (new_base - old_base);
                count++;
            }
        }
    }
    say("rebased libGameCore pointers=%llu", (unsigned long long)count);
}

static void *h5_alloc(uint32_t size) { return malloc(size); }
static void h5_free(void *ptr) { free(ptr); }

static void *make_cs_obj(uint32_t ring_size, const char *name) {
    void *obj = calloc(1, 0x90);
    if (!obj) { say("%s calloc failed", name); exit(4); }
    say("%s calloc obj=%p", name, obj);
    ((void (*)(void *))(g_base + 0x49CBD88ULL))(obj);
    say("%s ctor done vtable=%#lx", name, (unsigned long)*(uintptr_t *)obj);
    if (g_stock_init) {
        ((void (*)(void *, uint32_t, uint32_t, void *, void *))
            (g_base + 0x49CBEF4ULL))(obj, ring_size, 0, 0, 0);
        say("%s stock init returned", name);
    } else {
        /* Field-for-field equivalent of 0x49CBEF4 with host allocators. */
        uint32_t staging = ring_size / 2 < 0x20 ? 0x20 : ring_size / 2;
        void *ring = calloc(1, ring_size);
        void *staging_buf = calloc(1, staging);
        if (!ring || !staging_buf) { say("%s buffer alloc failed", name); exit(4); }
        *(void **)((uintptr_t)obj + 0x78) = (void *)h5_alloc;
        *(void **)((uintptr_t)obj + 0x80) = (void *)h5_free;
        *(void **)((uintptr_t)obj + 0x08) = ring;
        *(uint32_t *)((uintptr_t)obj + 0x10) = ring_size;
        *(void **)((uintptr_t)obj + 0x18) = staging_buf;
        *(uint32_t *)((uintptr_t)obj + 0x20) = staging;
        say("%s manual init (stock init bypassed): ring=%p staging=%p cap=%#x",
            name, ring, staging_buf, staging);
    }
    return obj;
}

static void install_slot0(uint32_t ring_size) {
    void *obj = make_cs_obj(ring_size, "slot0");
    *(void **)(g_base + 0x52C3250ULL) = obj;
    g_slot0 = (uintptr_t)obj;
    say("slot0 fresh obj=%#lx vtable=%#lx ring=%#x cap=%#x staging=%#lx",
        (unsigned long)g_slot0, (unsigned long)*(uintptr_t *)obj,
        *(uint32_t *)(g_slot0 + 0x10), *(uint32_t *)(g_slot0 + 0x20),
        (unsigned long)*(uintptr_t *)(g_slot0 + 0x18));
}

static void install_slot1(uint32_t ring_size) {
    if (*(uintptr_t *)(g_base + 0x52C3258ULL)) return;
    void *obj = make_cs_obj(ring_size, "slot1");
    *(void **)(g_base + 0x52C3258ULL) = obj;
    say("slot1 fresh obj=%#lx vtable=%#lx ring=%#x cap=%#x staging=%#lx",
        (unsigned long)(uintptr_t)obj, (unsigned long)*(uintptr_t *)obj,
        *(uint32_t *)((uintptr_t)obj + 0x10), *(uint32_t *)((uintptr_t)obj + 0x20),
        (unsigned long)*(uintptr_t *)((uintptr_t)obj + 0x18));
}

static void snap_slot0(uintptr_t obj, struct slot_snap *s) {
    memset(s, 0, sizeof *s);
    if (!obj) return;
    s->ring_size = *(uint32_t *)(obj + 0x10);
    s->staging = *(uint64_t *)(obj + 0x18);
    s->pending = *(uint32_t *)(obj + 0x24);
    s->write = *(uint32_t *)(obj + 0x2c);
    s->read = *(uint32_t *)(obj + 0x30);
    s->committed = *(uint32_t *)(obj + 0x34);
}

static int load_cmd_table(const char *path, int *entries_out, int *slots_out,
                          int *zero_out, int *conflict_out) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) { say("open %s: %s", path, strerror(errno)); return -1; }
    struct stat st;
    if (fstat(fd, &st) != 0 || st.st_size < 36) { close(fd); return -1; }
    size_t size = (size_t)st.st_size;
    uint8_t *buf = malloc(size);
    if (!buf) { close(fd); return -1; }
    if (read_all(fd, buf, size) != (int)size) { free(buf); close(fd); return -1; }
    close(fd);

    uint32_t version, count, nslots;
    uint64_t table_off, reserved;
    if (memcmp(buf, "KCMD", 4) != 0) { say("cmd table: bad magic"); free(buf); return -1; }
    memcpy(&version, buf + 4, 4);
    memcpy(&count, buf + 8, 4);
    uint64_t nslots64;
    memcpy(&nslots64, buf + 12, 8);
    memcpy(&table_off, buf + 20, 8);
    memcpy(&reserved, buf + 28, 8);
    (void)reserved;
    nslots = (uint32_t)nslots64;
    if (version != 1 || nslots64 > 0x100000) {
        say("cmd table: version=%u nslots=%llu unsupported", version,
            (unsigned long long)nslots64);
        free(buf); return -1;
    }
    size_t need = 36 + (size_t)count * 16 + (size_t)nslots * 8;
    if (count > 0x10000 || nslots > 0x100000 || size < need) {
        say("cmd table: invalid size count=%u slots=%u bytes=%zu need=%zu",
            count, nslots, size, need);
        free(buf); return -1;
    }
    uintptr_t table = g_base + (uintptr_t)table_off;
    if (!in_lib(table) || !writable_range(table, (size_t)count * 16)) {
        say("cmd table: table address %#lx not writable in lib", (unsigned long)table);
        free(buf); return -1;
    }
    memcpy((void *)table, buf + 36, (size_t)count * 16);
    /* Rebase handler offsets in place. */
    for (uint32_t i = 0; i < count; i++) {
        uint64_t *entry = (uint64_t *)(table + (uintptr_t)i * 16);
        uint64_t handler_off = entry[0];
        entry[0] = handler_off ? g_base + handler_off : 0;
    }
    *(uintptr_t *)(g_base + 0x544D340ULL) = table;
    *(uint32_t *)(g_base + 0x5272368ULL) = count;
    g_cmd_count = count;
    g_table_base = table;

    int installed = 0, zero = 0, conflicts = 0, skipped = 0;
    const uint8_t *slot_data = buf + 36 + (size_t)count * 16;
    for (uint32_t i = 0; i < nslots; i++) {
        uint32_t slot_off, target_off;
        memcpy(&slot_off, slot_data + (size_t)i * 8, 4);
        memcpy(&target_off, slot_data + (size_t)i * 8 + 4, 4);
        uintptr_t slot = g_base + slot_off;
        if (!in_lib(slot) || !writable_range(slot, 8)) { skipped++; continue; }
        uintptr_t target = target_off ? g_base + target_off : 0;
        uintptr_t *p = (uintptr_t *)slot;
        if (*p == 0) {
            if (target) { *p = target; installed++; }
            else zero++;
        } else if (*p == target) {
            installed++;
        } else {
            conflicts++;
        }
    }
    say("cmd table installed: count=%u table=%#lx slots=%d zero=%d conflict=%d skipped=%d",
        count, (unsigned long)table, installed, zero, conflicts, skipped);
    *entries_out = (int)count;
    *slots_out = installed;
    *zero_out = zero;
    *conflict_out = conflicts;
    free(buf);
    return 0;
}

static int load_frames(const char *dir, struct frame_meta **meta_out,
                       uint8_t **blob_out, size_t *blob_size_out, int *count_out) {
    char path[1024];
    snprintf(path, sizeof path, "%s/index.tsv", dir);
    FILE *f = fopen(path, "r");
    if (!f) { say("open %s: %s", path, strerror(errno)); return -1; }
    struct frame_meta *meta = calloc(MAX_FRAMES, sizeof *meta);
    if (!meta) { fclose(f); return -1; }
    char line[512];
    int n = 0;
    while (fgets(line, sizeof line, f)) {
        if (line[0] == '#' || line[0] == '\n') continue;
        uint64_t index, seq, offset;
        unsigned len, entries, parsed;
        if (sscanf(line, "%llu\t%llu\t%llu\t%u\t%u\t%u",
                   (unsigned long long *)&index, (unsigned long long *)&seq,
                   (unsigned long long *)&offset, &len, &entries, &parsed) != 6)
            continue;
        if (n >= MAX_FRAMES) break;
        meta[n].index = index;
        meta[n].seq = seq;
        meta[n].offset = offset;
        meta[n].len = len;
        meta[n].entries = entries;
        meta[n].parsed = parsed;
        n++;
    }
    fclose(f);

    snprintf(path, sizeof path, "%s/frames.bin", dir);
    int fd = open(path, O_RDONLY);
    if (fd < 0) { say("open %s: %s", path, strerror(errno)); free(meta); return -1; }
    struct stat st;
    if (fstat(fd, &st) != 0 || st.st_size <= 0) { close(fd); free(meta); return -1; }
    size_t size = (size_t)st.st_size;
    uint8_t *blob = malloc(size);
    if (!blob || read_all(fd, blob, size) != (int)size) {
        close(fd); free(blob); free(meta); return -1;
    }
    close(fd);
    for (int i = 0; i < n; i++) {
        if (meta[i].offset > size || meta[i].len > size - meta[i].offset) {
            say("frame %llu out of bounds (offset=%llu len=%u size=%zu)",
                (unsigned long long)meta[i].index,
                (unsigned long long)meta[i].offset, meta[i].len, size);
            free(blob); free(meta); return -1;
        }
    }
    *meta_out = meta;
    *blob_out = blob;
    *blob_size_out = size;
    *count_out = n;
    return 0;
}

static void preflight(const uint8_t *payload, uint32_t len, struct result *r) {
    r->preflight = 0;
    r->opcode = r->arg = r->flag = r->in_range = 0;
    r->handler = 0;
    if (len < 4) return;
    uint32_t header;
    memcpy(&header, payload, 4);
    uint32_t opcode = header & 0xffffu;
    r->opcode = opcode;
    r->arg = header >> 16;
    r->flag = (header & 0x40000000u) ? 0u : 1u;
    r->in_range = opcode < g_cmd_count;
    if (r->in_range) {
        r->preflight = 2;
        uintptr_t entry = g_table_base + (uintptr_t)opcode * 16;
        if (in_lib(entry) && in_lib(entry + 8))
            r->handler = *(uintptr_t *)entry;
    } else {
        r->preflight = 1;
    }
}

static void trace_common(uint32_t op, void **cursor, int flag, int arg) {
    if (g_trace_print) {
        uint32_t hdr = cursor && *cursor ? *(uint32_t *)((char *)*cursor - 4) : 0;
        fprintf(stderr, "dispatch op=%#x arg=%#x flag=%d cursor=%p hdr=%#x\n",
                op, arg, flag, cursor ? *cursor : NULL, hdr);
        fflush(stderr);
    }
    if (g_trace_result) {
        g_trace_result->trace_total++;
        if (op == 0x0d) g_trace_result->trace_0d++;
        else if (op == 0x83) g_trace_result->trace_83++;
        else if (op == 0x84) g_trace_result->trace_84++;
        else if (op == 0x32) g_trace_result->trace_32++;
        else if (op == 0x39) g_trace_result->trace_39++;
        else if (op == 0x3a) g_trace_result->trace_3a++;
        else if (op == 0x3b) g_trace_result->trace_3b++;
        else if (op == 0x34) g_trace_result->trace_34++;
        else if (op == 0x48) g_trace_result->trace_48++;
        else if (op == 0x4d) g_trace_result->trace_4d++;
        else if (op == 0x73) g_trace_result->trace_73++;
        else g_trace_result->trace_other++;
        g_trace_result->trace_last_op = op;
        g_trace_result->trace_last_arg = (uint32_t)arg;
    }
    cs_handler_fn h = g_orig_handlers[op];
    if (h) h(cursor, flag, arg);
}

#define TRACE_OP(op) \
    static void trace_op_##op(void **cursor, int flag, int arg) { \
        trace_common(op, cursor, flag, arg); \
    }
TRACE_OP(0x0d)
TRACE_OP(0x12e)
TRACE_OP(0x11f)
TRACE_OP(0x32)
TRACE_OP(0x34)
TRACE_OP(0x39)
TRACE_OP(0x3a)
TRACE_OP(0x3b)
TRACE_OP(0x48)
TRACE_OP(0x4d)
TRACE_OP(0x73)
TRACE_OP(0x83)
TRACE_OP(0x84)

static void install_trace_wrappers(void) {
    struct { uint32_t op; cs_handler_fn fn; } map[] = {
        {0x0d, trace_op_0x0d}, {0x12e, trace_op_0x12e},
        {0x11f, trace_op_0x11f}, {0x32, trace_op_0x32},
        {0x34, trace_op_0x34}, {0x39, trace_op_0x39},
        {0x3a, trace_op_0x3a}, {0x3b, trace_op_0x3b},
        {0x48, trace_op_0x48}, {0x4d, trace_op_0x4d},
        {0x73, trace_op_0x73}, {0x83, trace_op_0x83},
        {0x84, trace_op_0x84},
    };
    int installed = 0;
    for (size_t i = 0; i < sizeof map / sizeof map[0]; i++) {
        uint32_t op = map[i].op;
        if (op >= g_cmd_count) continue;
        uintptr_t entry = g_table_base + (uintptr_t)op * 16;
        uintptr_t orig = *(uintptr_t *)entry;
        if (!orig) continue;
        g_orig_handlers[op] = (cs_handler_fn)orig;
        *(uintptr_t *)entry = (uintptr_t)map[i].fn;
        installed++;
    }
    say("dispatch trace wrappers installed=%d", installed);
}

static void execute_frame(const struct frame_meta *m, const uint8_t *payload,
                          struct result *r) {
    memset(r, 0, sizeof *r);
    r->magic = RESULT_MAGIC;
    r->version = 1;
    r->frame_index = m->index;
    r->seq = m->seq;
    r->len = m->len;
    g_trace_result = r;

    uint8_t *ctx_copy = NULL;
    uintptr_t ctx_start = 0;
    size_t ctx_size = 0;
    if (g_diff_context) {
        for (int i = 0; i < g_nregions; i++) {
            if (g_regions[i].start <= g_context && g_context < g_regions[i].end) {
                ctx_start = g_regions[i].start;
                ctx_size = g_regions[i].end - g_regions[i].start;
                break;
            }
        }
        if (ctx_size && ctx_size <= 64 * 1024 * 1024) {
            ctx_copy = malloc(ctx_size);
            if (ctx_copy) {
                memcpy(ctx_copy, (void *)ctx_start, ctx_size);
                r->ctx_start = ctx_start;
                r->ctx_size = ctx_size;
                r->ctx_hash_before = fnv1a64(ctx_copy, ctx_size);
            }
        }
    }
    preflight(payload, m->len, r);
    g_last_opcode = r->opcode;
    g_last_arg = r->arg;

    uintptr_t obj = *(uintptr_t *)(g_base + 0x52C3250ULL);
    snap_slot0(obj, &r->before);
    g_stage = 0;
    r->stage = 0;

    if (g_push_mode) {
        void *staging = ((void *(*)(uint32_t))(g_base + 0x460A3ACULL))(m->len);
        r->staging = (uintptr_t)staging;
        if (staging && m->len) memcpy(staging, payload, m->len);
        r->pending = *(uint32_t *)(obj + 0x24);
        snap_slot0(obj, &r->after_push);
        g_stage = 1;
        r->stage = 1;
        r->commit_rc = ((int (*)(void))(g_base + 0x460A3E4ULL))();
        snap_slot0(obj, &r->after_commit);
        g_stage = 2;
        r->stage = 2;
    }

    if (g_consumer_mode) {
        uintptr_t cons = *(uintptr_t *)(g_base + 0x544CC40ULL);
        if (cons) {
            r->cons_base_before = *(uintptr_t *)cons;
            r->cons_cap_before = *(uint32_t *)(cons + 8);
            r->cons_used_before = *(uint32_t *)(cons + 0xc);
            g_stage = 3;
            r->stage = 3;
            if (g_split_consumer) {
                /* 0x46B80E8 = 0x49CBC0C(drain) + 0x46B8070(parse).  Splitting
                 * the two real calls lets a parser crash still report the
                 * drain result; it does not substitute any behaviour. */
                ((void (*)(void *, void *))(g_base + 0x49CBC0CULL))((void *)cons, (void *)obj);
                r->cons_base_after = *(uintptr_t *)cons;
                r->cons_cap_after = *(uint32_t *)(cons + 8);
                r->cons_used_after = *(uint32_t *)(cons + 0xc);
                snap_slot0(obj, &r->after_consumer);
                r->drained = r->after_consumer.read - r->before.read;
                g_stage = 4;
                r->stage = 4;
                uint8_t *buf = (uint8_t *)(uintptr_t)*(void **)cons;
                r->bytes_match = (buf && r->cons_used_after >= m->len && m->len &&
                                  memcmp(buf, payload, m->len) == 0);
                uint8_t *end = buf + r->cons_used_after;
                ((void (*)(void *, void *))(g_base + 0x46B8070ULL))(buf, end);
                r->consumer_returned = 1;
                g_stage = 5;
                r->stage = 5;
            } else {
                ((void (*)(void))(g_base + 0x46B80E8ULL))();
                r->consumer_returned = 1;
                r->cons_base_after = *(uintptr_t *)cons;
                r->cons_cap_after = *(uint32_t *)(cons + 8);
                r->cons_used_after = *(uint32_t *)(cons + 0xc);
                snap_slot0(obj, &r->after_consumer);
                r->drained = r->after_consumer.read - r->before.read;
                uint8_t *buf = (uint8_t *)(uintptr_t)*(void **)cons;
                r->bytes_match = (buf && r->cons_used_after >= m->len && m->len &&
                                  memcmp(buf, payload, m->len) == 0);
                g_stage = 4;
                r->stage = 4;
            }
        }
    }

    if (g_tick) {
        g_stage = 6;
        r->stage = 6;
        ((void (*)(float))(g_base + 0x46B7888ULL))(g_tick_delta);
        r->tick_returned = 1;
        g_stage = 7;
        r->stage = 7;
    }

    if (ctx_copy) {
        const uint8_t *cur = (const uint8_t *)ctx_start;
        const uint64_t *oldq = (const uint64_t *)ctx_copy;
        const uint64_t *curq = (const uint64_t *)cur;
        size_t nq = ctx_size / 8;
        r->ctx_hash_after = fnv1a64(cur, ctx_size);
        for (size_t i = 0; i < nq; i++) {
            if (oldq[i] == curq[i]) continue;
            uint64_t addr = (uint64_t)(ctx_start + i * 8);
            for (int j = 0; j < 8; j++) {
                if (((const uint8_t *)&oldq[i])[j] != ((const uint8_t *)&curq[i])[j]) {
                    if (!r->ctx_first_diff) r->ctx_first_diff = addr + (uint64_t)j;
                    r->ctx_diff_bytes++;
                }
            }
            if (r->diff_n < 32) {
                uint32_t k = r->diff_n++;
                r->diff_addr[k] = addr;
                r->diff_old[k] = oldq[i];
                r->diff_new[k] = curq[i];
            }
        }
        free(ctx_copy);
    }
}

static void emit_config(FILE *out, const char *mode, const char *slot0_source,
                        int frames_total, int selected, int req_start,
                        int req_limit, int req_stride, int cmd_entries,
                        int slots_installed, int slots_zero, int slots_conflict,
                        int buffer_replaced, uint32_t ring_size,
                        uintptr_t consumer) {
    fprintf(out,
            "{\"event\":\"config\",\"schema\":\"kpl-h5-probe-v1\","
            "\"base\":\"0x%lx\",\"old_base\":\"0x%lx\",\"context\":\"0x%lx\","
            "\"consumer\":\"0x%lx\",\"slot0\":\"0x%lx\",\"slot0_source\":\"%s\","
            "\"ring\":%u,\"mode\":\"%s\",\"push\":%d,\"call_consumer\":%d,"
            "\"consumer_split\":%d,"
            "\"cmd_count\":%u,\"cmd_table\":\"0x%lx\",\"cmd_entries\":%d,"
            "\"slots_installed\":%d,\"slots_zero\":%d,\"slots_conflict\":%d,"
            "\"consumer_buffer_replaced\":%d,\"frames_total\":%d,"
            "\"frames_selected\":%d,\"start\":%d,\"limit\":%d,\"stride\":%d}\n",
            (unsigned long)g_base, (unsigned long)g_old_base,
            (unsigned long)g_context, (unsigned long)consumer,
            (unsigned long)g_slot0, slot0_source, ring_size, mode,
            g_push_mode, g_consumer_mode, g_split_consumer, g_cmd_count,
            (unsigned long)g_table_base,
            cmd_entries, slots_installed, slots_zero, slots_conflict,
            buffer_replaced, frames_total, selected, req_start, req_limit,
            req_stride);
    fflush(out);
}

static void emit_result(FILE *out, const struct result *r, int status_signal,
                        int status_exit, int got_msg, const struct crash *c) {
    const char *status = "ok";
    if (got_msg && c && c->signo == SIGALRM) status = "timeout";
    else if (got_msg || status_signal) status = "crash";
    else if (status_exit) status = "exit";
    int effective_signal = (got_msg && c) ? (int)c->signo : status_signal;
    fprintf(out,
            "{\"event\":\"frame\",\"frame\":%llu,\"seq\":%llu,\"bytes\":%u,"
            "\"preflight\":%u,\"opcode\":%u,\"arg\":%u,\"flag\":%u,"
            "\"in_range\":%u,\"handler\":\"0x%llx\",\"pending\":%u,"
            "\"slot0_before\":{\"ring\":%u,\"pending\":%u,\"write\":%u,\"read\":%u,\"committed\":%u},"
            "\"slot0_commit\":{\"pending\":%u,\"write\":%u,\"read\":%u,\"committed\":%u},"
            "\"consumer\":{\"base_before\":\"0x%llx\",\"base_after\":\"0x%llx\","
            "\"cap_before\":%u,\"cap_after\":%u,\"used_before\":%u,\"used_after\":%u,"
            "\"returned\":%u,\"drained\":%u,\"bytes_match\":%u},"
            "\"stage\":%u,\"status\":\"%s\",\"signal\":%d,\"exit\":%d,"
            "\"tick\":%u,"
            "\"crash_pc\":\"0x%llx\",\"crash_fault\":\"0x%llx\","
            "\"crash_stage\":%u,\"crash_opcode\":%u,"
            "\"crash_lr\":\"0x%llx\",\"crash_x1\":\"0x%llx\","
            "\"crash_x2\":\"0x%llx\",\"crash_x3\":\"0x%llx\","
            "\"trace\":{\"total\":%u,\"op0d\":%u,\"op83\":%u,\"op84\":%u,"
            "\"op32\":%u,\"op39\":%u,\"op3a\":%u,\"op3b\":%u,"
            "\"op34\":%u,\"op48\":%u,\"op4d\":%u,\"op73\":%u,"
            "\"other\":%u,\"last_op\":%u,\"last_arg\":%u},"
            "\"ctx_diff\":{\"start\":\"0x%llx\",\"size\":%llu,"
            "\"before\":\"0x%llx\",\"after\":\"0x%llx\","
            "\"bytes\":%u,\"first\":\"0x%llx\"},\"diffs\":[",
            (unsigned long long)r->frame_index, (unsigned long long)r->seq,
            r->len, r->preflight, r->opcode, r->arg, r->flag, r->in_range,
            r->handler ? (unsigned long long)(r->handler - g_base) : 0ULL,
            r->pending,
            r->before.ring_size, r->before.pending, r->before.write,
            r->before.read, r->before.committed,
            r->after_commit.pending, r->after_commit.write, r->after_commit.read,
            r->after_commit.committed,
            (unsigned long long)r->cons_base_before,
            (unsigned long long)r->cons_base_after,
            r->cons_cap_before, r->cons_cap_after, r->cons_used_before,
            r->cons_used_after, r->consumer_returned, r->drained, r->bytes_match,
            r->stage, status,
            effective_signal, status_exit,
            r->tick_returned,
            c && got_msg && c->pc ? (unsigned long long)(c->pc - g_base) : 0ULL,
            c && got_msg ? (unsigned long long)c->fault : 0ULL,
            c && got_msg ? c->stage : 0,
            c && got_msg ? c->opcode : 0,
            c && got_msg ? (unsigned long long)c->lr : 0ULL,
            c && got_msg ? (unsigned long long)c->x1 : 0ULL,
            c && got_msg ? (unsigned long long)c->x2 : 0ULL,
            c && got_msg ? (unsigned long long)c->x3 : 0ULL,
            r->trace_total, r->trace_0d, r->trace_83, r->trace_84,
            r->trace_32, r->trace_39, r->trace_3a, r->trace_3b,
            r->trace_34, r->trace_48, r->trace_4d, r->trace_73,
            r->trace_other, r->trace_last_op, r->trace_last_arg,
            (unsigned long long)r->ctx_start, (unsigned long long)r->ctx_size,
            (unsigned long long)r->ctx_hash_before,
            (unsigned long long)r->ctx_hash_after,
            r->ctx_diff_bytes, (unsigned long long)r->ctx_first_diff);
    for (uint32_t i = 0; i < r->diff_n; i++) {
        fprintf(out, "%s{\"a\":\"0x%llx\",\"old\":\"0x%llx\",\"new\":\"0x%llx\"}",
                i ? "," : "",
                (unsigned long long)r->diff_addr[i],
                (unsigned long long)r->diff_old[i],
                (unsigned long long)r->diff_new[i]);
    }
    fprintf(out, "]}\n");
    fflush(out);
}

static void emit_skipped(FILE *out, const struct frame_meta *m, const char *why) {
    fprintf(out, "{\"event\":\"skip\",\"frame\":%llu,\"seq\":%llu,\"bytes\":%u,\"why\":\"%s\"}\n",
            (unsigned long long)m->index, (unsigned long long)m->seq, m->len, why);
    fflush(out);
}

static int run_sequential(FILE *out, struct frame_meta *meta, const uint8_t *blob,
                          int start, int limit, int stride, int skip_empty) {
    int done = 0;
    for (int i = start; i < MAX_FRAMES && meta[i].len != 0xffffffffu; i++) {
        if (stride > 1 && ((i - start) % stride) != 0) continue;
        if (skip_empty && meta[i].len <= 1) { emit_skipped(out, &meta[i], "empty"); continue; }
        struct result r;
        execute_frame(&meta[i], blob + meta[i].offset, &r);
        emit_result(out, &r, 0, 0, 0, NULL);
        if (++done >= limit) break;
    }
    return done;
}

static int run_isolated(FILE *out, struct frame_meta *meta, const uint8_t *blob,
                        int start, int limit, int stride, int skip_empty,
                        int timeout_sec) {
    int done = 0;
    for (int i = start; i < MAX_FRAMES && meta[i].len != 0xffffffffu; i++) {
        if (stride > 1 && ((i - start) % stride) != 0) continue;
        if (skip_empty && meta[i].len <= 1) { emit_skipped(out, &meta[i], "empty"); continue; }

        int fd[2];
        if (pipe(fd) != 0) { say("pipe: %s", strerror(errno)); return -1; }
        struct result *shared = mmap(NULL, sizeof *shared, PROT_READ | PROT_WRITE,
                                     MAP_SHARED | MAP_ANONYMOUS, -1, 0);
        if (shared == MAP_FAILED) {
            say("mmap shared result: %s", strerror(errno));
            close(fd[0]); close(fd[1]); return -1;
        }
        memset(shared, 0, sizeof *shared);
        pid_t pid = fork();
        if (pid < 0) {
            say("fork: %s", strerror(errno));
            close(fd[0]); close(fd[1]); munmap(shared, sizeof *shared);
            return -1;
        }
        if (pid == 0) {
            close(fd[0]);
            g_child_fd = fd[1];
            install_crash_handlers(1);
            if (timeout_sec > 0) alarm((unsigned)timeout_sec);
            execute_frame(&meta[i], blob + meta[i].offset, shared);
            _exit(0);
        }
        close(fd[1]);
        struct crash c;
        memset(&c, 0, sizeof c);
        int got_crash = 0;
        int n = read_all(fd[0], &c, sizeof c);
        close(fd[0]);
        int status = 0;
        (void)waitpid(pid, &status, 0);
        int sig = WIFSIGNALED(status) ? WTERMSIG(status) : 0;
        int ex = WIFEXITED(status) ? WEXITSTATUS(status) : 0;
        if (n >= 4 && c.magic == CRASH_MAGIC) got_crash = 1;
        struct result r = *shared;
        munmap(shared, sizeof *shared);
        if (r.magic != RESULT_MAGIC) {
            memset(&r, 0, sizeof r);
            r.magic = RESULT_MAGIC;
            r.frame_index = meta[i].index;
            r.seq = meta[i].seq;
            r.len = meta[i].len;
            preflight(blob + meta[i].offset, meta[i].len, &r);
        }
        emit_result(out, &r, sig, ex, got_crash, &c);
        if (++done >= limit) break;
    }
    return done;
}


static int load_lib_globals(const char *dir) {
    char path[1200];
    snprintf(path, sizeof path, "%s/manifest.tsv", dir);
    FILE *f = fopen(path, "r");
    if (!f) { say("open globals manifest %s: %s", path, strerror(errno)); return -1; }
    char line[2048];
    int copied = 0;
    uint64_t rebased = 0;
    while (fgets(line, sizeof line, f)) {
        if (line[0] == 'r' || line[0] == '#') continue;
        char rs[64], re[64], perms[32], rpath[1024], file[1024], sha[160];
        unsigned long size = 0;
        if (sscanf(line, "%63s\t%63s\t%lu\t%31s\t%1023s\t%1023s\t%159s",
                   rs, re, &size, perms, rpath, file, sha) != 7) continue;
        uintptr_t rel = (uintptr_t)strtoull(rs, NULL, 0);
        uintptr_t dst = g_base + rel;
        if (!writable_range(dst, size)) {
            if (mprotect((void *)dst, size, PROT_READ | PROT_WRITE) == 0) {
                say("globals mprotected %#lx+%lu", (unsigned long)dst, size);
            } else {
                void *p = mmap((void *)dst, size, PROT_READ | PROT_WRITE,
                               MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0);
                if (p == MAP_FAILED || p != (void *)dst) {
                    say("globals target %#lx+%lu not mappable: %s", (unsigned long)dst,
                        size, strerror(errno));
                    fclose(f); return -1;
                }
                say("globals mapped gap %#lx+%lu", (unsigned long)dst, size);
            }
        }
        char fp[1200];
        snprintf(fp, sizeof fp, "%s/%s", dir, file);
        int fd = open(fp, O_RDONLY);
        if (fd < 0) { say("open globals %s: %s", fp, strerror(errno)); fclose(f); return -1; }
        uint8_t *buf = malloc(size);
        if (!buf || read_all(fd, buf, (int)size) != (int)size) {
            if (buf) free(buf); close(fd); say("read globals %s failed", fp); fclose(f); return -1;
        }
        close(fd);
        uint64_t *q = (uint64_t *)buf;
        size_t n = size / 8;
        /* Aligned module pointers first; remember which qwords moved. */
        uint8_t *hit = calloc(n ? n : 1, 1);
        for (size_t i = 0; i < n; i++) {
            uint64_t v = q[i];
            if (v >= g_old_base && v < g_old_end) {
                q[i] = v + (g_base - g_old_base);
                if (hit) hit[i] = 1;
                rebased++;
            }
        }
        /* Packed 4-byte-aligned pointers (CS structs) need a second pass.
         * Skip any slot overlapping an aligned rewrite. */
        if (hit) {
            for (size_t i = 0; i + 1 < n; i++) {
                if (hit[i] || hit[i + 1]) continue;
                uint64_t v;
                memcpy(&v, buf + 4 + i * 8, 8);
                if (v >= g_old_base && v < g_old_end) {
                    v += g_base - g_old_base;
                    memcpy(buf + 4 + i * 8, &v, 8);
                    rebased++;
                }
            }
            free(hit);
        }
        memcpy((void *)(g_base + rel), buf, size);
        free(buf);
        copied++;
        say("globals copied rel=%#lx size=%lu %s", (unsigned long)rel, size, rpath);
    }
    fclose(f);
    say("lib globals: copied=%d rebased=%llu", copied, (unsigned long long)rebased);
    return copied ? 0 : -1;
}

static int dump_context_region(const char *path) {
    uintptr_t start = 0, end = 0;
    for (int i = 0; i < g_nregions; i++) {
        if (g_regions[i].start <= g_context && g_context < g_regions[i].end) {
            start = g_regions[i].start;
            end = g_regions[i].end;
            break;
        }
    }
    if (!start) { say("dump-context: context region not found"); return -1; }
    FILE *f = fopen(path, "wb");
    if (!f) { say("dump-context %s: %s", path, strerror(errno)); return -1; }
    size_t n = end - start;
    size_t off = 0;
    while (off < n) {
        size_t w = fwrite((void *)(start + off), 1, n - off, f);
        if (!w) { fclose(f); say("dump-context write failed"); return -1; }
        off += w;
    }
    fclose(f);
    say("dump-context %s %#lx-%#lx %zu B", path, (unsigned long)start,
        (unsigned long)end, n);
    return 0;
}

int main(int argc, char **argv) {
    const char *lib_dir = "/data/local/tmp/gc_transplant";
    const char *snapshot = "/data/local/tmp/gc_transplant/snapshot";
    const char *frames = "/data/local/tmp/gc_transplant/frames";
    const char *cmd_table = NULL;
    const char *globals = NULL;
    const char *jsonl = "-";
    const char *dump_context = NULL;
    const char *mode = "isolated";
    uintptr_t consumer = 0x75DC98DAAC10ULL;
    uintptr_t core_state = 0x400000000002ULL;
    uint32_t ring_size = 0x10000;
    int start = 0, limit = 0, stride = 1, skip_empty = 0, timeout_sec = 5;

    for (int i = 1; i < argc; i++) {
        const char *a = argv[i];
        if (!strcmp(a, "--lib-dir") && i + 1 < argc) lib_dir = argv[++i];
        else if (!strcmp(a, "--snapshot") && i + 1 < argc) snapshot = argv[++i];
        else if (!strcmp(a, "--frames") && i + 1 < argc) frames = argv[++i];
        else if (!strcmp(a, "--cmd-table") && i + 1 < argc) cmd_table = argv[++i];
        else if (!strcmp(a, "--globals") && i + 1 < argc) globals = argv[++i];
        else if (!strcmp(a, "--dump-context") && i + 1 < argc) dump_context = argv[++i];
        else if (!strcmp(a, "--jsonl") && i + 1 < argc) jsonl = argv[++i];
        else if (!strcmp(a, "--mode") && i + 1 < argc) mode = argv[++i];
        else if (!strcmp(a, "--ring-size") && i + 1 < argc) ring_size = (uint32_t)parse_u64(argv[++i]);
        else if (!strcmp(a, "--old-base") && i + 1 < argc) g_old_base = (uintptr_t)parse_u64(argv[++i]);
        else if (!strcmp(a, "--context") && i + 1 < argc) g_context = (uintptr_t)parse_u64(argv[++i]);
        else if (!strcmp(a, "--binder") && i + 1 < argc) g_binder = (uintptr_t)parse_u64(argv[++i]);
        else if (!strcmp(a, "--no-publish-context")) g_no_publish_context = 1;
        else if (!strcmp(a, "--consumer") && i + 1 < argc) consumer = (uintptr_t)parse_u64(argv[++i]);
        else if (!strcmp(a, "--core-state") && i + 1 < argc) core_state = (uintptr_t)parse_u64(argv[++i]);
        else if (!strcmp(a, "--start") && i + 1 < argc) start = atoi(argv[++i]);
        else if (!strcmp(a, "--limit") && i + 1 < argc) limit = atoi(argv[++i]);
        else if (!strcmp(a, "--stride") && i + 1 < argc) stride = atoi(argv[++i]);
        else if (!strcmp(a, "--timeout") && i + 1 < argc) timeout_sec = atoi(argv[++i]);
        else if (!strcmp(a, "--skip-empty")) skip_empty = 1;
        else if (!strcmp(a, "--reuse-slot0")) g_reuse_slot0 = 1;
        else if (!strcmp(a, "--stock-init")) g_stock_init = 1;
        else if (!strcmp(a, "--monolithic-consumer")) g_split_consumer = 0;
        else if (!strcmp(a, "--trace-dispatch")) g_trace_dispatch = 1;
        else if (!strcmp(a, "--trace-print")) g_trace_print = 1;
        else if (!strcmp(a, "--diff-context")) g_diff_context = 1;
        else if (!strcmp(a, "--init-slot1")) g_init_slot1 = 1;
        else if (!strcmp(a, "--tick")) g_tick = 1;
        else if (!strcmp(a, "--tick-delta") && i + 1 < argc) g_tick_delta = strtof(argv[++i], NULL);
        else if (!strcmp(a, "--no-push")) g_push_mode = 0;
        else if (!strcmp(a, "--no-consumer")) g_consumer_mode = 0;
        else if (!strcmp(a, "--quiet")) g_verbose = 0;
        else if (!strcmp(a, "--help")) {
            printf("usage: %s [--lib-dir DIR] [--snapshot DIR] [--frames DIR] "
                   "[--cmd-table FILE] [--globals DIR] [--jsonl FILE|-] [--mode isolated|sequential] "
                   "[--old-base HEX] [--context HEX] [--binder HEX] [--consumer HEX] [--core-state HEX] "
                   "[--ring-size HEX] [--start N] [--limit N] [--stride N] "
                   "[--skip-empty] [--reuse-slot0] [--stock-init] [--init-slot1] "
                   "[--trace-dispatch] [--trace-print] [--diff-context] "
                   "[--monolithic-consumer] [--no-push] [--no-consumer] "
                   "[--timeout SEC] [--quiet]\n", argv[0]);
            return 0;
        } else {
            say("unknown argument: %s", a);
            return 2;
        }
    }

    if (!g_old_base) g_old_base = 0x400036A00000ULL;
    if (!g_context) g_context = 0x75D7EA4E99F0ULL;
    if (!ring_size || (ring_size & (ring_size - 1))) {
        say("ring size must be a power of two: %u", ring_size);
        return 2;
    }
    if (strcmp(mode, "isolated") && strcmp(mode, "sequential")) {
        say("mode must be isolated or sequential");
        return 2;
    }

    setvbuf(stdout, NULL, _IONBF, 0);
    install_crash_handlers(0);

    const char *pre[] = {"libpandora.so", "libpixuiCurl.so", "libPixUI_Unity.so", "libpuerts.so"};
    for (int i = 0; i < 4; i++)
        if (!openlib(lib_dir, pre[i])) return 11 + i;
    void *gc = openlib(lib_dir, "libGameCore.so");
    if (!gc) return 20;
    void *mi = dlsym(gc, "ModuleInit");
    if (!mi) { say("dlsym ModuleInit failed"); return 21; }
    g_base = (uintptr_t)mi - 0x46AD0E0ULL;
    int rc = ((int (*)(void))mi)();
    say("base=%#lx ModuleInit=%d pid=%d", (unsigned long)g_base, rc, getpid());

    int mapped = 0, failed = 0;
    if (map_snapshot(snapshot, &mapped, &failed) != 0) return 30;
    g_old_end = g_old_base + LIB_END;
    say("snapshot mapped=%d failed=%d", mapped, failed);
    if (failed) return 40;
    relocate_snapshot(g_old_base, g_old_end, g_base);
    if (globals && load_lib_globals(globals) != 0) return 31;
    /* Active-context fixture: [0x4FF57C8] is in the page immediately below
     * the captured data segment and is not part of the globals file.  It must
     * point at the rebased slot array at 0x52488C0 (slot0/1/... addresses). */
    if (g_init_slot1) {
        uintptr_t slot_ptr = g_base + 0x4FF57C8ULL;
        if (mprotect((void *)(slot_ptr & ~0xFFFULL), 0x1000,
                     PROT_READ | PROT_WRITE) == 0) {
            *(uintptr_t *)slot_ptr = g_base + 0x52488C0ULL;
            say("patched [0x4ff57c8]=%#lx", (unsigned long)*(uintptr_t *)slot_ptr);
            say("slot array [0x52488c0]=%#lx [0x52488c8]=%#lx",
                (unsigned long)*(uintptr_t *)(g_base + 0x52488C0ULL),
                (unsigned long)*(uintptr_t *)(g_base + 0x52488C8ULL));
        } else {
            say("E: mprotect [0x4ff57c8]: %s", strerror(errno));
        }
    }

    /* Publish the captured context exactly as A1 did. */
    uintptr_t holder_slot = *(uintptr_t *)(g_base + 0x51EA4D0ULL);
    if (holder_slot && g_context && !g_no_publish_context) {
        *(uintptr_t *)holder_slot = g_context;
        say("published context at [%#lx]=%#lx", (unsigned long)holder_slot,
            (unsigned long)g_context);
    }
    if (g_context) {
        /* The 0x4FF4520 chain ends at the wrapper; CS slots live in binder P. */
        uintptr_t binder = g_binder ? g_binder : g_context;
        uintptr_t slot0 = *(uintptr_t *)(binder + 0x80);
        uintptr_t slot1 = *(uintptr_t *)(binder + 0x88);
        *(uintptr_t *)(g_base + 0x52C3250ULL) = slot0;
        *(uintptr_t *)(g_base + 0x52C3258ULL) = slot1;
        *(uintptr_t *)(g_base + 0x52C3270ULL) = binder + 0x4F0;
        *(uintptr_t *)(g_base + 0x52C3278ULL) = binder + 0x578;
        say("binder slots: slot0=%#lx slot1=%#lx", (unsigned long)slot0,
            (unsigned long)slot1);
    }
    if (core_state) {
        *(uintptr_t *)(g_base + 0x544CBD0ULL) = core_state;
        say("core state [0x544CBD0]=%#lx", (unsigned long)core_state);
    }
    if (consumer) {
        *(uintptr_t *)(g_base + 0x544CC40ULL) = consumer;
        say("consumer [0x544CC40]=%#lx", (unsigned long)consumer);
    }

    const char *slot0_source = "captured";
    if (g_reuse_slot0) {
        g_slot0 = *(uintptr_t *)(g_base + 0x52C3250ULL);
        if (!g_slot0) { say("reuse-slot0 requested but slot0 is null"); return 41; }
        struct slot_snap s; snap_slot0(g_slot0, &s);
        say("slot0 reuse obj=%#lx ring=%#x pending=%u write=%u read=%u committed=%u",
            (unsigned long)g_slot0, s.ring_size, s.pending, s.write, s.read, s.committed);
        /* A captured slot may carry old cursors; reset it unless the caller
         * explicitly asked for the exact captured state. */
        ((void (*)(void))(g_base + 0x460A40CULL))();
    } else {
        install_slot0(ring_size);
        slot0_source = "fresh";
    }
    if (g_init_slot1) install_slot1(ring_size);

    int buffer_replaced = 0;
    if (g_consumer_mode && consumer) {
        uintptr_t cons = *(uintptr_t *)(g_base + 0x544CC40ULL);
        if (!in_regions(cons)) {
            say("consumer object %#lx is not in the snapshot", (unsigned long)cons);
            return 42;
        }
        uintptr_t cbase = *(uintptr_t *)cons;
        uint32_t ccap = *(uint32_t *)(cons + 8);
        uint32_t cused = *(uint32_t *)(cons + 0xc);
        say("consumer obj=%#lx base=%#lx cap=%#x used=%#x",
            (unsigned long)cons, (unsigned long)cbase, ccap, cused);
        if (!cbase || !in_regions(cbase) || ccap < 0x1000 || ccap > 16 * 1024 * 1024) {
            if (ccap < 0x1000 || ccap > 16 * 1024 * 1024) ccap = 0x40000;
            void *buf = calloc(1, ccap);
            if (!buf) { say("consumer buffer alloc failed"); return 43; }
            *(uintptr_t *)cons = (uintptr_t)buf;
            *(uint32_t *)(cons + 8) = ccap;
            *(uint32_t *)(cons + 0xc) = 0;
            buffer_replaced = 1;
            say("consumer buffer replaced: old=%#lx cap=%#x -> host=%p",
                (unsigned long)cbase, ccap, buf);
        } else {
            *(uint32_t *)(cons + 0xc) = 0;
            say("consumer buffer mapped; reset used=0 (stale=%u)", cused);
        }
    }

    int cmd_entries = 0, slots_installed = 0, slots_zero = 0, slots_conflict = 0;
    if (cmd_table) {
        if (load_cmd_table(cmd_table, &cmd_entries, &slots_installed,
                           &slots_zero, &slots_conflict) != 0)
            return 44;
    } else {
        g_cmd_count = *(uint32_t *)(g_base + 0x5272368ULL);
        g_table_base = *(uintptr_t *)(g_base + 0x544D340ULL);
        say("no --cmd-table: cmd_count=%u table=%#lx", g_cmd_count,
            (unsigned long)g_table_base);
    }
    if (g_trace_dispatch) install_trace_wrappers();

    struct frame_meta *meta = NULL;
    uint8_t *blob = NULL;
    size_t blob_size = 0;
    int frames_total = 0;
    if (load_frames(frames, &meta, &blob, &blob_size, &frames_total) != 0) return 50;
    say("frames=%d blob=%zu", frames_total, blob_size);

    /* Mark the array end for the loop condition. */
    if (frames_total < MAX_FRAMES) meta[frames_total].len = 0xffffffffu;

    int selected = 0;
    for (int i = start; i < frames_total; i++) {
        if (stride > 1 && ((i - start) % stride) != 0) continue;
        if (skip_empty && meta[i].len <= 1) continue;
        if (limit && selected >= limit) break;
        selected++;
    }

    FILE *out = stdout;
    if (strcmp(jsonl, "-") != 0) {
        out = fopen(jsonl, "w");
        if (!out) { say("open %s: %s", jsonl, strerror(errno)); return 51; }
    }
    emit_config(out, mode, slot0_source, frames_total, selected, start,
                limit, stride, cmd_entries, slots_installed, slots_zero,
                slots_conflict, buffer_replaced, ring_size, consumer);
    int done;
    if (!strcmp(mode, "sequential")) {
        done = run_sequential(out, meta, blob, start, limit ? limit : MAX_FRAMES,
                              stride, skip_empty);
    } else {
        done = run_isolated(out, meta, blob, start, limit ? limit : MAX_FRAMES,
                            stride, skip_empty, timeout_sec);
    }
    if (dump_context) {
        if (!strcmp(mode, "sequential"))
            (void)dump_context_region(dump_context);
        else
            say("dump-context ignored in isolated mode");
    }
    say("done frames=%d", done);
    if (out != stdout) fclose(out);
    free(blob);
    free(meta);
    return done < 0 ? 60 : 0;
}
