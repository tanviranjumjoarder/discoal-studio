/* win_compat.h -- lets discoal build with MinGW-w64 on Windows (added by discoal Studio).
 *
 * discoal maps its sweep-trajectory temp file with mmap(). Windows has no mmap(), so
 * here the "mapping" reads the whole file into memory instead (the file is only read).
 * On macOS/Linux this header just includes <sys/mman.h>; nothing changes there.
 */
#ifndef DISCOAL_WIN_COMPAT_H
#define DISCOAL_WIN_COMPAT_H

#include <fcntl.h>

#ifdef _WIN32
#include <io.h>
#include <process.h>
#include <stdio.h>
#include <stdlib.h>

#define PROT_READ 1
#define MAP_PRIVATE 2
#define MAP_FAILED ((void *)-1)

static inline void *mmap(void *addr, size_t len, int prot, int flags, int fd, long off) {
	(void)addr; (void)prot; (void)flags;
	char *buf = (char *)malloc(len ? len : 1);
	size_t got = 0;
	if (!buf) return MAP_FAILED;
	if (_lseek(fd, off, SEEK_SET) < 0) { free(buf); return MAP_FAILED; }
	while (got < len) {
		size_t want = len - got;
		int n = _read(fd, buf + got, (unsigned)(want > (1u << 30) ? (1u << 30) : want));
		if (n <= 0) { free(buf); return MAP_FAILED; }
		got += (size_t)n;
	}
	return buf;
}

static inline int munmap(void *addr, size_t len) {
	(void)len;
	free(addr);
	return 0;
}

/* Temp files go to %TEMP% instead of /tmp. */
static inline const char *discoal_tmpdir(void) {
	const char *t = getenv("TEMP");
	if (!t) t = getenv("TMP");
	return t ? t : ".";
}

/* stdout in binary mode, so .ms files get \n line endings exactly as on macOS/Linux. */
#define DISCOAL_BINARY_STDOUT() _setmode(_fileno(stdout), _O_BINARY)

#else /* POSIX */
#include <sys/mman.h>
static inline const char *discoal_tmpdir(void) { return "/tmp"; }
#define DISCOAL_BINARY_STDOUT() ((void)0)
#endif

#ifndef O_BINARY
#define O_BINARY 0
#endif

#endif
