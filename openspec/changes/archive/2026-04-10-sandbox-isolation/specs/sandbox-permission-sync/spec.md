## ADDED Requirements

### Requirement: SandboxPolicy dataclass
The system SHALL define a `SandboxPolicy` dataclass in `src/sandbox/types.py` with fields:
- `writable_paths: list[str]` — host paths bound read-write into the sandbox
- `readonly_paths: list[str]` — host paths bound read-only in addition to the base layer
- `allow_network: bool` (default `False`)

#### Scenario: Default policy is fully confined
- **WHEN** `SandboxPolicy()` is constructed with no arguments
- **THEN** `writable_paths` and `readonly_paths` SHALL be empty and `allow_network` SHALL be `False`

### Requirement: Policy derived from PermissionRule set
The system SHALL provide `policy_from_permission_rules(rules: list[PermissionRule]) -> SandboxPolicy` in `src/sandbox/sync.py`. The function SHALL translate each `allow` rule whose tool is `Edit`, `Write`, or `Bash` into entries on `writable_paths`, and each `allow` rule whose tool is `Read` into entries on `readonly_paths`. `deny` rules SHALL NOT add paths. Glob patterns SHALL be reduced to their longest non-glob prefix (e.g. `projects/**/*.py` → `projects`).

#### Scenario: Edit rule becomes writable path
- **WHEN** the rule set includes `PermissionRule(tool=Edit, action=allow, pattern="projects/**")`
- **THEN** the resulting policy SHALL include `"projects"` in `writable_paths`

#### Scenario: Read rule becomes readonly path
- **WHEN** the rule set includes `PermissionRule(tool=Read, action=allow, pattern="docs/**")`
- **THEN** the resulting policy SHALL include `"docs"` in `readonly_paths`

#### Scenario: Deny rule contributes nothing
- **WHEN** the rule set includes `PermissionRule(tool=Edit, action=deny, pattern="secrets/**")`
- **THEN** the resulting policy's `writable_paths` SHALL NOT include `"secrets"`

#### Scenario: Glob reduced to literal prefix
- **WHEN** the rule set includes `PermissionRule(tool=Write, action=allow, pattern="src/**/*.py")`
- **THEN** the resulting policy SHALL include `"src"` in `writable_paths`, not `"src/**/*.py"`

### Requirement: Policy derivation is pure
`policy_from_permission_rules` SHALL be a pure function — it SHALL NOT read files, query the filesystem, or memoize across calls. ShellTool SHALL invoke it on every wrap so that mid-run permission updates are reflected immediately.

#### Scenario: Same rules produce equal policies
- **WHEN** `policy_from_permission_rules` is called twice with structurally identical rule lists
- **THEN** both calls SHALL return policies whose fields are equal

#### Scenario: Updated rules reflected next call
- **WHEN** the active rule set changes between two ShellTool invocations
- **THEN** the second wrap SHALL use a policy derived from the new rule set, not a cached prior policy
