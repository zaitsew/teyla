# Low on disk

Agents fill a Mac's disk: simulators, build output, package caches, worktrees. This page is the order to work in. Part one needs nothing but Teyla. Part two adds an external drive.

## Part one: without a drive

```bash
teyla storage                  # what holds the disk: worktrees, build output, caches, simulators, free space
teyla storage clean            # dry run: what is safe to remove; add --apply to remove it
teyla storage sweep --dry      # what the sweep would remove: temp builds, old simulators, DerivedData, caches, logs
teyla storage sims --reap      # shut down idle simulators, delete old lane simulators
```

- **`teyla storage`** only reads. It lists every git worktree (SAFE means clean, pushed, idle, no process in it), git-ignored build output of idle repos, each cache with the command that clears it, and the booted simulators. Free space is the first line.
- **`teyla storage clean`** removes SAFE worktrees (`git worktree remove`, the branch stays) and idle build output. It is a dry run until you pass `--apply`.
- **`teyla storage sweep`** removes what agents leave behind. Each category has its own age and process check, and a running process always wins. Under `storage.sweep_critical_free_gb` (10) free, whole caches go.
- **The simulator agent** (`teyla config set storage.sims_agent=true`, then `teyla routine install`) runs `storage sims --reap` every 10 minutes. A simulator nothing uses for `storage.sim_idle_min` (30) minutes is shut down.
- **The guard** (`teyla load`) refuses new builds and simulators while free disk is low or falling.

Nothing here needs a setting. Each command has a dry run first.

## Part two: with a drive

A Mac with a small disk can keep the heavy, regenerable folders on an external drive: the simulator devices, DerivedData, the Android SDK and AVDs, the Gradle caches. Each stays at its usual path as a symlink to the drive.

### Prepare the drive (your steps, once)

1. **Format it as APFS with a GUID partition map.** Pick the whole physical disk in Disk Utility, not just a volume. A sandboxed app (including a terminal inside a sandbox) may be unable to erase a disk: use Disk Utility itself.
2. **Turn ownership on.** A new external volume often ignores file owners, which breaks build tools. Run both, with your own volume name:

   ```bash
   sudo diskutil enableOwnership /Volumes/External
   sudo chown "$USER" /Volumes/External
   ```

3. **Turn Spotlight indexing off** for the drive (`sudo mdutil -i off /Volumes/External`, or Spotlight settings, Privacy). Indexing a cache folder burns CPU and writes to the drive all day.
4. **Eject before you unplug** (`diskutil eject /Volumes/External`, or the Finder). A pulled drive leaves broken links behind.
5. **Keep only regenerable data on it.** Every tool can download or build it again, so the drive needs no backup.
6. **Put nothing with secrets on it.** An unencrypted drive can be read by anyone who holds it: no signing keys, no `gradle.properties` with passwords, no `.env` files.

### Move the folders: `teyla storage offload`

```bash
teyla storage offload --to /Volumes/External            # dry run: each folder, its size, "move" or why not
teyla storage offload --to /Volumes/External --apply    # move them, one at a time
teyla storage offload --undo ~/.gradle/caches           # copy one back and remove its link
```

`--to` is the mount point of the drive. The dry run changes nothing. The candidates are fixed: DerivedData, the Android SDK, the Gradle caches and wrapper, and (only with `--with-app-data`) the simulators and the virtual devices, because those can hold app data that exists nowhere else. You cannot name another path.

Each folder goes through the same steps, and the original is deleted last:

1. **Refuse** if anything uses it (a booted simulator, `xcodebuild`, a Gradle daemon, an emulator; a process list that cannot be read counts as "in use"), if it sits in or holds a git repository, holds a file that may be a secret (Gradle properties, keystores, ADB keys, `.env` files) or a mount point, if the drive is not writable, has ownership disabled, is on the same device, or has too little room, or if the destination exists already.
2. **Copy** to `<drive>/teyla/<name>.partial` (`ditto` on macOS, `cp -a` elsewhere).
3. **Verify** the copy: the same files, folders, links and bytes, and the same digest of every path, type, size and link target. The source is scanned again: a writer that started during the copy fails the move. File contents are not hashed, which would read 100 GB twice; the manifest catches a missing, extra, renamed or resized file.
4. **Switch**: rename the copy into place, rename the original aside (`<path>.teyla-offload-<time>`), make the symlink.
5. **Smoke check** that kind through the link (`simctl` lists the same devices, `adb version` runs, a Gradle folder takes a write, and so on).
6. **Delete** the original. `--keep` keeps it until `teyla storage offload --finalize`, for a week of trust.

Any failure before step 6 puts everything back: the link goes, the original is renamed back, the copy is deleted. Each step is written to `~/.teyla/state/offload.json` first, so a crash (or a pulled cable) leaves a state that `teyla storage offload --recover` reads and rolls back. `teyla doctor` names an unfinished offload. One offload runs at a time.

A moved folder is not backed up anywhere else: if the drive dies, rebuild the folder. Only data a tool can download or build again belongs there.

### What Teyla does with a drive

No setting is needed. Teyla looks at the heavy paths on every run, and a symlink that points to another drive shows up:

```
teyla storage
disk    135.0G free of 460.0G
disk    /Volumes/External  412.0G free of 931.0G
paths on external volumes
  ok        iOS simulators  ~/Library/Developer/CoreSimulator/Devices -> /Volumes/External/...
```

- A link to another device is "on <mount point>". A link to nothing is `DANGLING`. A plain folder is never reported.
- A cache on a drive is counted on the drive, not as internal usage.
- **A drive that is not attached is normal.** A laptop leaves the desk. `teyla doctor` prints one note and exits 0, the session-start hook prints one line, and only `teyla load --admit sim|build` refuses: for the kind whose path dangles (`sim` needs the simulator devices; `build` needs DerivedData, the Android SDK and the Gradle caches). Lanes are never refused.
- Every message says the same thing: **do not recreate these paths on the internal disk.** A tool that sees "No such file" and makes the folder fills the internal disk without a sound. If a link you remembered turns into a plain folder while the drive is away, Teyla reports it as `REPLACED`.
- `storage sims --reap` and the sweep do nothing through a dangling link, and never remove a link.

Two optional settings, in `~/.teyla/config.toml`:

```bash
teyla config set storage.volumes=/Volumes/External            # show this drive even before any link points into it
teyla config set storage.volumes_required=/Volumes/External   # its absence is a `teyla doctor` failure, one line per path
```

On macOS, `teyla doctor` also notes a drive with ownership disabled or Spotlight indexing on. Each check is cut off after 8 seconds, and other systems skip it.
