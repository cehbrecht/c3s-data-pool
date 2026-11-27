# Catalogs, output and file handling

Each CSV row needs `path`, `size` (bytes) and `mip_era`. Paths are relative to the
source/target roots and include the dataset version; `mip_era` is not prepended.
Catalogs are streamed row by row.
Each collection is read once to count file entries, then again to process them;
progress shows processed/total files and a percentage. Remote catalogs are
downloaded once and reused from `~/.cache/c3s-data-pool` (or
`$XDG_CACHE_HOME/c3s-data-pool`). Both passes use the same open local snapshot.
Use `--cache-dir PATH` to choose a writable local disk and `--refresh-catalog` to
replace cached snapshots. Failed downloads leave the previous cache intact and
return an error. Local catalogs are read directly.

## Build and verify

Run the CLI directly. Without activating Conda, use
`.conda-env/bin/c3s-data-pool` instead of `c3s-data-pool` below.

```sh
# Check source existence, type and size; only the local cache and log are written.
c3s-data-pool build --config config/dkrz.toml --log-file logs/cmip6-dry-run.log

# Review the displayed roots and answer yes to create hardlinks.
c3s-data-pool build --config config/dkrz.toml --apply

# Explicit alternative: copy file contents (requires additional storage/quota).
c3s-data-pool build --config config/dkrz.toml --copy --apply

# Check retained files, independently of the original source pool.
c3s-data-pool verify --config config/dkrz.toml
```

Add `--collection c3s-cmip6` or `--collection c3s-cmip6-decadal` to select a
collection. Apply requires `y` or `yes`; Enter or unavailable stdin cancels.
For unattended jobs, add `--batch` to skip confirmation. It does not enable
writes by itself: `--apply` is still required.
`--hardlink` is the default and can also be specified explicitly. `--copy` selects
independent copies; the two flags are mutually exclusive. There
is no automatic fallback to copying when a hardlink fails.
Dry-run never creates data pool directories or hardlinks. Keep its writable cache
and log on the VM's local disk rather than read-only Lustre.

Dry-run makes one stat call per source file and follows symlinks. That single
response provides existence, type and size; comparing the size costs no extra
filesystem request. Destination conflicts and filesystem compatibility are
checked during apply, so a successful dry-run cannot guarantee a successful
build.

Without `--batch`, verbose output is the default: detailed timestamped console
logs followed by a final status and log path. With `--batch`, silent output is
the default. Explicit `--verbose` or `--silent` overrides the default, including
when output is redirected. Use `--progress` for a progress bar on an interactive
terminal, instead of
verbose logs. When redirected, this mode prints only the final status. The three
console options are mutually exclusive.

Both modes keep the full log file at `~/.local/state/c3s-data-pool/logs`
(respecting `XDG_STATE_HOME`), or the path chosen with `--log-file`. Explicit log
files are appended to. `--silent` still prompts for apply unless `--batch` is
also provided; argument and log setup errors remain visible. These output options
also work with `verify`.

```sh
c3s-data-pool build --config config/dkrz.toml
c3s-data-pool build --config config/dkrz.toml --copy --apply --batch \
  --log-file logs/c3s-copy.log
```

Heartbeat log entries every 15 seconds include the current file and
elapsed time; use `--heartbeat-seconds 5` for more frequent log entries.

Apply resolves source symlinks and uses their metadata to check type and size.
With `--hardlink`, it prepares safe destination directories and attempts each hardlink directly,
without first probing the destination file or filesystem compatibility. If a
destination exists, its inode and device must match the source to be skipped.
Apply logs invalid entries, missing files, mismatches, conflicts and transfer
failures as `ERROR`, then continues with the remaining files and collections.
The final exit code is non-zero if any failed. An unreadable or malformed catalog
ends that collection; later collections are still processed. Successful files remain;
rerun after resolving the problems. Existing data files are never overwritten,
deleted or modified. Keep directory trees stable during a run; apply rechecks
destination directories before each transfer. Verify checks destination types and
sizes independently of the source and reports all failures.

Copy mode needs read access to sources and can copy across filesystems. It creates
new files owned by the running user, preserving source permission bits and
access/modification times, without copying ownership or ACLs. Existing regular files are skipped
if their catalog size matches; other destinations are conflicts. This is size
validation, not checksum validation, and does not convert existing hardlinks.

Copies are written to hidden temporary files beside their destinations and
validated before publication. Publication uses a hardlink from the new temporary
file owned by your account, which avoids the original source ownership restriction
and never overwrites a destination. The destination filesystem must support
hardlinks. Failed/interrupted copies remove their temporary files; an uncatchable
termination may leave `.c3s-copy-*.part` files, which reruns ignore.

Progress and summaries go to the log with local timestamps and UTC offsets,
including logical catalog volume in decimal GB/TB and errors. Exact bytes are
used internally for file-size checks.
`files` counts processed catalog entries, including duplicates and invalid rows.
`datasets` counts distinct parent directories of valid entries per collection;
different versions count separately. Totals sum across collections.
Exit `0` means success; non-zero means cancellation, an error or an incomplete
pool. `checked` counts source files that passed dry-run; `created` and `existing`
count apply results. Use verify to check a built pool.

