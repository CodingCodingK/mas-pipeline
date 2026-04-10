# sandbox-wrapper Specification

## Purpose
TBD - created by archiving change sandbox-isolation. Update Purpose after archive.
## Requirements
### Requirement: wrap_command function
The system SHALL provide `wrap_command(cmd: list[str], mode: SandboxMode, policy: SandboxPolicy) -> list[str]` in `src/sandbox/wrapper.py`. The function SHALL return an argv list that, when handed to `subprocess.run`, executes the original command inside the appropriate kernel-level isolation primitive for the given mode. It SHALL NOT spawn the subprocess itself.

#### Scenario: Function returns argv list
- **WHEN** `wrap_command(["ls", "-la"], LINUX_BWRAP, policy)` is called
- **THEN** it SHALL return a `list[str]` whose first element is `bwrap` and whose tail contains the original command

### Requirement: Linux bwrap branch
When `mode == LINUX_BWRAP`, `wrap_command` SHALL produce an argv that begins with `bwrap` and includes:
- `--die-with-parent`
- `--unshare-all` followed by `--share-net` ONLY if the policy explicitly opts in (default: no `--share-net`, network is unshared)
- `--ro-bind` entries for a base read-only layer (`/usr`, `/etc`, `/lib`, `/lib64`, `/bin`, `/sbin` when present)
- `--bind <host> <inside>` entries for every writable path supplied by the policy
- `--ro-bind <host> <inside>` entries for every read-only path supplied by the policy
- `--proc /proc`, `--dev /dev`, `--tmpfs /tmp`
- `--` separator followed by `bash -c '<original command joined>'`

#### Scenario: Network unshared by default
- **WHEN** `wrap_command` builds an argv with `mode=LINUX_BWRAP` and a policy that does not opt into network
- **THEN** the argv SHALL contain `--unshare-all` and SHALL NOT contain `--share-net`

#### Scenario: Writable paths bound rw
- **WHEN** the policy includes writable path `/repo/projects`
- **THEN** the argv SHALL contain `--bind /repo/projects /repo/projects`

#### Scenario: Base layer always read-only
- **WHEN** `wrap_command` builds an argv with `mode=LINUX_BWRAP`
- **THEN** the argv SHALL contain `--ro-bind /usr /usr` and `--ro-bind /etc /etc`

### Requirement: macOS sandbox-exec branch
When `mode == MACOS_SBX`, `wrap_command` SHALL produce an argv of the form `["sandbox-exec", "-p", <sbpl_profile_string>, "bash", "-c", <joined command>]`. The SBPL profile SHALL:
- Begin with `(version 1)` and `(deny default)`
- Allow `process-fork`, `process-exec`, `signal`, `sysctl-read`
- Allow `file-read*` for the entire filesystem
- Allow `file-write*` only for paths in the policy's writable list, expressed as `(allow file-write* (subpath "<path>"))`
- Deny `network*` unless the policy explicitly opts into network

#### Scenario: Profile denies network by default
- **WHEN** `wrap_command` builds an argv with `mode=MACOS_SBX` and no network opt-in
- **THEN** the SBPL profile string SHALL contain `(deny network*)`

#### Scenario: Writable subpath allowed
- **WHEN** the policy includes writable path `/Users/me/repo/projects`
- **THEN** the SBPL profile SHALL contain `(allow file-write* (subpath "/Users/me/repo/projects"))`

### Requirement: Passthrough and disabled branches
When `mode == PASSTHROUGH` or `mode == DISABLED`, `wrap_command` SHALL return the input `cmd` unchanged.

#### Scenario: Passthrough is identity
- **WHEN** `wrap_command(["ls", "-la"], PASSTHROUGH, policy)` is called
- **THEN** it SHALL return exactly `["ls", "-la"]`

#### Scenario: Disabled is identity
- **WHEN** `wrap_command(["ls", "-la"], DISABLED, policy)` is called
- **THEN** it SHALL return exactly `["ls", "-la"]`

### Requirement: Wrapper-failure tagging
The wrapper SHALL provide `is_wrapper_failure(stderr: str, exit_code: int) -> bool` that returns True when the captured stderr contains a recognizable bwrap or sandbox-exec error signature (e.g. `bwrap: ` prefix, `sandbox-exec: cannot read profile`). ShellTool SHALL use this to set `metadata["wrapper_failure"] = True` on the ToolResult so the agent and hooks can distinguish a sandbox setup failure from a command failure.

#### Scenario: Recognizes bwrap stderr signature
- **WHEN** `is_wrapper_failure("bwrap: Can't bind /nope: No such file\n", 1)` is called
- **THEN** it SHALL return True

#### Scenario: Real command failure not tagged
- **WHEN** `is_wrapper_failure("ls: cannot access /nope: No such file or directory\n", 2)` is called
- **THEN** it SHALL return False

