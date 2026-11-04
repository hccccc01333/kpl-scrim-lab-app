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
    dprintf(2, "FAULT sig=%d pc=%#lx lr=%#lx addr=%p\n", sig,
            (unsigned long)uc->uc_mcontext.pc, (unsigned long)uc->uc_mcontext.regs[30],
            si ? si->si_addr : NULL);
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
