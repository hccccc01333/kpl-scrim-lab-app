#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv) {
    setvbuf(stdout, NULL, _IONBF, 0);
    const char *dir = argc > 1 ? argv[1] : "/data/local/tmp/gc/sim";
    char path[1024];
    /* only libtprt, the sole custom DT_NEEDED of libil2cpp */
    snprintf(path, sizeof path, "%s/libtprt.so", dir);
    void *t = dlopen(path, RTLD_LAZY | RTLD_GLOBAL);
    printf("libtprt -> %p %s\n", t, t ? "" : dlerror());
    snprintf(path, sizeof path, "%s/libil2cpp.so", dir);
    printf("dlopen libil2cpp (only tprt) ...\n");
    void *h = dlopen(path, RTLD_LAZY | RTLD_GLOBAL);
    printf("libil2cpp -> %p %s\n", h, h ? "" : dlerror());
    return h ? 0 : 1;
}
