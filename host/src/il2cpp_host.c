/* il2cpp_host.c — Route A feasibility probe.
 *
 * Initializes the game's il2cpp runtime in a private ARM64 process
 * (no game process, no login, no injection), loads the metadata from a
 * directory, enumerates images, and resolves
 *   Assets.Scripts.GameLogic.GameLogicHelper.AdvanceFrameCommands
 * plus a few related types (HeroData/ActorData/DSVarBaseField) for inspection.
 *
 * Stage A1 only: init + resolve. It does not invoke managed methods yet.
 *
 * Build: NDK r28b, aarch64-linux-android28-clang -fPIE -pie -ldl
 * Run:   ./il2cpp_host /data/local/tmp/gc/sim
 *        (dir must contain global-metadata.dat and the .so dependencies)
 */
#define _GNU_SOURCE 1

#include <dlfcn.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ucontext.h>
#include <unistd.h>
#include <pthread.h>
#include <locale.h>
#include <sys/mman.h>
#include <errno.h>
#include <execinfo.h>
#include <semaphore.h>
#include <unwind.h>

typedef void *Il2CppDomain;
typedef void *Il2CppAssembly;
typedef void *Il2CppImage;
typedef void *Il2CppClass;
typedef void *Il2CppMethod;

/* Interpose setlocale: libil2cpp's init calls setlocale(LC_ALL=6, ...)
 * before its C++ locale globals are initialized, and the real call walks the
 * locale machinery (operator new) that is not ready yet.  The executable's
 * symbol wins over libc for every library in the global namespace. */
__attribute__((visibility("default")))
char *setlocale(int category, const char *locale) {
    (void)category; (void)locale;
    return (char *)"C";
}

extern int backtrace(void **, int) __attribute__((weak));
extern void backtrace_symbols_fd(void *const *, int, int) __attribute__((weak));

static int kpl_backtrace(void **bt, int n) {
    return backtrace ? backtrace(bt, n) : 0;
}
static void kpl_backtrace_symbols(void **bt, int n) {
    if (backtrace_symbols_fd) backtrace_symbols_fd(bt, n, 2);
}

struct bt_ctx { int n; };
static _Unwind_Reason_Code bt_cb(struct _Unwind_Context *c, void *arg) {
    struct bt_ctx *b = (struct bt_ctx *)arg;
    uintptr_t ip = _Unwind_GetIP(c);
    Dl_info di;
    memset(&di, 0, sizeof di);
    dladdr((void *)ip, &di);
    dprintf(2, "  uw[%d] pc=%#lx %s +%#lx%c", b->n, (unsigned long)ip,
            di.dli_fname ? di.dli_fname : "?",
            di.dli_fbase ? ip - (uintptr_t)di.dli_fbase : 0, 10);
    b->n++;
    return b->n < 24 ? _URC_NO_REASON : _URC_END_OF_STACK;
}

