#ifndef NDX_EVIDENCE_H
#define NDX_EVIDENCE_H
/* Linux evidence destinations. Never replace or unlink an existing entry.
 * Call once before producer effects, with a zero-initialized output array.
 * A reservation race/error may leave new empty files: retain them as evidence,
 * close our handles and refuse; use a fresh namespace for a later attempt. */
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

struct ndx_evidence_file { const char *path; FILE *stream; };

static inline int ndx_evidence_close(struct ndx_evidence_file *files, size_t count)
{
   int failed = 0;
   for (size_t i = 0; i < count; i++) {
      if (!files[i].stream) continue;
      if (ferror(files[i].stream)) failed = 1;
      if (fclose(files[i].stream)) failed = 1;
      files[i].stream = NULL;
   }
   return failed ? -1 : 0;
}

static inline int ndx_evidence_reserve(struct ndx_evidence_file *files, size_t count)
{
   struct target { int dir; char *storage; char *name; struct stat parent; } t[16];
   if (!files || !count || count > 16) { errno = EINVAL; return -1; }
   for (size_t i = 0; i < count; i++) {
      if (!files[i].path || !*files[i].path || files[i].stream) {
         errno = EINVAL; return -1;
      }
   }
   memset(t, 0, sizeof(t));
   for (size_t i = 0; i < count; i++) t[i].dir = -1;
   int result = -1, saved = EINVAL;
   /* Validate every name and existing entry before creating the first file.
    * Open parent directories anchor aliases and avoid re-resolving them when
    * reserving outputs. Final-component symlinks (even dangling) are refused. */
   for (size_t i = 0; i < count; i++) {
      t[i].storage = strdup(files[i].path);
      if (!t[i].storage) { saved = errno; goto done; }
      char *slash = strrchr(t[i].storage, '/');
      const char *parent = ".";
      t[i].name = t[i].storage;
      if (slash) {
         *slash = 0; t[i].name = slash + 1;
         parent = slash == t[i].storage ? "/" : t[i].storage;
      }
      if (!*t[i].name || !strcmp(t[i].name, ".") || !strcmp(t[i].name, "..")) goto done;
      t[i].dir = open(parent, O_RDONLY | O_DIRECTORY | O_CLOEXEC);
      if (t[i].dir < 0 || fstat(t[i].dir, &t[i].parent)) { saved = errno; goto done; }
      for (size_t j = 0; j < i; j++) {
         if (t[i].parent.st_dev == t[j].parent.st_dev &&
             t[i].parent.st_ino == t[j].parent.st_ino && !strcmp(t[i].name, t[j].name)) {
            saved = EEXIST; goto done;
         }
      }
      struct stat existing;
      if (!fstatat(t[i].dir, t[i].name, &existing, AT_SYMLINK_NOFOLLOW)) {
         saved = EEXIST; goto done;
      }
      if (errno != ENOENT) { saved = errno; goto done; }
   }
   for (size_t i = 0; i < count; i++) {
      int fd = openat(t[i].dir, t[i].name, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
      if (fd < 0) { saved = errno; goto done; }
      files[i].stream = fdopen(fd, "wb");
      if (!files[i].stream) { saved = errno; close(fd); goto done; }
   }
   result = 0;
done:
   for (size_t i = 0; i < count; i++) {
      if (t[i].dir >= 0) close(t[i].dir);
      free(t[i].storage);
   }
   if (result) ndx_evidence_close(files, count);
   errno = saved;
   return result;
}

static inline int ndx_evidence_write(FILE *f, const void *bytes, size_t size)
{
   if (!f) { errno = EINVAL; return -1; }
   if (fwrite(bytes, 1, size, f) != size || fflush(f) || fsync(fileno(f))) return -1;
   return 0;
}
#endif
