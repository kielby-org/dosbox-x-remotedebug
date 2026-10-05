# Upstream PR draft: GDB and QMP servers for remote debugging

Branch: `upstream-pr/remote-debug`, 4 commits on top of upstream master
`6c4a364be`, head `1b3f91da2`. Not pushed, not opened. This file is working
notes plus the proposed PR body; it is deliberately not part of the branch
being proposed.

That branch has since been deleted; its fixes (GPL header, the stack VLA,
the warning fixes) are on `remotedebug`. The PR body below is kept for reuse.

    af12e43cf  build: add a --enable-remotedebug configure option
    c4d23e9c9  feat(debug): add GDB and QMP servers for remote debugging
    503ec8a40  test: add a conformance suite for the GDB and QMP servers
    1b3f91da2  docs: document the remote debugging servers

---

## Proposed PR title

`Add opt-in GDB and QMP servers for remote debugging (--enable-remotedebug)`

## Proposed PR body

### What this is

Two TCP servers that let an external process drive a running DOSBox-X guest.
Both are compiled only under a new `--enable-remotedebug` configure option and
both are off unless switched on in the config file or from the Debug menu.

**GDB server** (default port 2159) speaks the GDB remote serial protocol, so a
stock `gdb` can attach to the guest:

```
(gdb) set architecture i8086
(gdb) target remote localhost:2159
```

It implements `g`/`G`/`p`/`P` (registers), `m`/`M` (memory), `Z0`/`z0`
(execution breakpoints), `s`/`c`, `?`, `D`, `qSupported` and
`QStartNoAckMode`. Register 8 is EIP, an offset within CS, as the protocol
specifies; addresses in `m`, `M`, `Z0` and `z0` are linear.

**QMP server** (default port 4444) speaks a subset of the QEMU Monitor
Protocol, for the things a debugger protocol has no vocabulary for:
`query-status`, `input-send-event` (keyboard and mouse), `memdump`,
`screendump`, `savestate`/`loadstate`, `stop`/`cont`, `system_reset`, and
`debug-break-on-exec`, which stops the guest at the entry point of the next
program DOS loads.

### Why it belongs in DOSBox-X rather than in a fork

The value is in the emulator, not in the client. Reverse engineering and
regression-testing DOS software both want the same three things — stop the
guest at a known point, read its state, and drive input reproducibly — and
today the only way to get them from DOSBox-X is the interactive curses
debugger, which needs a human at a keyboard. Everything here is a thin
protocol surface over primitives the internal debugger already has: 2154
lines of new server code, 834 added and 11 removed across fifteen existing
files, and 3215 lines of tests and documentation.

Both protocols are ones that already exist and that tools already speak. The
GDB stub works with real `gdb`, with any GDB frontend, and with the many
languages that have an RSP client. QMP is the protocol QEMU already exposes
for exactly this purpose. Neither invents a DOSBox-X-specific wire format
that upstream would then own.

Upstream now also carries the JSON-RPC debugger agent from #6512. That one is
Windows-only over a named pipe with its own protocol; this is POSIX-only over
TCP with two standard ones. They overlap in what they can do and not at all in
where they run or what talks to them. If the project would rather converge on
one mechanism, that is a fair thing to say up front, and this can be
withdrawn — but see "Interaction with the agent bridge" below, because there
is a bug worth knowing about either way.

### What it costs to maintain

Honestly:

- **Off by default and not compiled at all by default.** `--enable-remotedebug`
  is a separate opt-in that also requires `--enable-debug`; without it,
  `gdbserver.cpp` and `qmp.cpp` are not added to `libdebug.a` and every hook
  in existing files is inside `#if C_REMOTEDEBUG`. Even when compiled in, the
  `gdbserver` and `qmpserver` config settings default to `false` and no socket
  is opened. Verified: a `--enable-debug=heavy` build without
  `--enable-remotedebug` compiles clean, does not build `gdbserver.o` or
  `qmp.o`, and emits no `gdbserver`/`qmpserver` settings.
