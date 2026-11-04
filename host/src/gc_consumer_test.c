/* gc_consumer_test.c — H5 E1: prove the real CS consumer parser dispatches.
 *
 * Host-only; no game process. Real ring ctor/init, host consumer buffer, one
 * synthetic 4-byte record {len=0,id=0}, one host handler entry, call 0x46B80E8.
 */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdarg.h>
#include <string.h>
#include <unistd.h>
#include <dlfcn.h>
#include <signal.h>
#include <ucontext.h>

static const char *DIR = "/data/local/tmp/gc_consumer";
static uintptr_t base;
static int handler_calls;
static void on_segv(int sig, siginfo_t *si, void *ctx) {
    ucontext_t *uc = (ucontext_t *)ctx;
    fprintf(stderr, "SIG %d addr=%p pc=%#lx lr=%#lx x0=%#lx x1=%#lx\n",
            sig, si ? si->si_addr : NULL,
            (unsigned long)(uc ? uc->uc_mcontext.pc : 0),
            (unsigned long)(uc ? uc->uc_mcontext.regs[30] : 0),
            (unsigned long)(uc ? uc->uc_mcontext.regs[0] : 0),
            (unsigned long)(uc ? uc->uc_mcontext.regs[1] : 0));
    _exit(90 + sig);
}

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
static void handler(void *self, int op, int arg) {
    (void)self; (void)arg;
    handler_calls++;
    say("handler called op=%d arg=%d total=%d", op, arg, handler_calls);
}

int main(void) {
    struct sigaction sa; memset(&sa, 0, sizeof sa);
    sa.sa_sigaction = on_segv; sa.sa_flags = SA_SIGINFO;
    sigaction(SIGSEGV, &sa, NULL); sigaction(SIGBUS, &sa, NULL); sigaction(SIGABRT, &sa, NULL);
    say("=== gc_consumer_test pid=%d ===", getpid());
    const char *pre[] = {"libpandora.so", "libpixuiCurl.so",
                         "libPixUI_Unity.so", "libpuerts.so"};
    for (unsigned i = 0; i < 4; i++) if (!openlib(pre[i])) return 11 + (int)i;
    void *gc = openlib("libGameCore.so");
    if (!gc) return 20;
    void *mi = dlsym(gc, "ModuleInit");
    if (!mi) return 21;
    base = (uintptr_t)mi - 0x46AD0E0ULL;
    int rc = ((int (*)(void))mi)();
    say("base=%#lx ModuleInit=%d", (unsigned long)base, rc);

    /* Real CS ring at slot0. */
    void *ring = calloc(1, 0x90);
    if (!ring) return 30;
    say("ring ctor...");
    ((void (*)(void *))(base + 0x49CBD88ULL))(ring);
    say("ring init...");
    ((void (*)(void *, uint32_t, uint32_t, void *, void *))
        (base + 0x49CBEECULL))(ring, 0x1000, 0, 0, 0);
    say("ring init done");
    *(void **)(base + 0x52C3250ULL) = ring;
    say("ring=%p vtable=%#lx cap=%u pending=%u",
        ring, (unsigned long)*(uintptr_t *)ring,
        *(uint32_t *)((char *)ring + 0x20), *(uint32_t *)((char *)ring + 0x24));

    /* Consumer buffer: {data, cap, used}; 16 bytes. */
    unsigned char *buf = calloc(1, 0x1000);
    void *consumer = calloc(1, 0x10);
    if (!buf || !consumer) return 31;
    *(void **)((char *)consumer + 0x0) = buf;
    *(uint32_t *)((char *)consumer + 0x8) = 0x1000;
    *(uint32_t *)((char *)consumer + 0xc) = 0;
    *(void **)(base + 0x544CC40ULL) = consumer;

    /* One 16-byte handler entry; count=1. */
    void *table = calloc(1, 0x10);
    if (!table) return 32;
    *(void **)((char *)table + 0x0) = (void *)handler;
    *(void **)(base + 0x544D340ULL) = table;
    *(uint32_t *)(base + 0x5272368ULL) = 1;
    say("consumer=%p buf=%p table=%p handler=%p count=%u",
        consumer, buf, table, (void *)handler,
        *(uint32_t *)(base + 0x5272368ULL));

    void *(*push)(int) = dlsym(gc, "PushCsBuffer");
    int (*commit)(void) = dlsym(gc, "CommitCsBuffer");
    if (!push || !commit) return 33;
    void *staging = push(4);
    if (!staging) { say("E: PushCsBuffer null"); return 34; }
    memset(staging, 0, 4);  /* header = (len=0 << 16) | id=0 */
    commit();
    say("pushed 4 bytes header=00000000 slot0 pending=%u cursors=%u/%u/%u",
        *(uint32_t *)((char *)ring + 0x24),
        *(uint32_t *)((char *)ring + 0x2c),
        *(uint32_t *)((char *)ring + 0x30),
        *(uint32_t *)((char *)ring + 0x34));

    ((void (*)(void))(base + 0x46B80E8ULL))();
    say("after consumer: handler_calls=%d used=%u data=%02x %02x %02x %02x "
        "pending=%u cursors=%u/%u/%u",
        handler_calls, *(uint32_t *)((char *)consumer + 0xc),
        buf[0], buf[1], buf[2], buf[3],
        *(uint32_t *)((char *)ring + 0x24),
        *(uint32_t *)((char *)ring + 0x2c),
        *(uint32_t *)((char *)ring + 0x30),
        *(uint32_t *)((char *)ring + 0x34));
    return handler_calls == 1 ? 0 : 40;
}
