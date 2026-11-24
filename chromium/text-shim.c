// LD_PRELOAD shim for Chromium-family apps (browsers, Electron, CEF, AppImages):
//  - injects --text-contrast/--text-gamma into renderers (Chromium does not forward these
//    Skia switches to renderers), via both the zygote fork socket and no-zygote exec*.
//  - sets FONTCONFIG_FILE to ~/.config/fontlab/chromium-fonts.conf (when present and not
//    already set), so CSS system-ui and Windows web fonts work even when an app is launched
//    from a keybind or terminal instead of a wrapper.
// Safe to load session-wide via LD_PRELOAD: non-Chromium processes exit shim_init() after
// a single access() check and hit a one-branch fast path in every hooked call. All real_*
// symbols are resolved eagerly at load time so forked children never call dlsym().
// Values: ~/.config/fontlab/chromium-text.conf (CONTRAST=.. GAMMA=..), written by fontlab,
// or the file in $FONTLAB_TEXT_CONF (the preset comparison window). Missing file = no change.
// Fork message (base::Pickle): u32 payload_size | i32 cmd | str process_type | i32 argc | argc x str | rest
// str = i32 len + bytes, padded to 4.
#define _GNU_SOURCE
#include <dlfcn.h>
#include <spawn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

static ssize_t (*real_sendmsg)(int, const struct msghdr *, int);
static int (*real_execve)(const char *, char *const[], char *const[]);
static int (*real_execv)(const char *, char *const[]);
static int (*real_execvp)(const char *, char *const[]);
static int (*real_execvpe)(const char *, char *const[], char *const[]);
static int (*real_posix_spawn)(pid_t *, const char *, const posix_spawn_file_actions_t *,
                               const posix_spawnattr_t *, char *const[], char *const[]);
static char extra[2][64];
static int have_extra = 0;
static int is_chromium = 0;

static void load_conf(void) {
  have_extra = 0;
  char path[512], line[128], c[32] = "", g[32] = "";
  const char *own = getenv("FONTLAB_TEXT_CONF");
  const char *home = getenv("HOME");
  if (own && *own) snprintf(path, sizeof path, "%s", own);
  else if (home) snprintf(path, sizeof path, "%s/.config/fontlab/chromium-text.conf", home);
  else return;
  FILE *f = fopen(path, "r");
  if (!f) return;
  while (fgets(line, sizeof line, f)) {
    sscanf(line, "CONTRAST=%31[0-9.]", c);
    sscanf(line, "GAMMA=%31[0-9.]", g);
  }
  fclose(f);
  if (!*c || !*g) return;
  snprintf(extra[0], sizeof extra[0], "--text-contrast=%s", c);
  snprintf(extra[1], sizeof extra[1], "--text-gamma=%s", g);
  have_extra = 1;
}

static void load_fontconfig(void) {
  if (getenv("FONTCONFIG_FILE")) return;
  const char *home = getenv("HOME");
  if (!home || !*home) return;
  char path[512];
  int n = snprintf(path, sizeof path, "%s/.config/fontlab/chromium-fonts.conf", home);
  if (n > 0 && (size_t)n < sizeof path && access(path, R_OK) == 0) {
    setenv("FONTCONFIG_FILE", path, 0);
  }
}

// Launchers (shell scripts, /usr/bin/chromium, AppImage runtimes, session LD_PRELOAD) pass
// this .so on in LD_PRELOAD. The first Chromium binary (its folder holds icudtl.dat) keeps
// the hook, sets FONTCONFIG_FILE if needed, and drops the .so from LD_PRELOAD, so zygote,
// GPU, renderers and anything the app opens (a terminal inside an editor, say) do not load it.
static int file_in_dir(const char *dir, const char *name) {
  char p[1024];
  snprintf(p, sizeof p, "%s/%s", dir, name);
  return access(p, F_OK) == 0;
}

__attribute__((constructor)) static void shim_init(void) {
  // Resolve all wrapped libc functions up front (single-threaded) so forked children never
  // call dlsym() between fork() and exec*().
  real_sendmsg = dlsym(RTLD_NEXT, "sendmsg");
  real_execve = dlsym(RTLD_NEXT, "execve");
  real_execv = dlsym(RTLD_NEXT, "execv");
  real_execvp = dlsym(RTLD_NEXT, "execvp");
  real_execvpe = dlsym(RTLD_NEXT, "execvpe");
  real_posix_spawn = dlsym(RTLD_NEXT, "posix_spawn");

  char exe[512];
  ssize_t n = readlink("/proc/self/exe", exe, sizeof exe - 1);
  if (n <= 0) return;
  exe[n] = 0;
  char *slash = strrchr(exe, '/');
  if (!slash) return;
  *slash = 0;
  int chromium = file_in_dir(exe, "icudtl.dat") &&
                 (file_in_dir(exe, "resources.pak") || file_in_dir(exe, "v8_context_snapshot.bin"));
  if (!chromium) return;
  is_chromium = 1;
  load_conf();   // now, not after fork: fopen allocates, a forked child must not
  load_fontconfig();
  const char *lp = getenv("LD_PRELOAD");
  if (!lp) return;
  char keep[4096] = "", item[1024];
  const char *p = lp;
  while (*p) {
    size_t k = strcspn(p, ": ");
    if (k && k < sizeof item) {
      memcpy(item, p, k); item[k] = 0;
      if (!strstr(item, "fontlab-text-shim.so") && strlen(keep) + k + 2 < sizeof keep) {
        if (*keep) strcat(keep, ":");
        strcat(keep, item);
      }
    }
    p += k; if (*p) p++;
  }
  if (*keep) setenv("LD_PRELOAD", keep, 1); else unsetenv("LD_PRELOAD");
}