- **Four small things are not behind the flag**, because they are useful or
  harmless on their own and gating them would be noisier than not: a `REMOTE`
  entry in `LOG_TYPES`, which adds a `remote=` key to the `[log]` section
  whether or not the servers exist (its default is `normal` only when they
  do, `false` otherwise, so it behaves like every other group in a build
  without the flag); `CPU_ExitHLT()`; four `CAPTURE_*` accessors that
  remember where the last screenshot was written; and a signature change to
  `DEBUG_CheckKeys()` so the key can be supplied by a caller instead of read
  from `getch()`. All are inside `#if C_DEBUG` except the `CAPTURE_*`
  accessors. Happy to gate any of them.
- **The servers do not have their own thread into guest state.** The GDB stub
  is polled from `Normal_Loop` and QMP requests that touch the machine are
  queued and drained at the same point, so no protocol handler reads or writes
  guest memory from another thread. The cost is one non-blocking `accept()`
  per loop iteration while the GDB server is enabled.
- **Platform surface is small.** POSIX sockets only: Linux, the BSDs and
  macOS. `configure` refuses anything else rather than shipping stubs.
- **The tests do not need special hardware or a display.** They run headless
  under `SDL_VIDEODRIVER=dummy` and use only the Python standard library.

### Conformance suite

`tests/integration/` — 103 tests, pytest, standard library only. Run against a
build configured with `--enable-remotedebug`:

```
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python3 -m pytest tests/integration
```

Each test launches its own DOSBox-X on dynamically allocated ports, waits for
the guest to draw something, and tears down its own process group. No test
kills a process it did not spawn, and no test needs an emulator started by
hand.

The clients under `tests/integration/protocol/` frame RSP packets and speak
QMP directly and are deliberately unpleasant to use: no register dataclasses,
no address normalisation, no retries. That is the point. A convenience layer
that quietly fixes up an address or resends a packet hides exactly the class of
bug these tests exist to catch, and every bug listed below was originally
masked by one.

What the suite proves, concretely: that the wire format is what the protocols
say it is (packet framing, checksums, ack mode, the register block layout);
that every QMP command in the dispatch table answers, including its error
replies; that a breakpoint set through `Z0` fires at the address the client
named; that a failed memory read is reported as a failure rather than padded;
that the interactive debugger and the GDB stub cannot both hold the machine;
and that a client can disconnect and reconnect without leaving the stub in a
half-attached state.

### Correctness bugs found and fixed along the way

These were all found by writing the conformance suite against the
implementation, and each is covered by a test:

- **`Z0` and `m` disagreed about what an address is.** `DEBUG_SetBreakpoint()`
  split its argument as a packed far pointer (`seg = addr >> 16`), while `m`
  and `M` took a linear address. Below 0x10000 the two interpretations
  coincide, so it looked correct. Above it, `Z0` answered `OK` and the
  breakpoint never fired — a silent failure, the worst kind. Both now take a
  linear address, and `qSupported` advertises it. Protected-mode addresses are
  refused outright rather than accepted and dropped.
- **A `savestate` issued while stopped at a breakpoint timed out after 30
  seconds.** `Normal_Loop` returned early on the halted path, before the point
  where pending QMP work is drained, so the request was never serviced. The
  drain now also runs on the halted path.
- **A hand-written `E99` reply carried the wrong checksum**, so a strict client
  would reject it.
- **`M` ignored its length field**, writing as many bytes as the payload
  happened to contain, and reported success for writes that had failed.
- **`p` and `G` accepted out-of-range register indices** and read or wrote past
  the register array.
- **`m` reported an unreadable byte as zero**, presenting a fabricated byte as
  guest state. It now stops the reply at the first failure.
- **The stub advertised `swbreak`, `hwbreak` and `vCont;t`, none of which it
  implements**, and QMP advertised an `oob` capability it does not support.
  `query-commands` is now derived from the dispatch table rather than
  hand-maintained alongside it.
- **`TCP_NODELAY` was not set on the accepted sockets.** A request/response
  round trip cost about 82 ms, which is Nagle interacting with delayed ack.
  It is now about 0.1 ms.

### Limitations, stated plainly

- **Breakpoints are real-mode only.** `Z0` for a protected-mode address is
  refused. Register and memory access work in protected mode; breakpoints do
  not.
- **One GDB client at a time.** A second connection is not accepted until the
  first detaches.
