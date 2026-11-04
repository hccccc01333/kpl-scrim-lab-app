/* Load libil2cpp via DT_NEEDED + $ORIGIN rpath (game-like dependency load). */
#define _GNU_SOURCE 1
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
extern int il2cpp_init(const char *);
extern void il2cpp_set_data_dir(const char *);
int main(int argc, char **argv) {
    setvbuf(stdout, NULL, _IONBF, 0);
    const char *dir = argc > 1 ? argv[1] : "/data/local/tmp/gc/sim";
    printf("il2cpp_needed start dir=%s\n", dir);
    il2cpp_set_data_dir(dir);
    printf("set_data_dir ok\n");
    int rc = il2cpp_init("gc");
    printf("il2cpp_init rc=%d\n", rc);
    return rc;
}
