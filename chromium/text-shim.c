// LD_PRELOAD shim for Chromium-family apps (browsers, Electron, CEF, AppImages):
//  - adds --text-contrast/--text-gamma to a browser's own command line (browser UI, see
//    __libc_start_main) and injects them into renderers (Chromium does not forward these
//    Skia switches to renderers), via both the zygote fork socket and no-zygote exec*.
//  - sets FONTCONFIG_FILE to ~/.config/fontlab/chromium-fonts.conf (when present and not
//    already set), so CSS system-ui and Windows web fonts work even when an app is launched
//    from a keybind, a terminal or the app launcher. Only the Chromium process that loaded
//    the shim reads it: every exec*/posix_spawn from it drops the variable again, so a
//    terminal, editor or helper the app starts keeps the desktop's own fontconfig.
// Safe to load session-wide via LD_PRELOAD: non-Chromium processes exit shim_init() after
// a single access() check and hit a one-branch fast path in every hooked call. All real_*
// symbols are resolved in shim_init() so forked children never call dlsym(). REAL() still
// resolves one on first use, because constructors of the program's own libraries run
// before shim_init() and may spawn or exec (fork() comes later, when all are set).
//  - with LCD_FILTER=box, swaps Skia's subpixel (LCD) filter table for a 1-pixel box, in
//    memory, in every Chromium process (see patch_lcd_filter), and stays in LD_PRELOAD so
//    zygote, GPU and utility processes load it too.
// Values: ~/.config/fontlab/chromium-text.conf (CONTRAST=.. GAMMA=.. [LCD_FILTER=box]), written by fontlab,
// or the file in $FONTLAB_TEXT_CONF (the preset comparison window). Missing file = no change.
// Fork message (base::Pickle): u32 payload_size | i32 cmd | str process_type | i32 argc | argc x str | rest
// str = i32 len + bytes, padded to 4.
#define _GNU_SOURCE
#include <dlfcn.h>
#include <link.h>
#include <spawn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <unistd.h>

static ssize_t (*real_sendmsg)(int, const struct msghdr *, int);
static int (*real_execve)(const char *, char *const[], char *const[]);
static int (*real_execv)(const char *, char *const[]);
static int (*real_execvp)(const char *, char *const[]);
static int (*real_execvpe)(const char *, char *const[], char *const[]);
static int (*real_posix_spawn)(pid_t *, const char *, const posix_spawn_file_actions_t *,
                               const posix_spawnattr_t *, char *const[], char *const[]);
static int (*real_posix_spawnp)(pid_t *, const char *, const posix_spawn_file_actions_t *,
                                const posix_spawnattr_t *, char *const[], char *const[]);
typedef int (*main_fn)(int, char **, char **);
typedef int (*start_fn)(main_fn, int, char **, void (*)(void), void (*)(void), void (*)(void), void *);
static start_fn real_start;
#define REAL(name) ({ \
  if (!real_##name) real_##name = (__typeof__(real_##name))dlsym(RTLD_NEXT, #name); \
  real_##name; })
static char extra[2][64];
static int have_extra = 0;
static int is_chromium = 0;
static int is_browser = 0;   // a web browser (BROWSER_EXES), not an Electron or CEF app
static int lcd_box = 0;
static char fc_env[600];   // "FONTCONFIG_FILE=<path>" when the shim set it, else empty

static void load_conf(void) {
  have_extra = 0;
  char path[512], line[128], c[32] = "", g[32] = "", lf[16] = "";
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
    sscanf(line, "LCD_FILTER=%15[a-z]", lf);
  }
  fclose(f);
  lcd_box = !strcmp(lf, "box");
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
  if (n > 0 && (size_t)n < sizeof path && access(path, R_OK) == 0 &&
      setenv("FONTCONFIG_FILE", path, 0) == 0) {
    snprintf(fc_env, sizeof fc_env, "FONTCONFIG_FILE=%s", path);
  }
}

