/* gchost.c — GameCore offline host harness (productized skeleton, source-only).
 *
 * Scope of this file
 * ------------------
 * Implemented stages:
 *   deps        preload the four GameCore dependencies + libGameCore.so
 *   module-init dlsym(ModuleInit), verify the build profile offset, call it
 *   fixture     load and cross-check <fixture>/meta.json (+ init/abc_header.json)
 *   databin     load dumped "stdr" databin blocks, install host table objects,
 *               then verify them through GameCore's DT_Count/DT_GetByIndex
 *
 * Explicitly NOT implemented (fail-closed stubs, never guessed):
 *   context-init  host-built CLevelContext / deskPool
 *   frame-tick    .abc init commands -> CS FIFO -> synchronous tick
 *   state-output  CPlayer/CLevelContext field extraction -> JSONL
 *
 * The harness runs in a private ARM64 process. It does not attach to the game,
 * log in, inject code, or write game files. ./abc/.ope inputs are read-only.
 *
 * Verified profile: Android ARM64 GameCore build 5247758. The offsets below are
 * only valid for that build; any other build must pass --allow-unverified-build
 * and is expected to fail or crash. See docs/host_harness.md.
 *
 * Build (NDK r28b): see host/scripts/build_host.sh
 */
#define _GNU_SOURCE 1

#include <ctype.h>
#include <dirent.h>
#include <dlfcn.h>
#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#if defined(__BYTE_ORDER__) && (__BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__)
#error "gchost expects a little-endian target (Android ARM64)"
#endif

#define GCHOST_VERSION        "0.1.0-skeleton"
#define GCHOST_PROFILE        "gc-android-arm64-build-5247758-v1"
#define GCHOST_PROFILE_BUILD  "5247758"

#define GCHOST_PATH_MAX       1024
#define GCHOST_MAX_TABLES     1024
#define GCHOST_MAX_JSON_BYTES (4u * 1024u * 1024u)
#define GCHOST_MAX_BLOCK_BYTES (256ull * 1024ull * 1024ull)

/* Verified only for GameCore build 5247758. All values are offsets from the
 * ELF load base returned by dladdr(ModuleInit). */
#define PROFILE_MODULE_INIT_OFF  0x46ad0e0u
#define PROFILE_REG_SLOT_OFF     0x5118810u  /* -> pointer to registry holder */
#define PROFILE_REG_HOLDER_OFF   0x52742a0u  /* holds the void*[1024] registry */
#define PROFILE_CS_ARRAY_OFF     0x52c3250u  /* diagnostic read-only */

enum {
    GC_OK                = 0,
    GC_ERR_USAGE         = 2,
    GC_ERR_DEP           = 10,
    GC_ERR_GAMECORE      = 11,
    GC_ERR_PROFILE       = 12,
    GC_ERR_FIXTURE       = 20,
    GC_ERR_DATABIN_LOAD  = 30,
    GC_ERR_DATABIN_CHECK = 31,
    GC_ERR_UNIMPLEMENTED = 40
};

typedef enum {
    VERIFY_NONE = 0,
    VERIFY_SAMPLES,
    VERIFY_FULL
} VerifyMode;

typedef struct {
    const char *lib_dir;
    const char *fixture_dir;
    const char *databin_dir;
    const char *expect_replay_id;
    const char *state_out;
    VerifyMode verify;
    int allow_unverified_build;
    int keep_databin_crc;
    int want_context;
    int want_tick;
    unsigned long long tick_frames;
    int keepalive_sec;
} Options;

typedef struct {
    void *dep[4];
    void *gc;
    int (*module_init)(void);
    void *module_init_sym;
    uintptr_t base;
    int (*dt_count)(uint32_t index);
    void *(*dt_get)(uint32_t index, uint32_t row);
    void (*set_databin_crc)(int enabled);
} GcSession;

/* ------------------------------------------------------------------------- */
/* logging                                                                   */
/* ------------------------------------------------------------------------- */

static void log_info(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    fputs("[gchost] ", stdout);
    vfprintf(stdout, fmt, ap);
    fputc('\n', stdout);
    fflush(stdout);
    va_end(ap);
}

static void log_warn(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    fputs("[gchost] W: ", stderr);
    vfprintf(stderr, fmt, ap);
    fputc('\n', stderr);
    fflush(stderr);
    va_end(ap);
}

static void log_error(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    fputs("[gchost] E: ", stderr);
    vfprintf(stderr, fmt, ap);
    fputc('\n', stderr);
    fflush(stderr);
    va_end(ap);
}

static void on_fatal_signal(int sig, siginfo_t *info, void *context) {
    (void)info;
    (void)context;
    const char *msg = "\n[gchost] fatal signal (SIGSEGV/SIGABRT/SIGBUS)\n";
    if (sig == SIGSEGV) {
        msg = "\n[gchost] fatal signal: SIGSEGV\n";
    } else if (sig == SIGABRT) {
        msg = "\n[gchost] fatal signal: SIGABRT\n";
    } else if (sig == SIGBUS) {
        msg = "\n[gchost] fatal signal: SIGBUS\n";
    }
    if (msg) {
        (void)write(STDOUT_FILENO, msg, strlen(msg));
    }
    _exit(90 + sig);
}

static void install_fatal_signal_handlers(void) {
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_sigaction = on_fatal_signal;
    sa.sa_flags = SA_SIGINFO;
    sigemptyset(&sa.sa_mask);
    (void)sigaction(SIGSEGV, &sa, NULL);
    (void)sigaction(SIGABRT, &sa, NULL);
    (void)sigaction(SIGBUS, &sa, NULL);
}

/* ------------------------------------------------------------------------- */
/* paths / files                                                             */
/* ------------------------------------------------------------------------- */

static int join_path(char *out, size_t cap, const char *dir, const char *name) {
    int n = snprintf(out, cap, "%s/%s", dir, name);
    return (n > 0 && (size_t)n < cap) ? 0 : -1;
}

static void default_lib_dir(char *out, size_t cap) {
    ssize_t n = readlink("/proc/self/exe", out, cap - 1);
    if (n <= 0 || (size_t)n >= cap) {
        snprintf(out, cap, ".");
        return;
    }
    out[n] = '\0';
    char *slash = strrchr(out, '/');
    if (!slash) {
        snprintf(out, cap, ".");
        return;
    }
    if (slash == out) {
        out[1] = '\0';
        return;
    }
    *slash = '\0';
}

