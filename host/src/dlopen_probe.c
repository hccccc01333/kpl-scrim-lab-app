#include <dlfcn.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
int main(int argc, char **argv) {
    setvbuf(stdout, NULL, _IONBF, 0);
    const char *dir = argc > 1 ? argv[1] : "/data/local/tmp/gc/sim";
    int mode = argc > 2 ? atoi(argv[2]) : 0;
    char path[1024];
    if (mode & 1) {
        const char *deps[] = {"libtprt.so","libpandora.so","libpixuiCurl.so","libPixUI_Unity.so","libpuerts.so","libGameCore.so"};
        for (int i = 0; i < 6; i++) {
            snprintf(path, sizeof path, "%s/%s", dir, deps[i]);
            void *h = dlopen(path, RTLD_LAZY | RTLD_GLOBAL);
            printf("dep %s -> %p %s\n", deps[i], h, h ? "" : dlerror());
        }
    }
    snprintf(path, sizeof path, "%s/libil2cpp.so", dir);
    printf("dlopen %s ...\n", path);
    void *h = dlopen(path, (mode & 2) ? (RTLD_NOW | RTLD_GLOBAL) : (RTLD_LAZY | RTLD_GLOBAL));
    printf("libil2cpp -> %p %s\n", h, h ? "" : dlerror());
    return h ? 0 : 1;
}
