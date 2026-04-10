## Context

Phase 5 brought a Permission system that intercepts every tool call via a `PreToolUse` hook and matches against rule patterns (`Edit("projects/**")`, `Bash("git *")`, …). String matching is good UX but a weak boundary: symlinks, `cd`, shell substitution, and rule-list mistakes can all let a command touch paths the user never intended. We want a second, kernel-level boundary specifically for ShellTool — not a replacement for Permission, an addition under it.

CC solved the same problem with `@anthropic-ai/sandbox-runtime`, which on Linux delegates to **bubblewrap** (a setuid front-end for Linux user/mount/network namespaces + seccomp) and on macOS delegates to **`sandbox-exec`** (the command-line front-end for Apple's TrustedBSD MAC framework). On Windows there is no comparable, low-friction primitive, and CC simply skips sandboxing there. We adopt the same posture.

The full design discussion is captured in `.plan/sandbox_design_notes.md`; this document records the decisions only.

## Goals / Non-Goals

**Goals:**
- Add a kernel-enforced boundary around every ShellTool subprocess so that path/network confinement does not depend on string matching.
- Reuse existing OS primitives — write zero security code ourselves; we only translate config and assemble argv.
- Keep the implementation under ~200 lines across one new package.
- Default to **on**; degrade gracefully when the sandbox binary is missing (warn + passthrough), with an opt-in hard-fail.
- Make Permission rules the single source of truth: anything writable to Permission is writable to the sandbox.
- Zero friction on Windows (Junjie's primary dev box): one-line warning at startup, then transparent passthrough.

**Non-Goals:**
- Docker / container backends. Per-call namespace wrap is faster, lighter, and avoids image build / volume / Windows-shared-mount headaches.
- Per-domain network whitelisting via egress proxy (socat/tinyproxy). Too complex; we fully disable network inside the sandbox and let WebSearch / MCP run in the parent Python process.
- Sandboxing file tools (Read/Write). They run in-process; bwrap cannot intercept Python's `open()`. Permission is the only boundary for those.
- CPU / memory / pid / wall-time limits. bwrap is the wrong layer; production should use systemd cgroups outside the process.
- A violations dashboard or metrics. First version logs to stderr.
- Native Windows sandbox (AppContainer / Job Objects). Too much engineering for one developer's box.

## Decisions

### Decision 1: Per-call wrap, not a long-lived sandbox process
**Choice:** For each ShellTool invocation, we synthesize a fresh `bwrap …  -- bash -c '<cmd>'` (or `sandbox-exec -f profile.sb bash -c '<cmd>'`) argv and hand it to `subprocess.run`.
**Why:** bwrap and sandbox-exec are not daemons — they create a namespace, exec the child, then exit. There is no lifecycle to manage, no state to clean up, and no crash recovery to design. This matches CC's `wrapWithSandbox()` exactly.
**Alternative considered:** A long-lived sandbox shell that the engine talks to over a pipe. Rejected — adds an IPC protocol, a session-state class, and a recovery story for what is effectively just argv assembly.

### Decision 2: Translation only — we own no security code
**Choice:** `src/sandbox/wrapper.py` produces a `list[str]` argv. It does not call any `prctl`, `unshare`, `seccomp`, or MAC API directly.
**Why:** Every line of "real" sandbox code is a line we can get wrong. bwrap and sandbox-exec are audited, setuid-gated, and shipped by distro / Apple. Our job is to pick correct flags.
**Implication:** "Sandbox enabled" is meaningless without `bwrap` / `sandbox-exec` on `PATH`. The detector is therefore part of the contract, not a nice-to-have.

### Decision 3: Default `enabled: true`, default `fail_if_unavailable: false`
**Choice:** Sandbox starts enabled. If the platform binary is missing, we log a one-line warning and pass commands through unwrapped. Users who want hard-fail set `sandbox.fail_if_unavailable: true`.
**Why:** "Default secure" is the right posture — most CI Linux runners and most macOS dev machines will have the binary, so the secure path becomes the unmarked path. CC's default is the opposite (`enabled: false`); we believe that bias is wrong for a project where the agent has Bash.
**Trade-off:** First-time Windows users see a warning. Acceptable cost.

### Decision 4: Permission is the single source of truth for paths
**Choice:** `src/sandbox/sync.py` reads the active `PermissionRule` set and produces `(allow_write, deny_write, allow_read)` lists. The wrapper consumes these to emit `--bind` / `--ro-bind` (Linux) or `(allow file-write* (subpath …))` (macOS).
**Why:** Two sources of truth diverge. If the user adds `Edit("data/**")` to Permission and forgets to also add it to a sandbox config, every Edit through Bash silently fails. By deriving sandbox paths from Permission rules, the user only edits one place.
**Alternative considered:** Independent `sandbox.allow_paths` config. Rejected — duplication and divergence risk.

### Decision 5: Network fully disabled in sandbox, network tools bypass
**Choice:** Linux uses `--unshare-net`; macOS uses `(deny network*)`. Tools like WebSearch and MCP do their own HTTP from the parent Python process and never go through ShellTool.
**Why:** The two ways an agent might need network — fetching a URL and talking to an MCP server — already have first-class implementations that don't shell out. Letting Bash hit the network would require either an egress proxy (complex) or full openness (insecure). Disabling it costs us nothing.
**Caveat:** `git push`, `curl`, `pip install` from inside an Agent shell command will fail. Document this; the workaround is "use the dedicated tool" or "raise a Permission ask for an unsandboxed run."

### Decision 6: Windows = passthrough + warn-once
**Choice:** On Windows, `wrap_command()` returns the original argv unchanged and a process-global flag prints one warning to stderr the first time it is called.
**Why:** No primitive on Windows offers what bwrap offers without a major engineering investment. AppContainer is opt-in by the launching process and has its own ACL model that doesn't compose with our PermissionRule layout. Job Objects don't isolate the filesystem at all.
**Trade-off:** Windows users get only Permission as a boundary. This matches CC and is acceptable for development; production deploys go on Linux.

### Decision 7: Single new package, no abstract base class
**Choice:** Three platform branches live in one `wrap_command()` function selected by the detector's mode enum. No `SandboxBackend` ABC, no plugin loader, no entry-points.
**Why:** Three implementations is not enough to justify an abstraction. An ABC adds three classes and three files for behavior that is already isolated by `if mode == ...`.

## Risks / Trade-offs

- **Risk:** bwrap setuid binary may be missing or restricted on some hardened distros (e.g., grsec, certain managed Kubernetes nodes). → **Mitigation:** Detector reports unavailable; user configures `fail_if_unavailable` per environment. Document in README.
- **Risk:** A wrapped command's exit code can come from either bwrap (e.g., `126` = could not exec) or the inner command. Agents that switch on exit code may misinterpret. → **Mitigation:** Wrapper inspects stderr for the bwrap signature lines and tags the `ToolResult` with `wrapper_failure: true` so the Agent / hook can distinguish.
- **Risk:** Bind-mounting too narrowly may break legitimate workflows (e.g., `tox` reading `/etc/ssl/certs`). → **Mitigation:** Default policy includes a curated read-only base layer (`/usr`, `/etc`, `/lib*`, `/bin`); writable paths come only from Permission.
- **Trade-off:** Network is binary on/off. We accept this for v1; if a real use case for whitelisted egress arises later, it becomes its own change.
- **Trade-off:** macOS SBPL profiles are a string template assembled at call time. Easier to read than a `.sb` file under `resources/`, but harder to lint. We accept it because the profile is short.

## Open Questions

1. **Linux base layer policy:** `--ro-bind /` (whole rootfs read-only, then carve out writable spots) vs explicit `--ro-bind /usr`, `--ro-bind /etc`, … . First is simpler, second is auditable. **Lean: explicit list, ~6 entries.**
2. **macOS SBPL profile location:** inline string in `wrapper.py` vs `src/sandbox/profiles/default.sb` resource file. **Lean: inline for v1, extract if it grows past ~30 lines.**
3. **Exit-code disambiguation:** stderr signature scan vs reserve a bwrap-side exit shim that prefixes the output. **Lean: stderr scan; cheap and good enough.**
4. **`dangerously_disable_sandbox=true` on ShellTool calls:** CC has `allowUnsandboxedCommands` for the rare case (e.g., `apt install`). Do we expose the same per-call escape hatch, or force users to flip the global config? **Lean: yes, gated by a Permission ask, mirrors CC semantics.**