static char *read_text_file(const char *path, size_t max_bytes, size_t *out_len) {
    FILE *f = fopen(path, "rb");
    if (!f) {
        log_error("cannot open %s: %s", path, strerror(errno));
        return NULL;
    }
    if (fseek(f, 0, SEEK_END) != 0) {
        log_error("seek failed for %s: %s", path, strerror(errno));
        fclose(f);
        return NULL;
    }
    long n = ftell(f);
    if (n < 0) {
        log_error("tell failed for %s: %s", path, strerror(errno));
        fclose(f);
        return NULL;
    }
    if ((unsigned long long)n > (unsigned long long)max_bytes) {
        log_error("%s is too large (%ld bytes, max %zu)", path, n, max_bytes);
        fclose(f);
        return NULL;
    }
    if (fseek(f, 0, SEEK_SET) != 0) {
        log_error("rewind failed for %s: %s", path, strerror(errno));
        fclose(f);
        return NULL;
    }
    char *buf = (char *)malloc((size_t)n + 1);
    if (!buf) {
        log_error("out of memory reading %s", path);
        fclose(f);
        return NULL;
    }
    size_t got = fread(buf, 1, (size_t)n, f);
    if (got != (size_t)n) {
        log_error("short read for %s (%zu/%ld bytes)", path, got, n);
        free(buf);
        fclose(f);
        return NULL;
    }
    if (fclose(f) != 0) {
        log_error("close failed for %s: %s", path, strerror(errno));
        free(buf);
        return NULL;
    }
    buf[n] = '\0';
    if (out_len) {
        *out_len = (size_t)n;
    }
    return buf;
}

/* ------------------------------------------------------------------------- */
/* minimal JSON reader (no external deps; enough for fixture metadata)       */
/* ------------------------------------------------------------------------- */

typedef struct {
    const char *p;
    const char *end;
} Json;

static int failf(char *err, size_t cap, const char *fmt, ...) {
    if (err && cap) {
        va_list ap;
        va_start(ap, fmt);
        vsnprintf(err, cap, fmt, ap);
        va_end(ap);
    }
    return -1;
}

static void json_ws(Json *j) {
    while (j->p < j->end) {
        char c = *j->p;
        if (c != ' ' && c != '\t' && c != '\n' && c != '\r') {
            break;
        }
        j->p++;
    }
}

static int json_expect(Json *j, char ch) {
    json_ws(j);
    if (j->p >= j->end || *j->p != ch) {
        return -1;
    }
    j->p++;
    return 0;
}

static int json_hexval(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static void json_append(char *out, size_t cap, size_t *n, char c) {
    if (out && cap && *n + 1 < cap) {
        out[*n] = c;
    }
    (*n)++;
}

static int json_parse_string(Json *j, char *out, size_t cap) {
    json_ws(j);
    if (j->p >= j->end || *j->p != '"') {
        return -1;
    }
    j->p++;
    size_t n = 0;
    while (j->p < j->end) {
        unsigned char c = (unsigned char)*j->p++;
        if (c == '"') {
            if (out && cap) {
                out[n < cap ? n : cap - 1] = '\0';
            }
            return 0;
        }
        if (c == '\\') {
            if (j->p >= j->end) {
                return -1;
            }
            char esc = *j->p++;
            switch (esc) {
                case '"':  json_append(out, cap, &n, '"');  break;
                case '\\': json_append(out, cap, &n, '\\'); break;
                case '/':  json_append(out, cap, &n, '/');  break;
                case 'b':  json_append(out, cap, &n, '\b'); break;
                case 'f':  json_append(out, cap, &n, '\f'); break;
                case 'n':  json_append(out, cap, &n, '\n'); break;
                case 'r':  json_append(out, cap, &n, '\r'); break;
                case 't':  json_append(out, cap, &n, '\t'); break;
                case 'u': {
                    if (j->end - j->p < 4) {
                        return -1;
                    }
                    unsigned cp = 0;
                    for (int k = 0; k < 4; k++) {
                        int h = json_hexval(j->p[k]);
                        if (h < 0) {
                            return -1;
                        }
                        cp = (cp << 4) | (unsigned)h;
                    }
                    j->p += 4;
                    json_append(out, cap, &n, cp < 0x80u ? (char)cp : '?');
                    break;
                }
                default:
                    return -1;
            }
            continue;
        }
        if (c < 0x20) {
            return -1;
        }
        json_append(out, cap, &n, (char)c);
    }
    return -1;
}

static int json_skip_number(Json *j) {
    const char *p = j->p;
    if (p < j->end && *p == '-') {
        p++;
    }
    if (p >= j->end || !isdigit((unsigned char)*p)) {
        return -1;
    }
    if (*p == '0') {
        p++;
    } else {
        while (p < j->end && isdigit((unsigned char)*p)) {
            p++;
        }
    }
    if (p < j->end && *p == '.') {
        p++;
        if (p >= j->end || !isdigit((unsigned char)*p)) {
            return -1;
        }
        while (p < j->end && isdigit((unsigned char)*p)) {
            p++;
        }
    }
    if (p < j->end && (*p == 'e' || *p == 'E')) {
        p++;
        if (p < j->end && (*p == '+' || *p == '-')) {
            p++;
        }
        if (p >= j->end || !isdigit((unsigned char)*p)) {
            return -1;
        }
        while (p < j->end && isdigit((unsigned char)*p)) {
            p++;
        }
    }
    j->p = p;
    return 0;
}

static int json_skip_value(Json *j, int depth) {
    json_ws(j);
    if (j->p >= j->end) {
        return -1;
    }
    char c = *j->p;
    if (c == '"') {
        return json_parse_string(j, NULL, 0);
    }
    if (c == '{' || c == '[') {
        if (depth > 64) {
            return -1;
        }
        char close = (c == '{') ? '}' : ']';
        j->p++;
        json_ws(j);
        if (j->p < j->end && *j->p == close) {
            j->p++;
            return 0;
        }
        for (;;) {
            if (c == '{') {
                if (json_parse_string(j, NULL, 0) != 0) {
                    return -1;
                }
                if (json_expect(j, ':') != 0) {
                    return -1;
                }
            }
            if (json_skip_value(j, depth + 1) != 0) {
                return -1;
            }
            json_ws(j);
            if (j->p >= j->end) {
                return -1;
            }
            if (*j->p == ',') {
                j->p++;
                continue;
            }
            if (*j->p == close) {
                j->p++;
                return 0;
            }
            return -1;
        }
    }
    if (c == '-' || isdigit((unsigned char)c)) {
        return json_skip_number(j);
    }
    if (j->end - j->p >= 4 && memcmp(j->p, "true", 4) == 0) {
        j->p += 4;
        return 0;
    }
    if (j->end - j->p >= 5 && memcmp(j->p, "false", 5) == 0) {
        j->p += 5;
        return 0;
    }
    if (j->end - j->p >= 4 && memcmp(j->p, "null", 4) == 0) {
        j->p += 4;
        return 0;
    }
    return -1;
}

static int json_parse_uint(Json *j, unsigned long long *out) {
    json_ws(j);
    if (j->p >= j->end || !isdigit((unsigned char)*j->p)) {
        return -1;
    }
    unsigned long long v = 0;
    while (j->p < j->end && isdigit((unsigned char)*j->p)) {
        unsigned d = (unsigned)(*j->p - '0');
        if (v > (ULLONG_MAX - d) / 10ull) {
            return -1;
        }
        v = v * 10ull + d;
        j->p++;
    }
    if (j->p < j->end && (*j->p == '.' || *j->p == 'e' || *j->p == 'E')) {
        return -1;
    }
    *out = v;
    return 0;
}

static int json_parse_string_array_last(Json *j, char *out, size_t cap, int *has_value) {
    *has_value = 0;
    if (json_expect(j, '[') != 0) {
        return -1;
    }
    json_ws(j);
    if (j->p < j->end && *j->p == ']') {
        j->p++;
        return 0;
    }
    for (;;) {
        char tmp[256];
        if (json_parse_string(j, tmp, sizeof(tmp)) != 0) {
            return -1;
        }
        snprintf(out, cap, "%s", tmp);
        *has_value = 1;
        json_ws(j);
        if (j->p < j->end && *j->p == ',') {
            j->p++;
            continue;
        }
        if (j->p < j->end && *j->p == ']') {
            j->p++;
            return 0;
        }
        return -1;
    }
}

/* ------------------------------------------------------------------------- */
/* fixture metadata                                                          */
/* ------------------------------------------------------------------------- */

typedef struct {
    char schema[64];
    char replay_id[128];
    char build[64];
    unsigned long long total_frames;
    char abc_sha256[65];
} FixtureMeta;

typedef struct {
    char schema[64];
    char replay_id[128];
    char builds_last[64];
    int has_builds_last;
    unsigned long long total_frame_num;
    int has_total_frame_num;
} InitHeader;

static int is_lower_sha256(const char *s) {
    if (strlen(s) != 64) {
        return 0;
    }
    for (size_t i = 0; i < 64; i++) {
        char c = s[i];
        if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) {
            return 0;
        }
    }
    return 1;
}