static size_t pad4(size_t n) { return (n + 3) & ~(size_t)3; }

// Returns offset just past a pickle string at off, or 0 if malformed.
static size_t skip_str(const uint8_t *b, size_t len, size_t off, const char **s, int32_t *slen) {
  if (off + 4 > len) return 0;
  int32_t n; memcpy(&n, b + off, 4);
  if (n < 0 || off + 4 + pad4((size_t)n) > len) return 0;
  if (s) *s = (const char *)b + off + 4;
  if (slen) *slen = n;
  return off + 4 + pad4((size_t)n);
}

static size_t put_str(uint8_t *o, const char *s) {
  int32_t n = (int32_t)strlen(s);
  memcpy(o, &n, 4);
  memset(o + 4, 0, pad4((size_t)n));
  memcpy(o + 4, s, (size_t)n);
  return 4 + pad4((size_t)n);
}

ssize_t sendmsg(int fd, const struct msghdr *m, int flags) {
  if (!real_sendmsg) real_sendmsg = dlsym(RTLD_NEXT, "sendmsg");
  if (!is_chromium || !have_extra || !m || m->msg_iovlen != 1 || m->msg_iov[0].iov_len < 32)
    return real_sendmsg(fd, m, flags);
  const uint8_t *b = m->msg_iov[0].iov_base;
  size_t len = m->msg_iov[0].iov_len;
  uint32_t payload; memcpy(&payload, b, 4);
  if ((size_t)payload + 4 != len) return real_sendmsg(fd, m, flags);
  const char *pt; int32_t ptlen;
  size_t off = skip_str(b, len, 8, &pt, &ptlen);  // after header + cmd
  if (!off || ptlen != 8 || memcmp(pt, "renderer", 8)) return real_sendmsg(fd, m, flags);
  if (off + 4 > len) return real_sendmsg(fd, m, flags);
  int32_t argc; memcpy(&argc, b + off, 4);
  if (argc < 1 || argc > 4096) return real_sendmsg(fd, m, flags);
  size_t argc_off = off, p = off + 4;
  for (int32_t i = 0; i < argc; i++) {
    const char *s; int32_t n;
    p = skip_str(b, len, p, &s, &n);
    if (!p) return real_sendmsg(fd, m, flags);
    if (n > 15 && !memcmp(s, "--text-contrast", 15)) return real_sendmsg(fd, m, flags);
  }
  size_t add = 4 + pad4(strlen(extra[0])) + 4 + pad4(strlen(extra[1]));
  uint8_t *o = malloc(len + add);
  if (!o) return real_sendmsg(fd, m, flags);
  memcpy(o, b, p);
  size_t q = p;
  q += put_str(o + q, extra[0]);
  q += put_str(o + q, extra[1]);
  memcpy(o + q, b + p, len - p);
  uint32_t np = payload + (uint32_t)add; memcpy(o, &np, 4);
  int32_t nargc = argc + 2; memcpy(o + argc_off, &nargc, 4);
  struct iovec iov = { o, len + add };
  struct msghdr mm = *m; mm.msg_iov = &iov; mm.msg_iovlen = 1;
  ssize_t r = real_sendmsg(fd, &mm, flags);
  free(o);
  if (r == (ssize_t)(len + add)) return (ssize_t)len;
  return r < 0 ? r : -1;
}

// ---- no-zygote path: renderers exec'd straight from the browser process ----
// Runs in the forked child between fork and exec, so no allocation: argv is copied to the stack.

#define MAX_ARGS 1024

static int needs_flags(char *const argv[]) {
  if (!is_chromium || !have_extra || !argv) return 0;
  int renderer = 0;
  for (int i = 0; argv[i]; i++) {
    if (i >= MAX_ARGS - 3) return 0;
    if (!strcmp(argv[i], "--type=renderer")) renderer = 1;
    if (!strncmp(argv[i], "--text-contrast", 15)) return 0;
  }
  return renderer;
}

static void with_flags(char *const argv[], char *out[]) {
  int n = 0;
  for (; argv[n]; n++) out[n] = argv[n];
  out[n++] = extra[0];
  out[n++] = extra[1];
  out[n] = NULL;
}

#define ENSURE(name) \
  if (!real_##name) real_##name = (__typeof__(name) *)dlsym(RTLD_NEXT, #name)

int execve(const char *path, char *const argv[], char *const envp[]) {
  ENSURE(execve);
  if (!needs_flags(argv)) return real_execve(path, argv, envp);
  char *a[MAX_ARGS]; with_flags(argv, a);
  return real_execve(path, a, envp);
}

int execv(const char *path, char *const argv[]) {
  ENSURE(execv);
  if (!needs_flags(argv)) return real_execv(path, argv);
  char *a[MAX_ARGS]; with_flags(argv, a);
  return real_execv(path, a);
}

int execvp(const char *file, char *const argv[]) {
  ENSURE(execvp);
  if (!needs_flags(argv)) return real_execvp(file, argv);
  char *a[MAX_ARGS]; with_flags(argv, a);
  return real_execvp(file, a);
}

int execvpe(const char *file, char *const argv[], char *const envp[]) {
  ENSURE(execvpe);
  if (!needs_flags(argv)) return real_execvpe(file, argv, envp);
  char *a[MAX_ARGS]; with_flags(argv, a);
  return real_execvpe(file, a, envp);
}

int posix_spawn(pid_t *pid, const char *path, const posix_spawn_file_actions_t *fa,
                const posix_spawnattr_t *at, char *const argv[], char *const envp[]) {
  ENSURE(posix_spawn);
  if (!needs_flags(argv)) return real_posix_spawn(pid, path, fa, at, argv, envp);
  char *a[MAX_ARGS]; with_flags(argv, a);
  return real_posix_spawn(pid, path, fa, at, a, envp);
}
