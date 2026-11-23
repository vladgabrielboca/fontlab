// LD_PRELOAD shim for Chromium/Brave: add --text-contrast/--text-gamma to renderer
// fork requests sent from the browser process to the zygote. Chromium does not
// forward these Skia switches to renderers. Renderers stay zygote-forked and sandboxed.
// Values: ~/.config/fontlab/chromium-text.conf (CONTRAST=.. GAMMA=..), written by fontlab.
// Missing file = no change.
// Fork message (base::Pickle): u32 payload_size | i32 cmd | str process_type | i32 argc | argc x str | rest
// str = i32 len + bytes, padded to 4.
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

static ssize_t (*real_sendmsg)(int, const struct msghdr *, int);
static char extra[2][64];
static int have_extra = -1;

static void load_conf(void) {
  have_extra = 0;
  const char *home = getenv("HOME");
  if (!home) return;
  char path[512], line[128], c[32] = "", g[32] = "";
  snprintf(path, sizeof path, "%s/.config/fontlab/chromium-text.conf", home);
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

// In the real browser binary (/usr/lib/... or /opt/...), drop this .so from LD_PRELOAD
// so zygote, GPU, renderers and anything the browser opens do not load it.
// The launcher (/usr/bin/chromium, or bash for brave-origin) keeps it so it reaches the browser.
__attribute__((constructor)) static void shim_init(void) {
  char exe[512];
  ssize_t n = readlink("/proc/self/exe", exe, sizeof exe - 1);
  if (n <= 0) return;
  exe[n] = 0;
  if (strncmp(exe, "/usr/lib/", 9) && strncmp(exe, "/opt/", 5)) return;
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
  if (!m || m->msg_iovlen != 1 || m->msg_iov[0].iov_len < 32) return real_sendmsg(fd, m, flags);
  const uint8_t *b = m->msg_iov[0].iov_base;
  size_t len = m->msg_iov[0].iov_len;
  uint32_t payload; memcpy(&payload, b, 4);
  if ((size_t)payload + 4 != len) return real_sendmsg(fd, m, flags);
  const char *pt; int32_t ptlen;
  size_t off = skip_str(b, len, 8, &pt, &ptlen);  // after header + cmd
  if (!off || ptlen != 8 || memcmp(pt, "renderer", 8)) return real_sendmsg(fd, m, flags);
  if (have_extra < 0) load_conf();
  if (have_extra != 1 || off + 4 > len) return real_sendmsg(fd, m, flags);
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