static int parse_fixture_meta(const char *text, FixtureMeta *m, char *err, size_t errcap) {
    enum {
        MF_SCHEMA = 1u << 0,
        MF_REPLAY = 1u << 1,
        MF_BUILD  = 1u << 2,
        MF_FRAMES = 1u << 3,
        MF_SHA    = 1u << 4
    };
    memset(m, 0, sizeof(*m));
    Json j = { text, text + strlen(text) };
    unsigned seen = 0;

    if (json_expect(&j, '{') != 0) {
        return failf(err, errcap, "meta.json: expected a JSON object");
    }
    for (;;) {
        json_ws(&j);
        if (j.p >= j.end) {
            return failf(err, errcap, "meta.json: truncated object");
        }
        if (*j.p == '}') {
            j.p++;
            break;
        }
        char key[64];
        if (json_parse_string(&j, key, sizeof(key)) != 0 || json_expect(&j, ':') != 0) {
            return failf(err, errcap, "meta.json: malformed object member");
        }
        if (strcmp(key, "schema") == 0) {
            if (seen & MF_SCHEMA) return failf(err, errcap, "meta.json: duplicate schema");
            if (json_parse_string(&j, m->schema, sizeof(m->schema)) != 0)
                return failf(err, errcap, "meta.json: schema must be a string");
            seen |= MF_SCHEMA;
        } else if (strcmp(key, "replay_id") == 0) {
            if (seen & MF_REPLAY) return failf(err, errcap, "meta.json: duplicate replay_id");
            if (json_parse_string(&j, m->replay_id, sizeof(m->replay_id)) != 0)
                return failf(err, errcap, "meta.json: replay_id must be a string");
            seen |= MF_REPLAY;
        } else if (strcmp(key, "build") == 0) {
            if (seen & MF_BUILD) return failf(err, errcap, "meta.json: duplicate build");
            if (json_parse_string(&j, m->build, sizeof(m->build)) != 0)
                return failf(err, errcap, "meta.json: build must be a string");
            seen |= MF_BUILD;
        } else if (strcmp(key, "total_frames") == 0) {
            if (seen & MF_FRAMES) return failf(err, errcap, "meta.json: duplicate total_frames");
            if (json_parse_uint(&j, &m->total_frames) != 0)
                return failf(err, errcap, "meta.json: total_frames must be a non-negative integer");
            seen |= MF_FRAMES;
        } else if (strcmp(key, "abc_sha256") == 0) {
            if (seen & MF_SHA) return failf(err, errcap, "meta.json: duplicate abc_sha256");
            if (json_parse_string(&j, m->abc_sha256, sizeof(m->abc_sha256)) != 0)
                return failf(err, errcap, "meta.json: abc_sha256 must be a string");
            seen |= MF_SHA;
        } else if (json_skip_value(&j, 0) != 0) {
            return failf(err, errcap, "meta.json: bad value for key '%s'", key);
        }
        json_ws(&j);
        if (j.p < j.end && *j.p == ',') {
            j.p++;
            continue;
        }
        if (j.p < j.end && *j.p == '}') {
            j.p++;
            break;
        }
        return failf(err, errcap, "meta.json: expected ',' or '}'");
    }
    json_ws(&j);
    if (j.p != j.end) {
        return failf(err, errcap, "meta.json: trailing bytes after object");
    }
    if (!(seen & MF_SCHEMA)) return failf(err, errcap, "meta.json: missing schema");
    if (!(seen & MF_REPLAY)) return failf(err, errcap, "meta.json: missing replay_id");
    if (!(seen & MF_BUILD)) return failf(err, errcap, "meta.json: missing build");
    if (!(seen & MF_FRAMES)) return failf(err, errcap, "meta.json: missing total_frames");
    if (!(seen & MF_SHA)) return failf(err, errcap, "meta.json: missing abc_sha256");
    return 0;
}

/* The top-level abc_header.json has {"schema", "replay_id", "header": {...}}.
 * Note: make_fixture.py writes totalFrameNum/builds inside the nested "header"
 * object, so the nested object is parsed with the same field names. */