// ---- Skia LCD filter ----
// Skia renders subpixel glyphs from outlines (Chromium uses Fontations, so all of them)
// with pack4xHToMask() in SkScalerContext.cpp: 4 samples per pixel, then a 12-tap FIR per
// colour channel from a compiled-in uint32[36] table (a Gaussian, sigma 5/3 sample). That
// is wider than ClearType, so text looks soft. No flag reaches it, so the shim finds the
// table by content in the read-only segments of the main executable (Chromium, Electron)
// and of libcef.so / libelectron*.so (CEF apps such as Spotify), and overwrites it in this
// process only (copy-on-write page). Renderers forked from the zygote inherit the patched
// page. Exactly one hit is required; anything else (another Skia, already patched) changes
// nothing. Measurements: docs/research/experiments.md, Experiment 5.
static const uint32_t LCD_STOCK[36] = {
  3, 11, 28, 51, 64, 57, 36, 16, 5, 1, 0, 0,
  0, 2, 8, 22, 43, 61, 61, 43, 22, 8, 2, 0,
  0, 0, 1, 5, 16, 36, 57, 64, 51, 28, 11, 3};
// Each channel averages the 4 samples of a 1-pixel window centred on its subpixel; every
// row sums to 0x110 like the stock rows, so overall ink stays the same.
static const uint32_t LCD_BOX[36] = {
  0, 0, 23, 68, 68, 68, 45, 0, 0, 0, 0, 0,
  0, 0, 0, 0, 68, 68, 68, 68, 0, 0, 0, 0,
  0, 0, 0, 0, 0, 45, 68, 68, 68, 23, 0, 0};

struct lcd_scan { uint32_t *hit; int hits; };

static int skia_object(const char *name) {
  if (!name || !*name) return 1;   // the main executable
  const char *b = strrchr(name, '/');
  b = b ? b + 1 : name;
  return !strncmp(b, "libcef.so", 9) || !strncmp(b, "libelectron", 11);
}

static int scan_object(struct dl_phdr_info *info, size_t size, void *data) {
  (void)size;
  struct lcd_scan *s = data;
  if (!skia_object(info->dlpi_name)) return 0;
  for (int i = 0; i < info->dlpi_phnum; i++) {
    const ElfW(Phdr) *ph = &info->dlpi_phdr[i];
    if (ph->p_type != PT_LOAD || ph->p_flags != PF_R || ph->p_filesz < sizeof LCD_STOCK) continue;
    uintptr_t start = (info->dlpi_addr + ph->p_vaddr + 3) & ~(uintptr_t)3;
    uintptr_t end = info->dlpi_addr + ph->p_vaddr + ph->p_filesz - sizeof LCD_STOCK;
    for (const uint32_t *w = (const uint32_t *)start; (uintptr_t)w <= end; w++) {
      if (w[0] == 3 && w[1] == 11 && w[2] == 28 && !memcmp(w, LCD_STOCK, sizeof LCD_STOCK)) {
        s->hit = (uint32_t *)w;
        s->hits++;
      }
    }
  }
  return 0;
}

static void patch_lcd_filter(void) {
  struct lcd_scan s = {0, 0};
  dl_iterate_phdr(scan_object, &s);
  if (s.hits != 1) return;
  long pg = sysconf(_SC_PAGESIZE);
  if (pg <= 0) return;
  uintptr_t a = (uintptr_t)s.hit & ~(uintptr_t)(pg - 1);
  uintptr_t e = ((uintptr_t)s.hit + sizeof LCD_BOX + (uintptr_t)pg - 1) & ~(uintptr_t)(pg - 1);
  if (mprotect((void *)a, e - a, PROT_READ | PROT_WRITE)) return;
  memcpy(s.hit, LCD_BOX, sizeof LCD_BOX);
  mprotect((void *)a, e - a, PROT_READ);
}

// The login session preloads this .so into every process (~/.config/uwsm/env and
// systemd --user, written by fontlab); launch scripts and AppImage runtimes pass it on. The first Chromium binary (its folder holds icudtl.dat) keeps
// the hook, sets FONTCONFIG_FILE if needed, and drops the .so from LD_PRELOAD, so zygote,
// GPU, renderers and anything the app opens (a terminal inside an editor, say) do not load it.
// With LCD_FILTER=box it stays: each Chromium process patches its own copy of the filter
// (and sets FONTCONFIG_FILE again for itself, since child_env() drops it).
static int file_in_dir(const char *dir, const char *name) {
  char p[1024];
  snprintf(p, sizeof p, "%s/%s", dir, name);
  return access(p, F_OK) == 0;
}