- **The stop reply is a bare `S05`.** No `T` packet with register or reason
  annotations, so `gdb` re-reads the register block after every stop.
- **No watchpoints and no hardware breakpoints** (`Z1`-`Z4`).
- **`memdump` requires the CPU to be stopped**, either halted for GDB or
  paused via QMP `stop`. It reports busy rather than queueing.
- **No authentication and no encryption.** Both servers bind loopback and
  should be treated exactly like QEMU's own monitor sockets.
- **POSIX only.** No Windows support.

---

## Notes for the submitter (NOT part of the PR body)

### Interaction with the agent bridge — investigate before submitting

Rebasing onto current upstream master surfaced a savestate failure that is
worth understanding before this is offered to anyone.

With `gdbserver=true`, upstream's own `SaveState::save()` fails while
serialising the `Dos` component: `deflate()` returns `Z_STREAM_ERROR` about
67 KB into that component's data, `save_err` is set, and
`notifyError(MSG_Get("SAVE_FAILED"))` opens a modal `systemmessagebox`, which
under a headless video driver blocks the emulation thread indefinitely. That
is why the QMP `savestate` command appeared to hang.

It is reproducible without any of this subsystem's own code paths: enable
`autosave=5` and `gdbserver=true`, connect nothing, and upstream's own autosave
fails the same way. Narrowing it down:

| per-iteration work in `Normal_Loop`  | upstream autosave |
| ------------------------------------ | ----------------- |
| nothing                              | saves fine        |
| `qmpserver` enabled (own thread)     | saves fine        |
| `gdbserver` enabled and polled       | fails on `Dos`    |
| GDB server created but never polled  | saves fine        |
| bare `getpid()` each iteration       | saves fine        |
| bare non-blocking `accept()` each iteration | fails on `Dos` |
| `errno = EAGAIN` each iteration, no syscall | saves fine |

So it is not errno and it is not generic overhead — a real `accept()` syscall
in the loop is enough. That points at a timing- or scheduling-sensitive latent
bug in upstream's savestate path rather than anything this branch does, and it
is consistent with the failure being intermittent: the full suite passed 103/103
on two runs after the test fixture began waiting for the guest to boot rather
than sleeping a fixed 2.5 s, which shifted when the save happens.

Two things follow. Upstream should probably look at the `Dos` component
serialisation. Independently, this subsystem should not be able to wedge the
emulation thread on a modal dialog just because a save failed — that is worth
fixing here regardless of who owns the underlying bug.

### Rebase notes

Base moved from `1fedf4eb2` to `6c4a364be`: 1403 commits, roughly nine months.
Five files conflicted textually; four were pure adjacency (both sides adding at
the same spot) and one was semantic:

- `src/debug/debug.cpp` — upstream changed `DEBUG_CheckKeys(void)` and added a
  Win32 VT-sequence translator, `dbg_getch_vt()`, that calls `getch()` inside
  the function. This branch needs the key passed in. Resolved by keeping
  upstream's translator and moving the platform choice to the one caller.

One change was required that is not a conflict at all and would have been
missed by a textual merge: upstream's `GetAddress()` now masks the offset to
16 bits whenever the segment is 16-bit (commit `0317b07f8`). This branch used
to hand a linear address to `CBreakpoint` as segment 0 with the whole address
in the offset, which upstream now truncates — so every breakpoint above 64 KB
silently stopped firing, the exact bug the `Z0` fix had cured. It now splits
the address into a real segment:offset pair so the offset always fits in 16
bits. This is why the branch must be tested against current master, not merely
merged into it.

### What was excluded from the curated branch, and why

- `.github/ISSUE_TEMPLATE/*` — fork administration. The fork's version deletes
  upstream's own bug_report/feature_request/question templates.
- `README.md` — a fork banner. Not ours to rewrite.
- `CLAUDE.md`, `.gitattributes`, `docs/superpowers/` — local tooling and
  internal planning documents.
- `tests/integration/dosbox_debug.py` and `test_dosbox_debug_guard.py` — a
  deprecated client shim kept only for a downstream consumer that does not
  exist upstream, plus its guard test (4 tests). Its functionality is
  duplicated by `tests/integration/protocol/`.