static int parse_init_header(const char *text, InitHeader *h, char *err, size_t errcap) {
    memset(h, 0, sizeof(*h));
    Json j = { text, text + strlen(text) };
    char top_schema[64] = {0};
    char top_replay[128] = {0};
    int have_header = 0;

    if (json_expect(&j, '{') != 0) {
        return failf(err, errcap, "abc_header.json: expected a JSON object");
    }
    for (;;) {
        json_ws(&j);
        if (j.p >= j.end) {
            return failf(err, errcap, "abc_header.json: truncated object");
        }
        if (*j.p == '}') {
            j.p++;
            break;
        }
        char key[64];
        if (json_parse_string(&j, key, sizeof(key)) != 0 || json_expect(&j, ':') != 0) {
            return failf(err, errcap, "abc_header.json: malformed object member");
        }
        if (strcmp(key, "schema") == 0) {
            if (json_parse_string(&j, top_schema, sizeof(top_schema)) != 0)
                return failf(err, errcap, "abc_header.json: schema must be a string");
        } else if (strcmp(key, "replay_id") == 0) {
            if (json_parse_string(&j, top_replay, sizeof(top_replay)) != 0)
                return failf(err, errcap, "abc_header.json: replay_id must be a string");
        } else if (strcmp(key, "header") == 0) {
            /* The nested header is an object, not the same field set as the
             * top level; only pull totalFrameNum/builds from it. */
            if (json_expect(&j, '{') != 0)
                return failf(err, errcap, "abc_header.json: header must be an object");
            for (;;) {
                json_ws(&j);
                if (j.p >= j.end)
                    return failf(err, errcap, "abc_header.json: truncated header");
                if (*j.p == '}') { j.p++; break; }
                char hkey[64];
                if (json_parse_string(&j, hkey, sizeof(hkey)) != 0 || json_expect(&j, ':') != 0)
                    return failf(err, errcap, "abc_header.json: malformed header member");
                if (strcmp(hkey, "totalFrameNum") == 0) {
                    if (json_parse_uint(&j, &h->total_frame_num) != 0)
                        return failf(err, errcap, "abc_header.json: totalFrameNum must be an integer");
                    h->has_total_frame_num = 1;
                } else if (strcmp(hkey, "builds") == 0) {
                    if (json_parse_string_array_last(&j, h->builds_last, sizeof(h->builds_last),
                                                     &h->has_builds_last) != 0)
                        return failf(err, errcap, "abc_header.json: builds must be a string array");
                } else if (json_skip_value(&j, 0) != 0) {
                    return failf(err, errcap, "abc_header.json: bad header value '%s'", hkey);
                }
                json_ws(&j);
                if (j.p < j.end && *j.p == ',') { j.p++; continue; }
                if (j.p < j.end && *j.p == '}') { j.p++; break; }
                return failf(err, errcap, "abc_header.json: expected ',' or '}' in header");
            }
            have_header = 1;
        } else if (json_skip_value(&j, 0) != 0) {
            return failf(err, errcap, "abc_header.json: bad value for '%s'", key);
        }
        json_ws(&j);
        if (j.p < j.end && *j.p == ',') {
            j.p++;
            continue;
        }
        if (j.p < j.end && *j.p == '}') {
            j.p++;
            break;
        }
        return failf(err, errcap, "abc_header.json: expected ',' or '}'");
    }
    json_ws(&j);
    if (j.p != j.end) {
        return failf(err, errcap, "abc_header.json: trailing bytes after object");
    }
    if (!have_header) {
        return failf(err, errcap, "abc_header.json: missing header object");
    }
    snprintf(h->schema, sizeof(h->schema), "%s", top_schema);
    snprintf(h->replay_id, sizeof(h->replay_id), "%s", top_replay);
    return 0;
}

static int verify_fixture(const char *fixture_dir, const char *expect_replay_id,
                          FixtureMeta *meta) {
    char path[GCHOST_PATH_MAX];
    char err[256];

    if (join_path(path, sizeof(path), fixture_dir, "meta.json") != 0) {
        log_error("fixture path too long");
        return GC_ERR_FIXTURE;
    }
    size_t text_len = 0;
    char *text = read_text_file(path, GCHOST_MAX_JSON_BYTES, &text_len);
    if (!text) {
        return GC_ERR_FIXTURE;
    }
    if (parse_fixture_meta(text, meta, err, sizeof(err)) != 0) {
        log_error("%s", err);
        free(text);
        return GC_ERR_FIXTURE;
    }
    free(text);

    if (strcmp(meta->schema, "kpl-gamecore-fixture-v1") != 0) {
        log_error("fixture meta: unsupported schema '%s'", meta->schema);
        return GC_ERR_FIXTURE;
    }
    if (meta->replay_id[0] == '\0' || meta->build[0] == '\0') {
        log_error("fixture meta: replay_id/build must not be empty");
        return GC_ERR_FIXTURE;
    }
    if (meta->total_frames == 0) {
        log_error("fixture meta: total_frames must be > 0");
        return GC_ERR_FIXTURE;
    }
    if (!is_lower_sha256(meta->abc_sha256)) {
        log_error("fixture meta: abc_sha256 must be 64 lowercase hex characters");
        return GC_ERR_FIXTURE;
    }
    if (expect_replay_id && strcmp(expect_replay_id, meta->replay_id) != 0) {
        log_error("fixture meta: replay_id '%s' != expected '%s'",
                  meta->replay_id, expect_replay_id);
        return GC_ERR_FIXTURE;
    }
    log_info("fixture meta OK: replay_id=%s build=%s frames=%llu abc_sha256=%.12s...",
             meta->replay_id, meta->build, meta->total_frames, meta->abc_sha256);

    if (join_path(path, sizeof(path), fixture_dir, "init/abc_header.json") != 0) {
        log_error("fixture path too long");
        return GC_ERR_FIXTURE;
    }
    if (access(path, R_OK) != 0) {
        log_warn("fixture: %s not present; init cross-check skipped", path);
        return GC_OK;
    }
    text = read_text_file(path, GCHOST_MAX_JSON_BYTES, &text_len);
    if (!text) {
        return GC_ERR_FIXTURE;
    }
    InitHeader h;
    if (parse_init_header(text, &h, err, sizeof(err)) != 0) {
        log_error("%s", err);
        free(text);
        return GC_ERR_FIXTURE;
    }
    free(text);

    if (strcmp(h.schema, "kpl-gamecore-fixture-init-v1") != 0) {
        log_error("fixture init: unsupported schema '%s'", h.schema);
        return GC_ERR_FIXTURE;
    }
    if (strcmp(h.replay_id, meta->replay_id) != 0) {
        log_error("fixture init: replay_id '%s' != meta '%s'", h.replay_id, meta->replay_id);
        return GC_ERR_FIXTURE;
    }
    if (h.has_total_frame_num && h.total_frame_num != meta->total_frames) {
        log_error("fixture init: totalFrameNum %llu != meta total_frames %llu",
                  h.total_frame_num, meta->total_frames);
        return GC_ERR_FIXTURE;
    }
    if (h.has_builds_last && strcmp(h.builds_last, meta->build) != 0) {
        log_error("fixture init: last build '%s' != meta build '%s'",
                  h.builds_last, meta->build);
        return GC_ERR_FIXTURE;
    }
    log_info("fixture init OK: replay_id=%s last_build=%s totalFrameNum=%s%llu",
             h.replay_id, h.has_builds_last ? h.builds_last : "(absent)",
             h.has_total_frame_num ? "" : "(absent)", h.total_frame_num);
    return GC_OK;
}

