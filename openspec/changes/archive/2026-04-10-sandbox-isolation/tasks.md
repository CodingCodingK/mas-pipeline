## 1. Types and config

- [x] 1.1 Create `src/sandbox/__init__.py` exporting the public surface (`SandboxMode`, `SandboxConfig`, `SandboxPolicy`, `init_sandbox`, `wrap_command`, `policy_from_permission_rules`)
- [x] 1.2 Create `src/sandbox/types.py` with `SandboxMode` enum and `SandboxConfig` / `SandboxPolicy` dataclasses
- [x] 1.3 Add `sandbox` section to `config/settings.yaml` and to the loader in `src/project/config.py` with defaults `enabled=true`, `fail_if_unavailable=false`
- [x] 1.4 Unit test: `SandboxConfig` defaults applied when section missing; values respected when set

## 2. Detection

- [x] 2.1 Implement `src/sandbox/detector.py::detect_sandbox_mode(config)` with platform branching, memoization, and `RuntimeError` on hard-fail
- [x] 2.2 Implement `init_sandbox()` that resolves the mode once, logs the boot banner line, and stores the mode for later use
- [x] 2.3 Wire `init_sandbox()` into application startup (FastAPI lifespan in `src/main.py`)
- [x] 2.4 Unit test: Linux+bwrap path, Linux-without-bwrap warn path, Linux-without-bwrap hard-fail path, Windows passthrough, disabled-by-config

## 3. Permission sync

- [x] 3.1 Implement `src/sandbox/sync.py::policy_from_permission_rules(rules)` translating `edit`/`write` allow rules to `writable_paths` and `read_file` allow rules to `readonly_paths`, reducing globs to literal prefixes
- [x] 3.2 Unit test: edit/write/read rule translation, deny rule contributes nothing, glob `src/**/*.py` reduced to `src`, repeated calls produce equal policies

## 4. Wrapper

- [x] 4.1 Implement `src/sandbox/wrapper.py::wrap_command(cmd, mode, policy)` skeleton with the four-branch dispatch (LINUX_BWRAP, MACOS_SBX, PASSTHROUGH, DISABLED)
- [x] 4.2 Implement the LINUX_BWRAP branch: `--die-with-parent`, `--unshare-all`, base read-only layer (`/usr`, `/etc`, `/lib`, `/lib64`, `/bin`, `/sbin` if present), policy `--bind` / `--ro-bind`, `--proc /proc`, `--dev /dev`, `--tmpfs /tmp`, `--`, original argv
- [x] 4.3 Implement the MACOS_SBX branch: build SBPL profile string with `(version 1)`, `(deny default)`, baseline allows, `(allow file-read*)`, per-path `(allow file-write* (subpath …))`, network deny
- [x] 4.4 Implement `is_wrapper_failure(stderr, exit_code)` recognizing `bwrap:` and `sandbox-exec:` signatures
- [x] 4.5 Unit test: argv shape per mode, default-no-network, writable bind, base layer always present, passthrough is identity, wrapper failure recognition

## 5. ShellTool integration

- [x] 5.1 Modify `src/tools/builtins/shell.py::ShellTool.call()` to compute `policy = policy_from_permission_rules(active_rules)` and call `wrap_command(argv, current_mode, policy)` before subprocess execution
- [x] 5.2 Add the `dangerously_disable_sandbox: bool` parameter to ShellTool's input schema and bypass `wrap_command` when True
- [x] 5.3 On non-zero exit, run `is_wrapper_failure` over captured stderr and set `metadata["wrapper_failure"]` and `metadata["sandbox_mode"]` on the `ToolResult`
- [x] 5.4 Extend `register_permission_hooks` to detect `dangerously_disable_sandbox=True` on shell calls and force ask/deny in NORMAL/STRICT modes (allow in BYPASS)
- [x] 5.5 Unit test: ShellTool wraps under LINUX_BWRAP (mock subprocess), passes through under PASSTHROUGH, escape hatch bypasses wrap, wrapper failure tagged in metadata

## 6. Integration tests

- [ ] 6.1 Linux integration test (skipif no bwrap): `ShellTool.call({"command": "touch /tmp/sbx-test"})` succeeds; `ShellTool.call({"command": "touch /etc/sbx-test"})` fails because `/etc` is read-only — *deferred, requires Linux runner*
- [ ] 6.2 Linux integration test (skipif no bwrap): `ShellTool.call({"command": "curl -sS http://example.com"})` fails because network is unshared — *deferred, requires Linux runner*
- [x] 6.3 Windows integration: ShellTool runs raw under PASSTHROUGH and uses `create_subprocess_shell` (verified by `scripts/test_sandbox.py::test_shell_passthrough_uses_shell`); boot warning emitted exactly once via `init_sandbox` memoization (verified by `test_init_sandbox_memoized`)
- [ ] 6.4 macOS integration test (skipif not Darwin): writable subpath honored, network denied — *deferred, requires macOS runner*

## 7. Docs and OpenSpec

- [x] 7.1 Add a short "Sandbox" section to `README.md` covering install (`apt install bubblewrap`), default behavior, and the `sandbox.fail_if_unavailable` knob
- [x] 7.2 Update `.plan/progress.md` Phase 5 row: Sandbox ✅
- [x] 7.3 Run `openspec validate sandbox-isolation --strict` (passes)
- [x] 7.4 Run the regression test sweep (`scripts/test_sandbox.py` 43/43; permission/hooks/tools/pipeline/loop_compact/subagent regressions all green)
- [ ] 7.5 Commit and archive the change via `/openspec-archive-change sandbox-isolation`