// Executable names of browsers whose own process gets --text-contrast/--text-gamma (the
// browser UI: tabs, menus, omnibox). Electron and CEF apps draw everything in renderers,
// and some read unknown arguments as files to open, so their command line is left alone.
static const char *const BROWSER_EXES[] = {"chrome", "chromium", "brave", "vivaldi-bin", "msedge", 0};

__attribute__((constructor)) static void shim_init(void) {
  // Resolve all wrapped libc functions up front (single-threaded) so forked children never
  // call dlsym() between fork() and exec*().
  real_sendmsg = dlsym(RTLD_NEXT, "sendmsg");
  real_execve = dlsym(RTLD_NEXT, "execve");
  real_execv = dlsym(RTLD_NEXT, "execv");
  real_execvp = dlsym(RTLD_NEXT, "execvp");
  real_execvpe = dlsym(RTLD_NEXT, "execvpe");
  real_posix_spawn = dlsym(RTLD_NEXT, "posix_spawn");
  real_posix_spawnp = dlsym(RTLD_NEXT, "posix_spawnp");
  real_start = (start_fn)dlsym(RTLD_NEXT, "__libc_start_main");

  char exe[512];
  ssize_t n = readlink("/proc/self/exe", exe, sizeof exe - 1);
  if (n <= 0) return;
  exe[n] = 0;
  char *slash = strrchr(exe, '/');
  if (!slash) return;
  for (int i = 0; BROWSER_EXES[i]; i++)
    if (!strcmp(slash + 1, BROWSER_EXES[i])) is_browser = 1;
  *slash = 0;
  int chromium = file_in_dir(exe, "icudtl.dat") &&
                 (file_in_dir(exe, "resources.pak") || file_in_dir(exe, "v8_context_snapshot.bin"));
  if (!chromium) return;
  is_chromium = 1;
  load_conf();   // now, not after fork: fopen allocates, a forked child must not
  load_fontconfig();
  if (lcd_box) {
    patch_lcd_filter();
    return;
  }
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

// ---- browser process: add the flags to its own command line ----
// Chromium reads its switches from main()'s argv, so the shim hands main() a longer one.
// ld.so runs shim_init() before the executable's _start calls this, so the config is loaded.
// Only the browser process itself (no --type=) of a BROWSER_EXES binary, and only once.
int __libc_start_main(main_fn main, int argc, char **argv, void (*init)(void), void (*fini)(void),
                      void (*rtld_fini)(void), void *stack_end) {
  if (!real_start) real_start = (start_fn)dlsym(RTLD_NEXT, "__libc_start_main");
  if (!real_start) _exit(127);
  if (!is_browser || !have_extra || !argv || argc < 1)
    return real_start(main, argc, argv, init, fini, rtld_fini, stack_end);
  int at = argc;   // before a "--", after which Chromium reads no switches
  for (int i = 1; i < argc; i++) {
    if (!strncmp(argv[i], "--type=", 7) || !strncmp(argv[i], "--text-contrast", 15))
      return real_start(main, argc, argv, init, fini, rtld_fini, stack_end);
    if (!strcmp(argv[i], "--") && at == argc) at = i;
  }
  char **out = malloc(sizeof *out * (size_t)(argc + 3));
  if (!out) return real_start(main, argc, argv, init, fini, rtld_fini, stack_end);
  int n = 0;
  for (int i = 0; i < at; i++) out[n++] = argv[i];
  out[n++] = extra[0];
  out[n++] = extra[1];
  for (int i = at; i < argc; i++) out[n++] = argv[i];
  out[n] = NULL;
  return real_start(main, n, out, init, fini, rtld_fini, stack_end);
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
  if (!is_chromium || !have_extra || !m || m->msg_iovlen != 1 || m->msg_iov[0].iov_len < 32)
    return REAL(sendmsg)(fd, m, flags);
  const uint8_t *b = m->msg_iov[0].iov_base;
  size_t len = m->msg_iov[0].iov_len;
  uint32_t payload; memcpy(&payload, b, 4);
  if ((size_t)payload + 4 != len) return REAL(sendmsg)(fd, m, flags);
  const char *pt; int32_t ptlen;
  size_t off = skip_str(b, len, 8, &pt, &ptlen);  // after header + cmd
  if (!off || ptlen != 8 || memcmp(pt, "renderer", 8)) return REAL(sendmsg)(fd, m, flags);
  if (off + 4 > len) return REAL(sendmsg)(fd, m, flags);
  int32_t argc; memcpy(&argc, b + off, 4);
  if (argc < 1 || argc > 4096) return REAL(sendmsg)(fd, m, flags);
  size_t argc_off = off, p = off + 4;
  for (int32_t i = 0; i < argc; i++) {
    const char *s; int32_t n;
    p = skip_str(b, len, p, &s, &n);
    if (!p) return REAL(sendmsg)(fd, m, flags);
    if (n > 15 && !memcmp(s, "--text-contrast", 15)) return REAL(sendmsg)(fd, m, flags);
  }
  size_t add = 4 + pad4(strlen(extra[0])) + 4 + pad4(strlen(extra[1]));
  uint8_t *o = malloc(len + add);
  if (!o) return REAL(sendmsg)(fd, m, flags);
  memcpy(o, b, p);
  size_t q = p;
  q += put_str(o + q, extra[0]);
  q += put_str(o + q, extra[1]);
  memcpy(o + q, b + p, len - p);
  uint32_t np = payload + (uint32_t)add; memcpy(o, &np, 4);
  int32_t nargc = argc + 2; memcpy(o + argc_off, &nargc, 4);
  struct iovec iov = { o, len + add };
  struct msghdr mm = *m; mm.msg_iov = &iov; mm.msg_iovlen = 1;
  ssize_t r = REAL(sendmsg)(fd, &mm, flags);
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

// FONTCONFIG_FILE as set by load_fontconfig() is for this process only. Renderers get
// fonts from the browser process over IPC, so no child needs it, and children that are not
// Chromium (a shell in an editor, xdg-open, a helper) must keep the desktop fontconfig.
// Also runs between fork and exec: the copy lives on the stack. A value the user set
// themselves (fc_env empty) is passed on untouched.
#define MAX_ENV 2048

static char *const *child_env(char *const envp[], char *out[]) {
  if (!*fc_env || !envp) return envp;
  int n = 0, dropped = 0;
  for (int i = 0; envp[i]; i++) {
    if (!strcmp(envp[i], fc_env)) { dropped = 1; continue; }
    if (n >= MAX_ENV - 1) return envp;
    out[n++] = envp[i];
  }
  out[n] = NULL;
  return dropped ? out : envp;
}

static char *const *child_argv(char *const argv[], char *out[]) {
  if (!needs_flags(argv)) return argv;
  with_flags(argv, out);
  return out;
}

int execve(const char *path, char *const argv[], char *const envp[]) {
  char *a[MAX_ARGS], *e[MAX_ENV];
  return REAL(execve)(path, child_argv(argv, a), child_env(envp, e));
}

int execv(const char *path, char *const argv[]) {
  char *a[MAX_ARGS], *e[MAX_ENV];
  char *const *env = child_env(environ, e);
  if (env != environ) return REAL(execve)(path, child_argv(argv, a), env);
  return REAL(execv)(path, child_argv(argv, a));
}

int execvp(const char *file, char *const argv[]) {
  char *a[MAX_ARGS], *e[MAX_ENV];
  char *const *env = child_env(environ, e);
  if (env != environ && REAL(execvpe)) return REAL(execvpe)(file, child_argv(argv, a), env);
  return REAL(execvp)(file, child_argv(argv, a));
}

int execvpe(const char *file, char *const argv[], char *const envp[]) {
  char *a[MAX_ARGS], *e[MAX_ENV];
  return REAL(execvpe)(file, child_argv(argv, a), child_env(envp, e));
}

int posix_spawn(pid_t *pid, const char *path, const posix_spawn_file_actions_t *fa,
                const posix_spawnattr_t *at, char *const argv[], char *const envp[]) {
  char *a[MAX_ARGS], *e[MAX_ENV];
  return REAL(posix_spawn)(pid, path, fa, at, child_argv(argv, a), child_env(envp, e));
}

int posix_spawnp(pid_t *pid, const char *file, const posix_spawn_file_actions_t *fa,
                 const posix_spawnattr_t *at, char *const argv[], char *const envp[]) {
  char *a[MAX_ARGS], *e[MAX_ENV];
  return REAL(posix_spawnp)(pid, file, fa, at, child_argv(argv, a), child_env(envp, e));
}