/* ------------------------------------------------------------------------- */
/* GameCore loading                                                          */
/* ------------------------------------------------------------------------- */

static void *open_global(const char *lib_dir, const char *name) {
    char path[GCHOST_PATH_MAX];
    if (join_path(path, sizeof(path), lib_dir, name) != 0) {
        log_error("library path too long for %s", name);
        return NULL;
    }
    dlerror();
    void *h = dlopen(path, RTLD_LAZY | RTLD_GLOBAL);
    if (!h) {
        const char *e = dlerror();
        log_error("dlopen %s FAIL: %s", path, e ? e : "unknown error");
        return NULL;
    }
    log_info("dlopen %-22s OK", name);
    return h;
}

static void log_exported_symbols(void *gc) {
    const char *names[] = {
        "ModuleInit", "DT_Count", "DT_GetByIndex",
        "SGameSetEnableDatabinCrcFromFile",
        "PushCsBuffer", "CommitCsBuffer", "ResetCsBuffer",
        "PushViewBuffer", "CommitViewBuffer",
        "SGC_GetPlayerSettleData",
    };
    log_info("library exports:");
    for (size_t i = 0; i < sizeof(names) / sizeof(names[0]); i++) {
        void *sym = dlsym(gc, names[i]);
        log_info("  sym %-36s %s", names[i], sym ? "present" : "absent");
    }
}

static int load_gamecore(GcSession *s, const char *lib_dir) {
    static const char *deps[] = {
        "libpandora.so",
        "libpixuiCurl.so",
        "libPixUI_Unity.so",
        "libpuerts.so",
    };
    log_info("== stage: deps ==");
    for (size_t i = 0; i < sizeof(deps) / sizeof(deps[0]); i++) {
        s->dep[i] = open_global(lib_dir, deps[i]);
        if (!s->dep[i]) {
            return GC_ERR_DEP;
        }
    }
    s->gc = open_global(lib_dir, "libGameCore.so");
    if (!s->gc) {
        return GC_ERR_GAMECORE;
    }
    log_exported_symbols(s->gc);

    s->module_init_sym = dlsym(s->gc, "ModuleInit");
    if (!s->module_init_sym) {
        log_error("libGameCore.so does not export ModuleInit");
        return GC_ERR_GAMECORE;
    }
    s->module_init = (int (*)(void))s->module_init_sym;
    s->dt_count = (int (*)(uint32_t))dlsym(s->gc, "DT_Count");
    s->dt_get = (void *(*)(uint32_t, uint32_t))dlsym(s->gc, "DT_GetByIndex");
    s->set_databin_crc =
        (void (*)(int))dlsym(s->gc, "SGameSetEnableDatabinCrcFromFile");
    return GC_OK;
}

static int stage_module_init(GcSession *s, int allow_unverified_build) {
    log_info("== stage: module-init ==");
    Dl_info info;
    if (dladdr(s->module_init_sym, &info) == 0 || !info.dli_fbase) {
        log_error("dladdr(ModuleInit) failed; cannot derive libGameCore base");
        return GC_ERR_PROFILE;
    }
    s->base = (uintptr_t)info.dli_fbase;
    uintptr_t off = (uintptr_t)s->module_init_sym - s->base;
    log_info("libGameCore base=%#" PRIxPTR " ModuleInit offset=%#" PRIxPTR,
             s->base, off);
    log_info("profile=%s verified_build=%s", GCHOST_PROFILE, GCHOST_PROFILE_BUILD);
    if (off != (uintptr_t)PROFILE_MODULE_INIT_OFF) {
        log_error("ModuleInit offset does not match the verified profile "
                  "(expected %#x)", PROFILE_MODULE_INIT_OFF);
        if (!allow_unverified_build) {
            return GC_ERR_PROFILE;
        }
        log_warn("continuing because --allow-unverified-build was supplied; "
                 "all subsequent offsets are unverified");
    }

    log_info("calling ModuleInit() @ %p", s->module_init_sym);
    int r = s->module_init();
    log_info("ModuleInit returned %d", r);
    if (r != 0) {
        log_warn("ModuleInit's return value is diagnostic only; nonzero values were "
                 "observed on the verified build (it is not a success code)");
    }
    return GC_OK;
}

/* ------------------------------------------------------------------------- */
/* databin blocks                                                            */
/* ------------------------------------------------------------------------- */

static uint32_t rd_u32le(const unsigned char *p) {
    uint32_t v;
    memcpy(&v, p, sizeof(v));
    return v;
}

static uint64_t rd_u64le(const unsigned char *p) {
    uint64_t v;
    memcpy(&v, p, sizeof(v));
    return v;
}

typedef struct {
    void **vt;                 /* must stay first: GameCore reads it at self+0 */
    unsigned char *block;      /* owned "stdr" block */
    uint32_t stride;
    uint32_t rows;
    char name[160];
} HostTable;

static uint64_t g_vtable[8];

static int host_table_count(void *self) {
    return (int)((HostTable *)self)->rows;
}

static void *host_table_get(void *self, uint32_t index) {
    HostTable *t = (HostTable *)self;
    if (!t->block || index >= t->rows) {
        return NULL;
    }
    return t->block + 0x98 + (size_t)index * t->stride;
}

static int ends_with(const char *s, const char *suffix) {
    size_t ls = strlen(s);
    size_t lf = strlen(suffix);
    return ls >= lf && memcmp(s + (ls - lf), suffix, lf) == 0;
}

