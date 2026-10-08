/*
 *  Socket portability layer for the remote debug servers (GDB, QMP).
 *
 *  POSIX sockets are plain file descriptors; Winsock sockets are not. The
 *  differences that matter here are: closesocket() instead of close(),
 *  ioctlsocket() instead of fcntl(), recv()/send() instead of read()/write(),
 *  WSAGetLastError() instead of errno, no SO_REUSEPORT, and a mandatory
 *  WSAStartup(). Everything the servers need is wrapped below so the protocol
 *  code stays free of #ifdefs.
 *
 *  Sockets are held as rd_sock_t (a signed integer wide enough for a Winsock
 *  SOCKET) with RD_BAD_SOCK (-1) meaning "none", which keeps the existing
 *  "fd >= 0" / "fd == -1" idiom working on both platforms.
 */

#ifndef DOSBOX_RDSOCK_H
#define DOSBOX_RDSOCK_H

#include <cstddef>
#include <cstdint>
#include <cerrno>
#include <cstring>

#ifdef WIN32
typedef intptr_t rd_sock_t;
typedef int rd_ssize_t;
#else
# include <sys/types.h>
typedef int rd_sock_t;
typedef ssize_t rd_ssize_t;
#endif

#define RD_BAD_SOCK ((rd_sock_t)-1)

/* Everything above is all the class headers need. The helpers below pull in
 * the system socket headers, which on Windows means winsock2.h -- and that
 * cannot be included after windows.h (it conflicts with winsock.h). So only
 * the two .cpp files that do socket I/O define RDSOCK_IMPL, and they do it
 * before including dosbox.h. */
#ifdef RDSOCK_IMPL

#ifdef WIN32
# ifndef WIN32_LEAN_AND_MEAN
#  define WIN32_LEAN_AND_MEAN
# endif
# include <winsock2.h>
# include <ws2tcpip.h>
#else
# include <sys/socket.h>
# include <netinet/in.h>
# include <netinet/tcp.h>
# include <arpa/inet.h>
# include <unistd.h>
# include <fcntl.h>
#endif

/* One-time network stack init. A no-op off Windows. Safe to call repeatedly. */
static inline bool rd_net_init() {
#ifdef WIN32
    /* A function-local static is initialised exactly once, thread-safely. The
     * stack is left up until the process exits. */
    static const bool ok = []() {
        WSADATA wsa;
        return WSAStartup(MAKEWORD(2, 2), &wsa) == 0;
    }();
    return ok;
#else
    return true;
#endif
}

static inline int rd_last_error() {
#ifdef WIN32
    return WSAGetLastError();
#else
    return errno;
#endif
}

static inline const char* rd_error_string(int err) {
#ifdef WIN32
    static thread_local char buf[160];
    buf[0] = 0;
    FormatMessageA(FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS, NULL,
                   (DWORD)err, 0, buf, (DWORD)sizeof(buf), NULL);
    /* FormatMessage ends messages with CR LF; trim so log lines stay on one line. */
    for (size_t n = 0; buf[n]; n++) if (buf[n] == '\r' || buf[n] == '\n') { buf[n] = 0; break; }
    return buf;
#else
    return strerror(err);
#endif
}

/* True when a non-blocking call failed only because it would have blocked.
 * EAGAIN and EWOULDBLOCK are the same value on Linux, so testing both with ||
 * trips -Wlogical-op; test them separately. */
static inline bool rd_would_block(int err) {
#ifdef WIN32
    return err == WSAEWOULDBLOCK;
#else
    if (err == EAGAIN) return true;
# if EWOULDBLOCK != EAGAIN
    if (err == EWOULDBLOCK) return true;
# endif
    return false;
#endif
}

static inline rd_sock_t rd_socket() {
#ifdef WIN32
    SOCKET s = socket(AF_INET, SOCK_STREAM, 0);
    return s == INVALID_SOCKET ? RD_BAD_SOCK : (rd_sock_t)s;
#else
    return socket(AF_INET, SOCK_STREAM, 0);
#endif
}

static inline rd_sock_t rd_accept(rd_sock_t s, struct sockaddr* addr, socklen_t* len) {
#ifdef WIN32
    SOCKET c = accept((SOCKET)s, addr, len);
    return c == INVALID_SOCKET ? RD_BAD_SOCK : (rd_sock_t)c;
#else
    return accept(s, addr, len);
#endif
}

static inline void rd_close(rd_sock_t s) {
#ifdef WIN32
    closesocket((SOCKET)s);
#else
    close(s);
#endif
}

/* Unblock a thread parked in accept()/recv() on this socket. */
static inline void rd_shutdown(rd_sock_t s) {
#ifdef WIN32
    shutdown((SOCKET)s, SD_BOTH);
#else
    shutdown(s, SHUT_RDWR);
#endif
}

static inline bool rd_set_nonblocking(rd_sock_t s) {
#ifdef WIN32
    u_long on = 1;
    return ioctlsocket((SOCKET)s, FIONBIO, &on) == 0;
#else
    int flags = fcntl(s, F_GETFL, 0);
    if (flags < 0) return false;
    return fcntl(s, F_SETFL, flags | O_NONBLOCK) == 0;
#endif
}

/* Reuse options for the listening socket, so a restart can rebind a port that
 * is still in TIME_WAIT. On POSIX these are SO_REUSEADDR and, where it exists,
 * SO_REUSEPORT, set one at a time: they are separate option numbers, and
 * OR-ing them into a single value happens to name SO_REUSEPORT on Linux but an
 * invalid option on macOS ("Protocol not available"). Windows is different:
 * SO_REUSEADDR there lets another process bind the same port and steal
 * connections, and rebinding past TIME_WAIT is already allowed, so ask for
 * exclusive use of the address instead. */
static inline bool rd_set_reuse(rd_sock_t s) {
    int on = 1;
#ifdef WIN32
    return setsockopt((SOCKET)s, SOL_SOCKET, SO_EXCLUSIVEADDRUSE, (const char*)&on, sizeof(on)) == 0;
#else
    if (setsockopt(s, SOL_SOCKET, SO_REUSEADDR, &on, sizeof(on)) < 0) return false;
# ifdef SO_REUSEPORT
    if (setsockopt(s, SOL_SOCKET, SO_REUSEPORT, &on, sizeof(on)) < 0) return false;
# endif
    return true;
#endif
}

static inline void rd_set_nodelay(rd_sock_t s) {
    int on = 1;
#ifdef WIN32
    setsockopt((SOCKET)s, IPPROTO_TCP, TCP_NODELAY, (const char*)&on, sizeof(on));
#else
    setsockopt(s, IPPROTO_TCP, TCP_NODELAY, &on, sizeof(on));
#endif
}

static inline rd_ssize_t rd_recv(rd_sock_t s, void* buf, size_t len) {
#ifdef WIN32
    return recv((SOCKET)s, (char*)buf, (int)len, 0);
#else
    return recv(s, buf, len, 0);
#endif
}

static inline rd_ssize_t rd_send(rd_sock_t s, const void* buf, size_t len) {
#ifdef WIN32
    return send((SOCKET)s, (const char*)buf, (int)len, 0);
#else
    return send(s, buf, len, 0);
#endif
}

#endif /* RDSOCK_IMPL */

#endif /* DOSBOX_RDSOCK_H */
