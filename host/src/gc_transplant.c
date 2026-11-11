/* gc_transplant.c — A1 host loader: map a captured process snapshot at original
 * addresses, relocate libGameCore pointers, publish the captured context.
 *
 * Read-only w.r.t. game/device; this runs as a private host process.
 */
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <dlfcn.h>
#include <errno.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>

#ifndef MAP_FIXED_NOREPLACE
#define MAP_FIXED_NOREPLACE 0x100000
#endif

static const char *DIR = "/data/local/tmp/gc_transplant";
static uintptr_t g_old_base, g_new_base, g_old_end, g_context;
static uint64_t g_rebased;
static uint64_t g_other_lib_ptrs;

static void say(const char *fmt, ...) {
    va_list ap; va_start(ap, fmt); vprintf(fmt, ap); putchar('\n');
    fflush(stdout); va_end(ap);
}

static void *openlib(const char *name) {
    char p[512]; snprintf(p, sizeof p, "%s/%s", DIR, name);
    void *h = dlopen(p, RTLD_LAZY | RTLD_GLOBAL);
    if (!h) say("E: dlopen %s: %s", name, dlerror());
    return h;
}

static int read_region(const char *path, void *dst, size_t size) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) return -1;
    size_t off = 0;
    while (off < size) {
        ssize_t n = read(fd, (char *)dst + off, size - off);
        if (n <= 0) { close(fd); return -1; }
        off += (size_t)n;
    }
    close(fd);
    return 0;
}