static int load_block(const char *path, HostTable *t, char *err, size_t errcap) {
    FILE *f = fopen(path, "rb");
    if (!f) {
        return failf(err, errcap, "open: %s", strerror(errno));
    }
    if (fseek(f, 0, SEEK_END) != 0) {
        int e = errno;
        fclose(f);
        return failf(err, errcap, "seek: %s", strerror(e));
    }
    long n = ftell(f);
    if (n < 0) {
        int e = errno;
        fclose(f);
        return failf(err, errcap, "tell: %s", strerror(e));
    }
    if ((unsigned long long)n > GCHOST_MAX_BLOCK_BYTES) {
        fclose(f);
        return failf(err, errcap, "block too large (%ld bytes)", n);
    }
    if (fseek(f, 0, SEEK_SET) != 0) {
        int e = errno;
        fclose(f);
        return failf(err, errcap, "rewind: %s", strerror(e));
    }
    unsigned char *b = (unsigned char *)malloc((size_t)n ? (size_t)n : 1);
    if (!b) {
        fclose(f);
        return failf(err, errcap, "out of memory");
    }
    size_t got = fread(b, 1, (size_t)n, f);
    if (got != (size_t)n) {
        free(b);
        fclose(f);
        return failf(err, errcap, "short read");
    }
    fclose(f);

    if (n < 0x98 || memcmp(b, "stdr", 4) != 0) {
        free(b);
        return failf(err, errcap, "bad magic/length");
    }
    uint32_t stride = rd_u32le(b + 0x14);
    uint32_t rows = rd_u32le(b + 0x18);
    uint64_t blob_len = rd_u64le(b + 0x90);
    uint64_t expect_len = 0x98ull + (uint64_t)stride * (uint64_t)rows;
    if (stride == 0 || rows == 0) {
        free(b);
        return failf(err, errcap, "zero stride/rows");
    }
    if (blob_len != (uint64_t)n || expect_len != (uint64_t)n) {
        free(b);
        return failf(err, errcap,
                     "size mismatch (file=%ld blob=%llu header=%llu)",
                     n, (unsigned long long)blob_len,
                     (unsigned long long)expect_len);
    }
    memset(t, 0, sizeof(*t));
    t->block = b;
    t->stride = stride;
    t->rows = rows;
    return 0;
}

static void free_tables(HostTable *tables) {
    if (!tables) {
        return;
    }
    for (size_t i = 0; i < GCHOST_MAX_TABLES; i++) {
        free(tables[i].block);
    }
    free(tables);
}

static int stage_register_databin(GcSession *s, const char *blocks_dir,
                                  VerifyMode mode, int keep_crc) {
    log_info("== stage: databin ==");
    if (!s->dt_count || !s->dt_get) {
        log_error("DT_Count/DT_GetByIndex are not exported; cannot verify databin");
        return GC_ERR_GAMECORE;
    }
    if (keep_crc) {
        log_info("databin CRC-from-file switch left unchanged");
    } else if (s->set_databin_crc) {
        s->set_databin_crc(0);
        log_info("SGameSetEnableDatabinCrcFromFile(0) called");
    } else {
        log_warn("SGameSetEnableDatabinCrcFromFile absent; continuing");
    }

    DIR *d = opendir(blocks_dir);
    if (!d) {
        log_error("opendir %s: %s", blocks_dir, strerror(errno));
        return GC_ERR_DATABIN_LOAD;
    }

    HostTable *tables = (HostTable *)calloc(GCHOST_MAX_TABLES, sizeof(*tables));
    void **registry = (void **)calloc(GCHOST_MAX_TABLES, sizeof(*registry));
    if (!tables || !registry) {
        log_error("out of memory for databin tables");
        closedir(d);
        free_tables(tables);
        free(registry);
        return GC_ERR_DATABIN_LOAD;
    }

    g_vtable[3] = (uint64_t)(uintptr_t)host_table_count;
    g_vtable[4] = (uint64_t)(uintptr_t)host_table_get;

    int installed = 0;
    int skipped = 0;
    int duplicates = 0;
    struct dirent *de;
    while ((de = readdir(d)) != NULL) {
        const char *name = de->d_name;
        if (!ends_with(name, ".bytes.bin")) {
            continue;
        }
        errno = 0;
        char *endp = NULL;
        long idx = strtol(name, &endp, 10);
        if (errno != 0 || endp == name || *endp != '_' ||
            idx < 0 || idx >= GCHOST_MAX_TABLES) {
            log_warn("databin: skip unparseable filename %s", name);
            skipped++;
            continue;
        }
        if (tables[idx].block) {
            log_warn("databin: duplicate index %ld (%s)", idx, name);
            duplicates++;
            continue;
        }
        char path[GCHOST_PATH_MAX];
        if (join_path(path, sizeof(path), blocks_dir, name) != 0) {
            log_warn("databin: path too long for %s", name);
            skipped++;
            continue;
        }
        char err[192];
        if (load_block(path, &tables[idx], err, sizeof(err)) != 0) {
            log_warn("databin: skip %s: %s", name, err);
            skipped++;
            continue;
        }
        tables[idx].vt = (void **)g_vtable;
        snprintf(tables[idx].name, sizeof(tables[idx].name), "%s", name);
        registry[idx] = &tables[idx];
        installed++;
    }
    closedir(d);

    if (duplicates != 0) {
        log_error("databin: %d duplicate index(es); refusing to install", duplicates);
        free_tables(tables);
        free(registry);
        return GC_ERR_DATABIN_LOAD;
    }
    if (installed == 0) {
        log_error("databin: no .bytes.bin blocks found in %s", blocks_dir);
        free_tables(tables);
        free(registry);
        return GC_ERR_DATABIN_LOAD;
    }

    uintptr_t expected_holder = s->base + (uintptr_t)PROFILE_REG_HOLDER_OFF;
    uintptr_t slot = *(volatile uintptr_t *)(s->base + (uintptr_t)PROFILE_REG_SLOT_OFF);
    uintptr_t holder;
    if (slot == 0) {
        holder = expected_holder;
    } else if (slot == expected_holder) {
        holder = slot;
    } else {
        log_error("databin: registry slot holds unexpected pointer %#" PRIxPTR
                  " (expected 0 or %#" PRIxPTR "); refusing to write",
                  slot, expected_holder);
        free_tables(tables);
        free(registry);
        return GC_ERR_PROFILE;
    }
    *(void **)holder = registry;
    if (*(void **)holder != registry) {
        log_error("databin: registry write did not stick");
        free_tables(tables);
        free(registry);
        return GC_ERR_DATABIN_LOAD;
    }
    log_info("databin registry installed: installed=%d skipped=%d holder=%p",
             installed, skipped, (void *)holder);

    int rc = GC_OK;
    if (mode == VERIFY_NONE) {
        log_info("databin verification skipped (--verify none)");
    } else {
        int count_bad = 0;
        int row_bad = 0;
        int verified = 0;
        unsigned long long total_rows = 0;
        for (int i = 0; i < GCHOST_MAX_TABLES; i++) {
            HostTable *t = &tables[i];
            if (!t->block) {
                continue;
            }
            int count = s->dt_count((uint32_t)i);
            if (count != (int)t->rows) {
                log_error("DT_Count(%d)=%d, expected %u", i, count, t->rows);
                count_bad++;
                continue;
            }
            int ok = 1;
            if (mode == VERIFY_FULL) {
                for (uint32_t r = 0; r < t->rows; r++) {
                    void *row = s->dt_get((uint32_t)i, r);
                    if (!row ||
                        memcmp(row, t->block + 0x98 + (size_t)r * t->stride,
                               t->stride) != 0) {
                        log_error("databin[%d] row %u mismatch/null", i, r);
                        ok = 0;
                        break;
                    }
                }
            } else {
                uint32_t samples[3];
                samples[0] = 0;
                samples[1] = t->rows / 2;
                samples[2] = t->rows - 1;
                for (size_t k = 0; k < 3; k++) {
                    uint32_t r = samples[k];
                    void *row = s->dt_get((uint32_t)i, r);
                    if (!row ||
                        memcmp(row, t->block + 0x98 + (size_t)r * t->stride,
                               t->stride) != 0) {
                        log_error("databin[%d] sample row %u mismatch/null", i, r);
                        ok = 0;
                        break;
                    }
                }
            }
            if (ok) {
                verified++;
                total_rows += t->rows;
            } else {
                row_bad++;
            }
            int done = verified + row_bad + count_bad;
            if (done % 200 == 0) {
                log_info("databin progress: checked=%d verified=%d", done, verified);
            }
        }
        log_info("databin RESULT installed=%d verified=%d count_bad=%d row_bad=%d "
                 "total_rows=%llu mode=%s",
                 installed, verified, count_bad, row_bad, total_rows,
                 mode == VERIFY_FULL ? "full" : "samples");
        if (count_bad || row_bad) {
            rc = GC_ERR_DATABIN_CHECK;
        }
    }

    /* Diagnostic only: the harness never constructs this array. */
    void *cs = *(void **)(s->base + (uintptr_t)PROFILE_CS_ARRAY_OFF);
    log_info("CS array slot (diagnostic, not initialized by harness) = %p", cs);
    return rc;
}

