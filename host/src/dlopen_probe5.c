#define _GNU_SOURCE 1
#include <dlfcn.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ucontext.h>
#include <unistd.h>
static void on_fault(int sig, siginfo_t *si, void *ctx) {
    ucontext_t *uc = (ucontext_t *)ctx;
    unsigned long pc = (unsigned long)uc->uc_mcontext.pc;
    unsigned long lr = (unsigned long)uc->uc_mcontext.regs[30];
    Dl_info di1, di2;
    memset(&di1, 0, sizeof di1); memset(&di2, 0, sizeof di2);
    dladdr((void *)pc, &di1);
    dladdr((void *)lr, &di2);
    dprintf(2, "FAULT sig=%d pc=%#lx lr=%#lx addr=%p\n", sig, pc, lr, si ? si->si_addr : NULL);
    dprintf(2, "  pc module=%s base=%p off=%#lx\n", di1.dli_fname ? di1.dli_fname : "?",
            di1.dli_fbase, di1.dli_fbase ? pc - (unsigned long)di1.dli_fbase : 0);
    dprintf(2, "  lr module=%s base=%p off=%#lx\n", di2.dli_fname ? di2.dli_fname : "?",
            di2.dli_fbase, di2.dli_fbase ? lr - (unsigned long)di2.dli_fbase : 0);
    _exit(90);
}
int main(int argc, char **argv) {
    setvbuf(stdout, NULL, _IONBF, 0);
    struct sigaction sa; memset(&sa, 0, sizeof sa);
    sa.sa_sigaction = on_fault; sa.sa_flags = SA_SIGINFO;
    sigaction(SIGSEGV, &sa, NULL); sigaction(SIGBUS, &sa, NULL);
    const char *dir = argc > 1 ? argv[1] : "/data/local/tmp/gc/sim";
    int ndeps = argc > 2 ? atoi(argv[2]) : 6;
    const char *deps[] = {"libtprt.so","libpandora.so","libpixuiCurl.so","libPixUI_Unity.so","libpuerts.so","libGameCore.so"};
    char path[1024];
    for (int i = 0; i < ndeps && i < 6; i++) {
        snprintf(path, sizeof path, "%s/%s", dir, deps[i]);
        void *h = dlopen(path, RTLD_LAZY | RTLD_GLOBAL);
        printf("dep %s -> %p %s\n", deps[i], h, h ? "" : dlerror());
    }
    snprintf(path, sizeof path, "%s/libil2cpp.so", dir);
    printf("dlopen libil2cpp (%d deps) ...\n", ndeps);
    void *h = dlopen(path, RTLD_LAZY | RTLD_GLOBAL);
    printf("libil2cpp -> %p %s\n", h, h ? "" : dlerror());
    return h ? 0 : 1;
}