int main(int argc, char **argv) {
    const char *manifest = argc > 1 ? argv[1] : "/data/local/tmp/gc_transplant/regions.tsv";
    const char *snapdir = argc > 2 ? argv[2] : "/data/local/tmp/gc_transplant/snapshot";
    g_old_base = argc > 3 ? strtoull(argv[3], NULL, 0) : 0x400036a00000ULL;
    g_old_end = g_old_base + 0x544D478ULL;
    g_context = argc > 4 ? strtoull(argv[4], NULL, 0) : 0x75d7e86e9ff0ULL;
    uintptr_t consumer = argc > 5 ? strtoull(argv[5], NULL, 0) : 0;
    uint64_t core_state = argc > 6 ? strtoull(argv[6], NULL, 0) : 0;

    say("=== gc_transplant pid=%d old_base=%#lx context=%#lx ===",
        getpid(), (unsigned long)g_old_base, (unsigned long)g_context);

    const char *pre[] = {"libpandora.so", "libpixuiCurl.so", "libPixUI_Unity.so",
                         "libpuerts.so"};
    for (unsigned i = 0; i < 4; i++) if (!openlib(pre[i])) return 11 + (int)i;
    void *gc = openlib("libGameCore.so");
    if (!gc) return 20;
    void *mi = dlsym(gc, "ModuleInit");
    if (!mi) return 21;
    g_new_base = (uintptr_t)mi - 0x46AD0E0ULL;
    say("new_base=%#lx delta=%+#lx", (unsigned long)g_new_base,
        (long)(g_new_base - g_old_base));
    int rc = ((int (*)(void))mi)();
    say("ModuleInit -> %d", rc);

    FILE *f = fopen(manifest, "r");
    if (!f) { say("E: manifest %s: %s", manifest, strerror(errno)); return 30; }
    char line[4096];
    int mapped = 0, failed = 0;
    while (fgets(line, sizeof line, f)) {
        if (line[0] == 's' || line[0] == '#') continue;
        char start_s[64], end_s[64], perms[16], path[1024], file[1024], size_s[64], sha[128];
        if (sscanf(line, "%63s\t%63s\t%15s\t%1023s\t%1023s\t%63s\t%127s",
                   start_s, end_s, perms, path, file, size_s, sha) != 7) continue;
        uintptr_t start = (uintptr_t)strtoull(start_s, NULL, 0);
        uintptr_t end = (uintptr_t)strtoull(end_s, NULL, 0);
        size_t size = end - start;
        void *want = (void *)start;
        void *p = mmap(want, size, PROT_READ | PROT_WRITE,
                       MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0);
        if (p == MAP_FAILED) {
            say("E: mmap %#lx-%#lx failed: %s", (unsigned long)start,
                (unsigned long)end, strerror(errno));
            failed++;
            continue;
        }
        char rp[1200];
        snprintf(rp, sizeof rp, "%s/%s", snapdir, file);
        if (read_region(rp, p, size) != 0) {
            say("E: read %s failed", rp);
            failed++;
            continue;
        }
        mapped++;
        say("mapped %#lx-%#lx %.1f MiB %s", (unsigned long)start,
            (unsigned long)end, size / 1048576.0, path);
    }
    fclose(f);
    say("mapped=%d failed=%d", mapped, failed);

    /* Relocate libGameCore pointers in every mapped region. */
    f = fopen(manifest, "r");
    if (!f) return 31;
    while (fgets(line, sizeof line, f)) {
        if (line[0] == 's' || line[0] == '#') continue;
        char start_s[64], end_s[64], perms[16], path[1024], file[1024], size_s[64], sha[128];
        if (sscanf(line, "%63s\t%63s\t%15s\t%1023s\t%1023s\t%63s\t%127s",
                   start_s, end_s, perms, path, file, size_s, sha) != 7) continue;
        uintptr_t start = (uintptr_t)strtoull(start_s, NULL, 0);
        uintptr_t end = (uintptr_t)strtoull(end_s, NULL, 0);
        uint64_t *q = (uint64_t *)start;
        size_t n = (end - start) / 8;
        for (size_t i = 0; i < n; i++) {
            uint64_t v = q[i];
            if (v >= g_old_base && v < g_old_end) {
                q[i] = v + (g_new_base - g_old_base);
                g_rebased++;
            } else if (v >= 0x400000000000ULL && v < 0x800000000000ULL &&
                       !(v >= g_context && v < g_context + 0x1E00000ULL)) {
                g_other_lib_ptrs++;
            }
        }
    }
    fclose(f);
    say("rebased libGameCore ptrs=%llu other_ptrs=%llu",
        (unsigned long long)g_rebased, (unsigned long long)g_other_lib_ptrs);

    uintptr_t holder_slot = *(uintptr_t *)(g_new_base + 0x51EA4D0ULL);
    say("holder_slot=%#lx", (unsigned long)holder_slot);
    if (holder_slot) {
        *(uintptr_t *)holder_slot = g_context;
        say("published context at [%#lx] = %#lx", (unsigned long)holder_slot,
            (unsigned long)*(uintptr_t *)holder_slot);
    } else {
        say("E: holder slot null");
        return 32;
    }
    /* Two distinct objects: the 0x4FF4520 chain ends at the wrapper context
     * (g_context), while the CS slots live in the binder context P.  The old
     * code published P into the chain and crashed at wrapper+0x3b8. */
    uintptr_t ctx = g_context;
    uintptr_t binder = argc > 7 ? (uintptr_t)strtoull(argv[7], NULL, 0) : 0;
    if (!binder) binder = ctx;
    uintptr_t slot0 = *(uintptr_t *)(binder + 0x80);
    uintptr_t slot1 = *(uintptr_t *)(binder + 0x88);
    say("wrapper context=%#lx binder P=%#lx", (unsigned long)ctx,
        (unsigned long)binder);
    say("binder+0x80 slot0=%#lx slot1=%#lx", (unsigned long)slot0,
        (unsigned long)slot1);

    /* Reproduce the four writes performed by binder 0x43d301c. */
    *(uintptr_t *)(g_new_base + 0x52C3250ULL) = slot0;
    *(uintptr_t *)(g_new_base + 0x52C3258ULL) = slot1;
    *(uintptr_t *)(g_new_base + 0x52C3270ULL) = binder + 0x4F0;
    *(uintptr_t *)(g_new_base + 0x52C3278ULL) = binder + 0x578;
    say("published CS slot0=%#lx slot1=%#lx slot4=%#lx slot5=%#lx",
        (unsigned long)*(uintptr_t *)(g_new_base + 0x52C3250ULL),
        (unsigned long)*(uintptr_t *)(g_new_base + 0x52C3258ULL),
        (unsigned long)*(uintptr_t *)(g_new_base + 0x52C3270ULL),
        (unsigned long)*(uintptr_t *)(g_new_base + 0x52C3278ULL));

    void *(*push)(int) = dlsym(gc, "PushCsBuffer");
    int (*commit)(void) = dlsym(gc, "CommitCsBuffer");
    int (*reset)(void) = dlsym(gc, "ResetCsBuffer");
    say("Push=%p Commit=%p Reset=%p", push, commit, reset);
    if (push) {
        void *p = push(0);
        say("PushCsBuffer(0) -> %p slot0+0x18=%#lx slot0+0x24=%#x",
            p, (unsigned long)*(uintptr_t *)(slot0 + 0x18),
            *(uint32_t *)(slot0 + 0x24));
        if (commit) {
            int c = commit();
            say("CommitCsBuffer(0) -> %d", c);
        }
    }
    if (reset) say("ResetCsBuffer -> %d", reset());
    if (consumer) *(uintptr_t *)(g_new_base + 0x544CC40ULL) = consumer;
    if (core_state) *(uintptr_t *)(g_new_base + 0x544CBD0ULL) = core_state;
    say("BSS state [0x544CBD0]=%#lx consumer [0x544CC40]=%#lx",
        (unsigned long)*(uintptr_t *)(g_new_base + 0x544CBD0ULL),
        (unsigned long)*(uintptr_t *)(g_new_base + 0x544CC40ULL));
    if (consumer) {
        say("consumer object +0=%#lx +8=%#lx +0x10=%#lx +0x18=%#lx",
            (unsigned long)*(uintptr_t *)consumer,
            (unsigned long)*(uintptr_t *)(consumer + 8),
            (unsigned long)*(uintptr_t *)(consumer + 0x10),
            (unsigned long)*(uintptr_t *)(consumer + 0x18));
        say("calling CS consumer 0x46B80E8");
        ((void (*)(void))(g_new_base + 0x46B80E8ULL))();
        say("CS consumer returned");
    }
    say("=== done ===");
    return failed ? 40 : 0;
}
