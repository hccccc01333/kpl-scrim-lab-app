#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv) {
    setvbuf(stdout, NULL, _IONBF, 0);
    const char *dir = argc > 1 ? argv[1] : "/data/local/tmp/gc/sim";
    int use_abs = argc > 2 ? atoi(argv[2]) : 0;
    setenv("LD_LIBRARY_PATH", dir, 1);
    printf("LD_LIBRARY_PATH=%s abs=%d\n", dir, use_abs);
    const char *deps[] = {"libtprt.so","libpandora.so","libpixuiCurl.so","libPixUI_Unity.so","libpuerts.so","libGameCore.so"};
    char path[1024];
    for (int i = 0; i < 6; i++) {
        if (use_abs) snprintf(path, sizeof path, "%s/%s", dir, deps[i]);
        else snprintf(path, sizeof path, "%s", deps[i]);
        void *h = dlopen(path, RTLD_LAZY | RTLD_GLOBAL);
        printf("dep %s -> %p %s\n", path, h, h ? "" : dlerror());
    }
    printf("dlopen libil2cpp ...\n");
    const char *p = use_abs ? NULL : "libil2cpp.so";
    if (!p) { snprintf(path, sizeof path, "%s/libil2cpp.so", dir); p = path; }
    void *h = dlopen(p, RTLD_LAZY | RTLD_GLOBAL);
    printf("libil2cpp -> %p %s\n", h, h ? "" : dlerror());
    return h ? 0 : 1;
}