static void on_fault(int sig, siginfo_t *si, void *ctx) {
    ucontext_t *uc = (ucontext_t *)ctx;
    unsigned long pc = (unsigned long)uc->uc_mcontext.pc;
    unsigned long lr = (unsigned long)uc->uc_mcontext.regs[30];
    unsigned long sp = (unsigned long)uc->uc_mcontext.sp;
    Dl_info d1, d2;
    memset(&d1, 0, sizeof d1); memset(&d2, 0, sizeof d2);
    dladdr((void *)pc, &d1); dladdr((void *)lr, &d2);
    dprintf(2, "FAULT sig=%d pc=%#lx lr=%#lx sp=%#lx addr=%p\n",
            sig, pc, lr, sp, si ? si->si_addr : NULL);
    dprintf(2, "  x0=%#lx x1=%#lx x2=%#lx x3=%#lx x4=%#lx\n",
            (unsigned long)uc->uc_mcontext.regs[0],
            (unsigned long)uc->uc_mcontext.regs[1],
            (unsigned long)uc->uc_mcontext.regs[2],
            (unsigned long)uc->uc_mcontext.regs[3],
            (unsigned long)uc->uc_mcontext.regs[4]);
    dprintf(2, "  pc %s +%#lx | lr %s +%#lx\n",
            d1.dli_fname ? d1.dli_fname : "?",
            d1.dli_fbase ? pc-(unsigned long)d1.dli_fbase : 0,
            d2.dli_fname ? d2.dli_fname : "?",
            d2.dli_fbase ? lr-(unsigned long)d2.dli_fbase : 0);
    unsigned long fp = (unsigned long)uc->uc_mcontext.regs[29];
    for (int i = 0; i < 12 && fp >= sp && fp < sp + 0x200000; i++) {
        unsigned long next = *(unsigned long *)fp;
        unsigned long ret = *(unsigned long *)(fp + 8);
        Dl_info di;
        memset(&di, 0, sizeof di);
        dladdr((void *)ret, &di);
        dprintf(2, "  frame[%d] lr=%#lx %s +%#lx\n", i, ret,
                di.dli_fname ? di.dli_fname : "?",
                di.dli_fbase ? ret-(unsigned long)di.dli_fbase : 0);
        if (next <= fp) break;
        fp = next;
    }
    struct bt_ctx bctx = {0};
    _Unwind_Backtrace(bt_cb, &bctx);
    /* Let debuggerd produce a full tombstone with the platform unwinder. */
    sigset_t unblock;
    sigemptyset(&unblock);
    sigaddset(&unblock, sig);
    sigprocmask(SIG_UNBLOCK, &unblock, NULL);
    signal(sig, SIG_DFL);
    raise(sig);
    _exit(90);
}

static void *open_global(const char *dir, const char *name) {
    char path[1024];
    snprintf(path, sizeof path, "%s/%s", dir, name);
    void *h = dlopen(path, RTLD_LAZY | RTLD_GLOBAL);
    if (!h) {
        fprintf(stderr, "dlopen %s: %s\n", path, dlerror());
        return NULL;
    }
    printf("dlopen %-24s OK (%p)\n", name, h);
    return h;
}

static void patch_nop(void *fn, uintptr_t rel) {
    Dl_info di;
    memset(&di, 0, sizeof di);
    if (!dladdr(fn, &di) || !di.dli_fbase) {
        printf("patch_nop: no libil2cpp base\n");
        return;
    }
    uintptr_t at = (uintptr_t)di.dli_fbase + rel;
    uintptr_t page = at & ~0xFFFULL;
    if (mprotect((void *)page, 0x1000, PROT_READ | PROT_WRITE | PROT_EXEC) != 0) {
        printf("patch_nop: mprotect %#lx failed: %s\n", (unsigned long)page, strerror(errno));
        return;
    }
    *(uint32_t *)at = 0xD503201F;  /* nop */
    printf("patch_nop: [%#lx] = nop\n", (unsigned long)at);
}

/* Anti-cheat interposition: libtprt's init waits on a semaphore that only
 * the real game process signals.  Let it proceed instead of skipping the
 * whole protection setup. */
int sem_wait(sem_t *sem) { (void)sem; return 0; }
int sem_timedwait(sem_t *sem, const struct timespec *abs_timeout) {
    (void)sem; (void)abs_timeout; return 0;
}

static int (*g_il2cpp_init)(const char *);
static int g_init_rc = -1;
static pthread_mutex_t g_init_mu = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t g_init_cv = PTHREAD_COND_INITIALIZER;

static void *init_on_thread(void *arg) {
    (void)arg;
    int rc = g_il2cpp_init("gc");
    pthread_mutex_lock(&g_init_mu);
    g_init_rc = rc;
    pthread_cond_broadcast(&g_init_cv);
    pthread_mutex_unlock(&g_init_mu);
    for (;;) sleep(3600);  /* keep the init thread and its TLS alive */
    return NULL;
}