static int databin_build_gate(const FixtureMeta *meta, int have_meta,
                              int allow_unverified) {
    if (!have_meta) {
        if (allow_unverified) {
            log_warn("databin: no fixture; proceeding because "
                     "--allow-unverified-build was supplied");
            return GC_OK;
        }
        log_error("databin: --fixture is required so the build can be checked "
                  "against the verified profile (or pass --allow-unverified-build)");
        return GC_ERR_PROFILE;
    }
    if (strcmp(meta->build, GCHOST_PROFILE_BUILD) != 0) {
        log_error("databin: fixture build '%s' != verified profile build '%s'",
                  meta->build, GCHOST_PROFILE_BUILD);
        if (!allow_unverified) {
            return GC_ERR_PROFILE;
        }
        log_warn("databin: continuing because --allow-unverified-build was supplied; "
                 "offsets may be wrong");
    }
    return GC_OK;
}

/* ------------------------------------------------------------------------- */
/* unimplemented stages (fail closed; no guessed offsets or fabricated state) */
/* ------------------------------------------------------------------------- */

static int stage_context_init_stub(void) {
    log_info("== stage: context-init ==");
    log_error("UNIMPLEMENTED (H4): host-side CLevelContext/deskPool construction");
    log_error("missing: CLevelContext field map, deskPool entry layout, CS buffer "
              "array ownership, and allocation/free semantics");
    log_error("the harness does not fabricate vtables or guess field offsets");
    return GC_ERR_UNIMPLEMENTED;
}

static int stage_frame_tick_stub(void) {
    log_info("== stage: frame-tick ==");
    log_error("UNIMPLEMENTED (H5): .abc init header -> CS init command stream -> "
              "PushCsBuffer/CommitCsBuffer -> synchronous tick");
    log_error("missing: command encoding, tick entry point (0x46B7888 or "
              "context+0x280 has not been validated in a host context), frame pacing");
    log_error("no frame was ticked");
    return GC_ERR_UNIMPLEMENTED;
}

static int stage_state_output_stub(void) {
    log_info("== stage: state-output ==");
    log_error("UNIMPLEMENTED (H6): CPlayer/CLevelContext field extraction -> "
              "kpl-runtime-v1 JSONL");
    log_error("missing: verified player/context field table and state readout");
    log_error("no state file was written");
    return GC_ERR_UNIMPLEMENTED;
}

/* ------------------------------------------------------------------------- */
/* CLI                                                                       */
/* ------------------------------------------------------------------------- */

static void usage(FILE *out, const char *argv0) {
    fprintf(out,
        "gchost %s — GameCore offline host harness (skeleton)\n"
        "\n"
        "Implemented stages: deps, module-init, fixture meta, databin registration.\n"
        "Unimplemented stubs: context-init, frame-tick, state-output (fail closed).\n"
        "\n"
        "Usage: %s [options]\n"
        "\n"
        "  --lib-dir DIR          directory with libGameCore.so + 4 dependencies\n"
        "                         (default: directory of this executable)\n"
        "  --fixture DIR          fixture root containing meta.json (+ init/abc_header.json)\n"
        "  --replay-id ID         require fixture meta.replay_id == ID\n"
        "  --databin-dir DIR      directory of <index>_<name>.bytes.bin blocks\n"
        "  --verify MODE          none | samples | full (default: samples)\n"
        "  --allow-unverified-build  bypass the build/offset gate (dangerous)\n"
        "  --keep-databin-crc     do not call SGameSetEnableDatabinCrcFromFile(0)\n"
        "  --context              request the unimplemented context-init stage\n"
        "  --tick N               request N frames of the unimplemented tick stage\n"
        "  --state-out FILE       request the unimplemented state-output stage\n"
        "  --keepalive SEC        sleep SEC seconds after the stages (default: 0)\n"
        "  --help                 show this help\n"
        "\n"
        "Exit codes: 0 ok, 2 usage, 10 dependency, 11 GameCore/symbol,\n"
        "            12 profile/offset, 20 fixture, 30 databin load,\n"
        "            31 databin verify, 40 requested stage unimplemented,\n"
        "            90+signal on fatal signal.\n"
        "\n"
        "This is a private host process: no login, no injection, no game file writes.\n",
        GCHOST_VERSION, argv0);
}

static int need_arg(int argc, char **argv, int *i, const char **out) {
    if (*i + 1 >= argc) {
        log_error("option %s requires an argument", argv[*i]);
        return -1;
    }
    *out = argv[++(*i)];
    return 0;
}