int main(int argc, char **argv) {
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_sigaction = on_fault;
    sa.sa_flags = SA_SIGINFO;
    sigaction(SIGSEGV, &sa, NULL);
    sigaction(SIGBUS, &sa, NULL);
    sigaction(SIGILL, &sa, NULL);
    setvbuf(stdout, NULL, _IONBF, 0);
    setvbuf(stderr, NULL, _IONBF, 0);

    const char *dir = argc > 1 ? argv[1] : "/data/local/tmp/gc/sim";
    printf("== il2cpp host A1 ==\ndir=%s\n", dir);

    const char *deps[] = {
        "libtprt.so", "libpandora.so", "libpixuiCurl.so",
        "libPixUI_Unity.so", "libpuerts.so", "libGameCore.so",
    };
    for (size_t i = 0; i < sizeof(deps) / sizeof(deps[0]); i++) {
        if (!open_global(dir, deps[i])) return 10;
    }

    void *il2 = open_global(dir, "libil2cpp.so");
    if (!il2) return 11;

    void (*set_data_dir)(const char *) = (void (*)(const char *))dlsym(il2, "il2cpp_set_data_dir");
    int (*init)(const char *) = (int (*)(const char *))dlsym(il2, "il2cpp_init");
    Il2CppDomain (*domain_get)(void) = (Il2CppDomain (*)(void))dlsym(il2, "il2cpp_domain_get");
    const Il2CppAssembly **(*domain_get_assemblies)(Il2CppDomain, size_t *) =
        (const Il2CppAssembly **(*)(Il2CppDomain, size_t *))dlsym(il2, "il2cpp_domain_get_assemblies");
    Il2CppImage *(*assembly_get_image)(const Il2CppAssembly *) =
        (Il2CppImage *(*)(const Il2CppAssembly *))dlsym(il2, "il2cpp_assembly_get_image");
    const char *(*image_get_name)(const Il2CppImage *) =
        (const char *(*)(const Il2CppImage *))dlsym(il2, "il2cpp_image_get_name");
    Il2CppClass *(*class_from_name)(const Il2CppImage *, const char *, const char *) =
        (Il2CppClass *(*)(const Il2CppImage *, const char *, const char *))dlsym(il2, "il2cpp_class_from_name");
    const Il2CppMethod *(*class_get_method_from_name)(Il2CppClass *, const char *, int) =
        (const Il2CppMethod *(*)(Il2CppClass *, const char *, int))dlsym(il2, "il2cpp_class_get_method_from_name");
    const char *(*class_get_name)(Il2CppClass *) = (const char *(*)(Il2CppClass *))dlsym(il2, "il2cpp_class_get_name");
    const char *(*class_get_namespace)(Il2CppClass *) =
        (const char *(*)(Il2CppClass *))dlsym(il2, "il2cpp_class_get_namespace");
    const char *(*method_get_name)(const Il2CppMethod *) =
        (const char *(*)(const Il2CppMethod *))dlsym(il2, "il2cpp_method_get_name");
    uint32_t (*method_get_param_count)(const Il2CppMethod *) =
        (uint32_t (*)(const Il2CppMethod *))dlsym(il2, "il2cpp_method_get_param_count");
    void (*thread_attach)(Il2CppDomain) = (void (*)(Il2CppDomain))dlsym(il2, "il2cpp_thread_attach");
    if (!set_data_dir || !init || !domain_get || !domain_get_assemblies ||
        !assembly_get_image || !image_get_name || !class_from_name ||
        !class_get_method_from_name) {
        fprintf(stderr, "missing il2cpp API symbols\n");
        return 12;
    }

    if (argc > 2 && strcmp(argv[2], "keys") == 0) {
        pthread_key_t keys[8];
        for (int i = 0; i < 8; i++) {
            int kr = pthread_key_create(&keys[i], NULL);
            printf("pthread_key_create[%d] rc=%d key=%u\n", i, kr,
                   (unsigned)keys[i]);
        }    }
    if (argc > 2) {
        printf("skip il2cpp_set_data_dir\n");
    } else {
        set_data_dir(dir);
        printf("il2cpp_set_data_dir(%s)\n", dir);
    }

    /* Always skip the anti-cheat call inside il2cpp_init; it blocks on a
     * libtprt semaphore that only the real game process signals. */
    patch_nop((void *)init, 0x3AA3BC8ULL);
    const char *loc = setlocale(LC_ALL, "C");
    printf("setlocale(LC_ALL,C) -> %s\n", loc ? loc : "(null)");
    int rc;
    if (argc > 2 && strcmp(argv[2], "thread") == 0) {
        g_il2cpp_init = init;
        pthread_t th;
        pthread_attr_t attr;
        pthread_attr_init(&attr);
        pthread_attr_setstacksize(&attr, 16 * 1024 * 1024);
        if (pthread_create(&th, &attr, init_on_thread, NULL) != 0) {
            printf("pthread_create failed\n");
            return 13;
        }
        pthread_mutex_lock(&g_init_mu);
        while (g_init_rc < 0) pthread_cond_wait(&g_init_cv, &g_init_mu);
        rc = g_init_rc;
        pthread_mutex_unlock(&g_init_mu);
    } else {
        rc = init("gc");
    }
    printf("il2cpp_init rc=%d\n", rc);
    if (rc != 0) return 20;

    Il2CppDomain d = domain_get();
    printf("domain=%p\n", d);
    if (thread_attach) thread_attach(d);

    size_t n = 0;
    const Il2CppAssembly **asms = domain_get_assemblies(d, &n);
    printf("assemblies=%zu\n", n);
    Il2CppImage *gc_image = NULL;
    for (size_t i = 0; i < n; i++) {
        Il2CppImage *img = assembly_get_image(asms[i]);
        const char *nm = img ? image_get_name(img) : NULL;
        if (nm && strcmp(nm, "Scripts.GameCore.dll") == 0) {
            gc_image = img;
            printf("FOUND image[%zu] = %s\n", i, nm);
        }
    }
    if (!gc_image) {
        printf("Scripts.GameCore.dll not found; first 8 images:\n");
        for (size_t i = 0; i < n && i < 8; i++) {
            Il2CppImage *img = assembly_get_image(asms[i]);
            printf("  [%zu] %s\n", i, img ? image_get_name(img) : "?");
        }
        return 21;
    }

    Il2CppClass *glh = class_from_name(gc_image, "Assets.Scripts.GameLogic", "GameLogicHelper");
    printf("GameLogicHelper=%p", glh);
    if (glh) printf(" (%s.%s)", class_get_namespace(glh), class_get_name(glh));
    printf("\n");
    if (!glh) return 22;

    const Il2CppMethod *m = class_get_method_from_name(glh, "AdvanceFrameCommands", 2);
    printf("AdvanceFrameCommands(2 args)=%p", m);
    if (m) {
        printf(" name=%s params=%u", method_get_name(m), method_get_param_count(m));
    }
    printf("\n");

    const char *probe_classes[][2] = {
        {"Assets.Scripts.GameLogic", "HeroData"},
        {"", "ActorData"},
        {"Dimension.DS.Network", "DSVarBaseField"},
        {"Dimension.DS.Network", "DSTransferRefArray`1"},
        {"Dimension.DS.Network", "DSTransferArray`1"},
    };
    for (size_t i = 0; i < sizeof(probe_classes) / sizeof(probe_classes[0]); i++) {
        Il2CppClass *k = class_from_name(gc_image, probe_classes[i][0], probe_classes[i][1]);
        printf("class %s.%s = %p\n", probe_classes[i][0], probe_classes[i][1], k);
    }

    printf("A1 done\n");
    return m ? 0 : 23;
}