static int parse_verify_mode(const char *s, VerifyMode *mode) {
    if (strcmp(s, "none") == 0) {
        *mode = VERIFY_NONE;
    } else if (strcmp(s, "samples") == 0) {
        *mode = VERIFY_SAMPLES;
    } else if (strcmp(s, "full") == 0) {
        *mode = VERIFY_FULL;
    } else {
        log_error("--verify must be none|samples|full");
        return -1;
    }
    return 0;
}

static char g_default_lib_dir[GCHOST_PATH_MAX];

static int parse_options(int argc, char **argv, Options *opt) {
    default_lib_dir(g_default_lib_dir, sizeof(g_default_lib_dir));
    memset(opt, 0, sizeof(*opt));
    opt->lib_dir = g_default_lib_dir;
    opt->verify = VERIFY_SAMPLES;

    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (strcmp(arg, "--help") == 0 || strcmp(arg, "-h") == 0) {
            usage(stdout, argv[0]);
            return 1;
        } else if (strcmp(arg, "--lib-dir") == 0) {
            const char *v;
            if (need_arg(argc, argv, &i, &v) != 0) return -1;
            opt->lib_dir = v;
        } else if (strcmp(arg, "--fixture") == 0) {
            const char *v;
            if (need_arg(argc, argv, &i, &v) != 0) return -1;
            opt->fixture_dir = v;
        } else if (strcmp(arg, "--replay-id") == 0) {
            const char *v;
            if (need_arg(argc, argv, &i, &v) != 0) return -1;
            opt->expect_replay_id = v;
        } else if (strcmp(arg, "--databin-dir") == 0) {
            const char *v;
            if (need_arg(argc, argv, &i, &v) != 0) return -1;
            opt->databin_dir = v;
        } else if (strcmp(arg, "--verify") == 0) {
            const char *v;
            if (need_arg(argc, argv, &i, &v) != 0) return -1;
            if (parse_verify_mode(v, &opt->verify) != 0) return -1;
        } else if (strcmp(arg, "--allow-unverified-build") == 0) {
            opt->allow_unverified_build = 1;
        } else if (strcmp(arg, "--keep-databin-crc") == 0) {
            opt->keep_databin_crc = 1;
        } else if (strcmp(arg, "--context") == 0) {
            opt->want_context = 1;
        } else if (strcmp(arg, "--tick") == 0) {
            const char *v;
            if (need_arg(argc, argv, &i, &v) != 0) return -1;
            errno = 0;
            char *endp = NULL;
            unsigned long long n = strtoull(v, &endp, 10);
            if (errno != 0 || endp == v || *endp != '\0' || n == 0 || v[0] == '-') {
                log_error("--tick requires a positive integer");
                return -1;
            }
            opt->want_tick = 1;
            opt->tick_frames = n;
        } else if (strcmp(arg, "--state-out") == 0) {
            const char *v;
            if (need_arg(argc, argv, &i, &v) != 0) return -1;
            opt->state_out = v;
        } else if (strcmp(arg, "--keepalive") == 0) {
            const char *v;
            if (need_arg(argc, argv, &i, &v) != 0) return -1;
            errno = 0;
            char *endp = NULL;
            long n = strtol(v, &endp, 10);
            if (errno != 0 || endp == v || *endp != '\0' || n < 0 || n > INT_MAX) {
                log_error("--keepalive requires a non-negative integer");
                return -1;
            }
            opt->keepalive_sec = (int)n;
        } else {
            log_error("unknown option: %s", arg);
            return -1;
        }
    }
    return 0;
}

/* ------------------------------------------------------------------------- */
/* main                                                                      */
/* ------------------------------------------------------------------------- */

int main(int argc, char **argv) {
    install_fatal_signal_handlers();

    Options opt;
    int pr = parse_options(argc, argv, &opt);
    if (pr == 1) {
        return GC_OK;
    }
    if (pr != 0) {
        usage(stderr, argv[0]);
        return GC_ERR_USAGE;
    }

    log_info("gchost %s (skeleton)", GCHOST_VERSION);
    log_info("profile %s (verified build %s)", GCHOST_PROFILE, GCHOST_PROFILE_BUILD);
    log_info("lib-dir=%s", opt.lib_dir);
    log_info("fixture=%s", opt.fixture_dir ? opt.fixture_dir : "(not requested)");
    log_info("databin-dir=%s", opt.databin_dir ? opt.databin_dir : "(not requested)");
    log_info("boundary: private host process; no login, no injection, no game writes");

    GcSession session;
    memset(&session, 0, sizeof(session));
    int rc = load_gamecore(&session, opt.lib_dir);
    if (rc != GC_OK) {
        return rc;
    }
    rc = stage_module_init(&session, opt.allow_unverified_build);
    if (rc != GC_OK) {
        return rc;
    }

    FixtureMeta meta;
    int have_meta = 0;
    if (opt.fixture_dir) {
        log_info("== stage: fixture ==");
        rc = verify_fixture(opt.fixture_dir, opt.expect_replay_id, &meta);
        if (rc != GC_OK) {
            return rc;
        }
        have_meta = 1;
    } else {
        log_info("== stage: fixture == skipped (--fixture not provided)");
    }

    if (opt.databin_dir) {
        rc = databin_build_gate(&meta, have_meta, opt.allow_unverified_build);
        if (rc != GC_OK) {
            return rc;
        }
        rc = stage_register_databin(&session, opt.databin_dir, opt.verify,
                                    opt.keep_databin_crc);
        if (rc != GC_OK) {
            return rc;
        }
    } else {
        log_info("== stage: databin == skipped (--databin-dir not provided)");
    }

    int unimplemented = 0;
    if (opt.want_context) {
        if (stage_context_init_stub() == GC_ERR_UNIMPLEMENTED) {
            unimplemented = 1;
        }
    }
    if (opt.want_tick) {
        log_info("requested tick frames: %llu", opt.tick_frames);
        if (stage_frame_tick_stub() == GC_ERR_UNIMPLEMENTED) {
            unimplemented = 1;
        }
    }
    if (opt.state_out) {
        log_info("requested state output: %s", opt.state_out);
        if (stage_state_output_stub() == GC_ERR_UNIMPLEMENTED) {
            unimplemented = 1;
        }
    }

    if (opt.keepalive_sec > 0) {
        log_info("keepalive %d s (pid=%d)", opt.keepalive_sec, (int)getpid());
        sleep((unsigned)opt.keepalive_sec);
    }

    if (unimplemented) {
        log_error("one or more requested stages are UNIMPLEMENTED; "
                  "see docs/host_harness.md");
        return GC_ERR_UNIMPLEMENTED;
    }
    log_info("implemented stages completed OK");
    return GC_OK;
}
