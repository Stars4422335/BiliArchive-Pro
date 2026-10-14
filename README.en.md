# 📺 BiliArchive-Pro

> **Back up, sync, and organize your personal Bilibili assets — with a local WebUI**

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Release: v1.6.0](https://img.shields.io/badge/release-v1.6.0-green.svg)](https://github.com/Stars4422335/BiliArchive-Pro/releases/tag/v1.6.0)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)

[简体中文](README.md) | **English**

**BiliArchive-Pro** is a stable, safety-first backup and sync tool for dedicated Bilibili users, producing media libraries that comply with Plex, Jellyfin, and Emby conventions. It is not just a downloader that supports up to 4K/HDR — it is an intelligent **personal digital librarian**.

Whether you are guarding against a creator deleting their videos, protecting against links going invalid, or simply want high-quality videos and articles permanently mirrored onto your NAS, BiliArchive-Pro provides an out-of-the-box, set-and-forget solution.

---

## ✨ Highlights

- 🚀 **Comprehensive media capture**: Not just videos. Downloads at the highest available quality (including multi-page videos) **plus first-class support for article/column content**, converted to Markdown with images localized to your disk.
- 👥 **Full follow-sync**: `followings.mode` archives submissions from every UP you follow, or monitors specific UIDs via `list` mode. Unfollowing never removes local assets; dead submissions fall into the tombstone / orphan-protection path.
- 🎬 **Media-library sidecar output (Plex/Jellyfin/Emby)**: Media and `.nfo` files share a filename, with standard cover art. Multi-page videos can be organized as `Season 01/S01E##`, and creators are written into the cast metadata.
- 🛡️ **Purpose-built asset protection**:
  - **Tombstone mechanism**: when a video in your favorites is deleted upstream, a metadata-only NFO placeholder is generated locally so the loss is still recorded.
  - **Orphan protection**: if an already-downloaded video disappears upstream, the local asset is tagged and locked (e.g. an `[源端已删]` prefix is added). Local files are **never** overwritten or synced away.
- ⚡ **Periodic full scans and anti-rate-limit**: full sweep of your favorites on a configurable interval, skipping archived assets via a local database and refreshing their liveness timestamp. Pagination and post-download cooldowns keep request volume low.
- 🖥️ **Local WebUI panel**: a separate process showing scan status, disk space, and real cover art, with cross-page search, filtering, allowlisted settings editing, and operational commands (trigger a scan / re-download one asset / request a restart) with execution receipts.
- 💬 **Danmaku rendering**: converts the current media's Bilibili XML danmaku into `.ass` subtitles, allocating separate scrolling, top, and bottom tracks, discarding conflicts under load to avoid overlapping text.
- 🔄 **Optional component checks**: `yt-dlp` can be checked per `auto` / `notify` / `off` policy. Automatic updates must pass the official GitHub SHA256 check, and FFmpeg availability is verified on the system path or your configured path.

---

## 🛠️ Installation

BiliArchive-Pro runs on Windows, macOS, Linux (including WSL), and common NAS platforms. Choose **native Python** or **Docker**.

### Option 1: Native Python (recommended for development/testing)

**1. Prerequisites**
Ensure **Python 3.10+** is installed. `yt-dlp` comes from `requirements.txt`; the program prefers your configured `yt-dlp` (also `.exe` on Windows), then the system `PATH`, and otherwise only prints installation instructions. Muxing requires [**FFmpeg**](https://ffmpeg.org/download.html): `sudo apt install ffmpeg` on Linux, or drop `ffmpeg.exe` / `ffmpeg` into this project's `bin/` directory.

```bash
# 1. Clone
git clone https://github.com/Stars4422335/BiliArchive-Pro.git
cd BiliArchive-Pro

# 2. Create and activate a virtual environment (optional but recommended)
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
```

### Option 2: Docker / Docker Compose (recommended for NAS and servers)

The Docker image bundles FFmpeg and the Python runtime, fully isolated — the most stable, hands-off way to keep it running.

**1. Clone and initialize**
```bash
git clone https://github.com/Stars4422335/BiliArchive-Pro.git
cd BiliArchive-Pro
```

**2. Log in on the host (required)**

Scanning a QR code inside a container is awkward, so generate credentials locally first:

```bash
pip install httpx qrcode bilibili-api-python
python login.py
```
*Scan the QR code printed in the console with the Bilibili app. On success, `data/cookie.json` is created.*

**3. Start the core container**
```bash
docker compose up -d biliarchive
```
Follow along with `docker compose logs -f biliarchive`.

**4. Optional: start the WebUI**

The WebUI runs as a separate service and **requires** a bearer token. The published port binds to host `127.0.0.1` only:

```bash
export BILIARCHIVE_WEB_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
docker compose --profile webui up -d
```

PowerShell:

```powershell
$env:BILIARCHIVE_WEB_TOKEN = python -c "import secrets; print(secrets.token_urlsafe(32))"
docker compose --profile webui up -d
```

Open `http://127.0.0.1:8000` and enter the token. To reach it from another machine, prefer an SSH tunnel or a TLS-terminating reverse proxy — do not expose the unencrypted port to the internet.

> **Persistence**: Docker maps `data/` (database, credentials, runtime state, `config.local.yaml`), `downloads/` (videos and articles), and `bin/` (component tools) to the host; `config.yaml` is mounted read-only. After saving settings in the WebUI, restart the `biliarchive` service for them to take effect.

---

## ⚙️ Configuration (`config.yaml`)

`config.yaml` in the project root is the default template. Adjust it to your needs before the first run:

```yaml
system:
  download_path: "./downloads"       # media library location
  plex_mode: true                    # multi-P uses Season 01/S01E; false flattens to P01/P02
  check_update_on_start: false       # run component checks at startup
  max_downloads_per_run: 0           # 0 = unlimited. Try 5 for a smoke test
  download_timeout_seconds: 7200     # per yt-dlp task timeout; 0 disables
  sync_watch_later: false            # also archive the "watch later" list
  sync_watch_history: false          # archive watch history (metadata only, no media)
  max_history_days: 90               # watch-history lookback window (days); 0 = unlimited
  verify_integrity: "off"            # integrity check level: off / light / full (see below)

network:
  sync_retry_attempts: 3             # max attempts when reading a source list
  sync_retry_backoff_seconds: 2      # initial exponential backoff
  request_timeout_seconds: 30        # timeout for direct HTTP sync requests
  github_proxy_url: "https://mirror.ghproxy.com/" # helps download yt-dlp behind the GFW

components:
  yt-dlp:
    strategy: "auto"                 # update after checksum; notify only; or off

sync_collections:
  # mid is the owning creator's UID, id is the collection/series ID
  # - id: 67890
  #   mid: 12345
  #   name: "A creator's curated collection"

followings:
  # Local assets are kept when you unfollow. See the config guide for the full switch list.
  mode: "off"                       # off / all / list
  list:
    # - mid: 946974
    #   name: "Some creator"        # name is optional; queried from Bilibili if omitted

favorites:
  # Leave this empty to automatically back up ALL favorites on your account
  # - id: 12345678
  #   name: "My favorites"
```

Put your personal test settings in `config.local.yaml` at the project root. The program recursively merges it after loading `config.yaml`, with local values winning for lists and scalars. This file is ignored by Git and Docker builds, making it suitable for your own favorites, switches, and paths.

Failed list reads are retried up to `sync_retry_attempts` times. When retries are exhausted, the affected favorite / watch-later list / collection is marked as failed for that round while other sources continue; the failed source is retried next round.

A download exceeding `download_timeout_seconds` has its yt-dlp/FFmpeg process tree terminated, returns as failed, and cleans up the temporary cookie. A non-empty `.part` file is kept and resumed next round via `yt-dlp --continue`; empty leftovers are removed.

Media library output rules:

- Single-P videos keep their directory layout in both modes; media, subtitles, danmaku `.ass`, and NFO share a filename prefix, and a `poster.jpg` is generated in the video directory.
- With `plex_mode: true`, multi-P videos are written into `Season 01/` as `S01E01`, `S01E02`; the root gets `tvshow.nfo` and `poster.jpg`, and each episode gets a matching NFO and `-thumb.jpg`.
- With `plex_mode: false`, multi-P videos are flattened into the video directory as `P01`, `P02`, each with its own NFO and cover to prevent overwrites.
- Each page downloads via an independent URL. The database completion status is written only after **all** pages and key NFO files succeed; a mid-way failure resumes with existing files and `.part` next round.
- Existing Active records are re-verified against the database `p_count` and stable per-page identifiers: missing pages trigger a resume, and only a complete set is skipped.
- Favorite directories and media filenames are truncated against a full path budget; if `download_path` is so long that no unique identifier survives, the program fails explicitly instead of risking name collisions.
- This setting only affects new or re-downloaded assets; existing archives are never moved automatically.

> `config.local.yaml` is for local overrides only and must not be shipped in a release package. Docker Compose writes local overrides to `data/config.local.yaml`, which appears in the image as `/app/data/config.local.yaml`.

### 🔖 Feature switches and levels

**Follow-sync (`followings.mode`)**

| Mode | Behavior | Use when |
|---|---|---|
| `off` | Disabled (default) | You only use favorites/collections |
| `all` | Archive submissions from every creator you follow | You want "follow means backup"; ⚠️ large first run |
| `list` | Archive only the UIDs listed below | You monitor a few creators; works without a follow relationship |

- When first enabling `all`, set `max_downloads_per_run: 5` for a trial round to observe rate limits and disk usage before opening it up.
- `list` entries accept `[{mid: 946974, name: "Creator"}]` or bare UIDs `[946974]`; a missing name is looked up from Bilibili.
- **Unfollow semantics**: after unfollowing (or removing from `list`), the creator is no longer scanned, but locally archived assets are **permanently kept**. No deletion logic exists.
- Follow sources share the same protection as favorites: dead submissions automatically create tombstones or trigger orphan protection; complete archives are skipped.

**Watch history sync (`system.sync_watch_history`)**

- When enabled, watched videos are recorded as local **metadata only** (bvid, title, creator, view time). **No media is downloaded.**
- Use it to keep a private record of "when did I watch what". Records do not participate in library organization or integrity checks.
- `max_history_days` controls the lookback window (default `90`, `0` for unlimited). History can contain tens of thousands of entries, so understand the rate-limit risk of a first full pull; incremental rounds only chase new records.

**Integrity check (`system.verify_integrity`)**

| Level | What is checked | Cost | Best for |
|---|---|---|---|
| `off` | Nothing (default) | None | Small libraries you don't worry about |
| `light` | File non-empty + container signature (MP4/MKV/FLV/AVI, etc.) | Very low (byte reads) | Recommended for routine sweeps |
| `full` | `light` plus a 5-second `ffmpeg` decode probe | Higher (CPU/time) | Suspect files, or periodic health checks on important libraries |

- Each scan round samples at most 20 assets: never-verified first, then least-recently-verified. Large libraries are naturally spread across rounds.
- Results are stored in the database column `integrity_status` (`0` unchecked / `1` passed / `2` corrupt) and visible on the WebUI asset page.
- **Marks only, never deletes**: corrupt files (including orphans) are kept and flagged; whether to re-download is your decision, based on whether the upstream source still exists.
- `full` requires FFmpeg. If it is missing, that check is marked as failed without interrupting the scan.

---

## 🚀 Usage

### 1. Authorize your account
Regardless of deployment method, credentials must be obtained first:
```bash
python login.py
```
- Supports **QR code login** (recommended, most stable) and **SMS verification**.
- Credentials are stored as plaintext JSON in `./data/cookie.json`, written atomically with best-effort permission restriction, but **not encrypted**.
- `data/` is ignored by Git and Docker builds. Never share this file; if credentials ever enter an image, archive, or public location, log in again to invalidate the old ones.

### 2. Start the daemon
```bash
python main.py --cli
```
The system pulls all favorites and begins downloading. After a round finishes it sleeps (default 21600 seconds, configurable via `system.scan_interval_seconds`), making it suitable for long-running use under `tmux`, `screen`, or `systemd`.

### 3. Start the WebUI
Building the frontend from source requires Node.js 20+; afterwards FastAPI serves the static page and API from the same origin:
```bash
cd webui
npm ci
npm run build
cd ..
python web.py
```
It listens on `127.0.0.1:8000` by default. Listening on a non-loopback address requires a token via environment variable:
```bash
export BILIARCHIVE_WEB_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python web.py --host 0.0.0.0 --port 8000
```
The WebAPI browses assets via SQLite `mode=ro` and never creates or migrates the database. The settings page only edits public allowlisted fields and writes them atomically to the local override config; paths, cookies, and proxy addresses are neither exposed nor modifiable. Restart the core process after saving.

### 4. Issue operational commands from the WebUI (v1.6.0+)

The **Operations** view can dispatch commands to the core engine without SSH:

| Command | Behavior | Notes |
|---|---|---|
| `trigger_scan` | Scan immediately | Skips the remaining sleep; in-flight downloads are not interrupted |
| `redownload_asset` | Re-download one asset | By BV / av ID. Existing local files are not deleted; output follows the normal layout rules and counts toward this round's download budget |
| `restart` | Request a core restart | The core **exits cleanly after the current round and closes the database**, then systemd / Docker / supervisor relaunches it |

The mechanism mirrors `runtime.json` — a local file command channel, no WebSocket:

- The WebUI only atomically writes to `commands.json` in the data directory; it never connects to the daemon directly.
- The daemon polls every 5 seconds and stays interruptible during sleep, so "scan now" does not wait out the full interval.
- Every command is claimed and acknowledged, with up to 50 retained history entries visible under **Execution Audit**.

**Safety boundary (by design, no toggle):**

- **Deleting local assets is never exposed.** Any delete-style command is rejected, including one hand-edited into `commands.json`.
- Asset IDs only accept canonical `BV` / `av` identifiers — not arbitrary strings or file paths — so a command payload can never be used for path traversal.
- Deleting assets or force-overwriting remains a manual terminal operation.
- `restart` is not a suicide restart: if managed by Docker Compose the core container will exit, so confirm your orchestration policy.

### 5. Testing and limiting downloads
To smoke-test the environment without downloading everything, cap this run:
```bash
python main.py --cli --limit 3
```

### 6. Packaging with PyInstaller (optional, no Python required)

The core engine can be packaged as a directory-distributed executable:
```bash
# in an environment with dependencies installed
pip install -r requirements.txt
pip install pyinstaller
venv\Scripts\python.exe -m PyInstaller build.spec --noconfirm

# artifact in dist\BiliArchive-Pro\, smoke test:
dist\BiliArchive-Pro\BiliArchive-Pro.exe --version
```

- The artifact is **one-directory mode**: the whole `dist\BiliArchive-Pro\` directory is required; ship it as a zip.
- At runtime the program switches to the exe's directory; `config.yaml`, `data/`, `downloads/`, and `bin/` (ffmpeg/yt-dlp) sit beside the exe, matching the source layout.
- `login.py` and the WebUI are **not** bundled: login needs terminal QR interaction and the WebUI needs built frontend assets.
- FFmpeg is not embedded: place `ffmpeg.exe` in `bin/` beside the exe, or ensure it is on the system `PATH`.

### 7. Development
```bash
pip install -r requirements-dev.txt
python -m pytest tests
python -m compileall main.py login.py web.py app
cd webui && npm ci && npm run lint && npm run build
```
See [CONTRIBUTING.md](CONTRIBUTING.md) for the full contribution guide and the architectural constraints any change must respect.

---

## 🧾 What's new (v1.6.0)

Full details in [CHANGELOG.md](CHANGELOG.md).

- The WebUI gained an **Operations** view: dispatch `trigger_scan` (scan now), `redownload_asset` (re-download one asset), and `restart` (request a core restart), and inspect each command's acknowledgement and audit trail.
- New local command channel `commands.json` (atomic writes, idempotent claiming, bounded audit) reusing the `runtime.json` philosophy. No WebSocket; the WebUI never connects to the daemon directly.
- Daemon sleep became interruptible polling, so "scan now" no longer waits out the full interval; re-download requests take effect on the next sweep.
- Safety boundary: deleting local assets is **never** exposed, including via a hand-edited `commands.json`; asset IDs accept only canonical BV / av identifiers.
- Backend tests grew from 141 to 197 cases, covering validation, idempotent claiming, audit trails, failure receipts, and injection defenses.

### v1.5.0

- Watch-history metadata sync: `sync_watch_history` records watched videos as a local viewing archive (metadata only), with a `max_history_days` window and incremental rounds.
- Integrity checks: `verify_integrity` in three levels, `light` verifying non-empty files and container signatures, `full` adding an ffmpeg decode probe; at most 20 assets sampled per round, corrupt files are marked, never deleted.
- Old databases migrate new columns automatically; the WebUI asset page surfaces the results.

### v1.4.0

- Full follow-sync: `followings.mode` supports `all` and `list` (any UID, no follow relationship required); dead submissions enter the tombstone / orphan-protection path, and unfollowing keeps local assets.
- New PyInstaller configuration `build.spec` for a Python-free directory distribution.
- Frozen-mode path fix: `main.py` / `login.py` locate the program directory correctly under PyInstaller.
- Security hardening: Bilibili CDN allowlist for article images (SSRF), path-containment checks, `defusedxml` for NFO XML, and allowlisted migration column names.

### Earlier versions

See [CHANGELOG.md](CHANGELOG.md) for v1.3.0 and below (WebUI introduction, Plex sidecar output, retry/timeout reliability, per-page downloads, danmaku rendering, and credential hardening).

---

## 📋 Feature status

### 🟢 Core (implemented)
- [x] **Fully automatic engine**: headless daemon archiving every favorite, or a configured subset
- [x] **Dual login**: terminal QR scan + SMS verification
- [x] **Highest quality downloads**: `yt-dlp`-based 4K/HDR video with automatic audio muxing
- [x] **Plex/Jellyfin metadata**: NFO matching each media file, standard cover art, `Season 01/S01E##` layout for multi-P
- [x] **Article support**: column articles converted to Markdown with images localized
- [x] **Danmaku renderer**: XML → `.ass` with scrolling/reverse/top/bottom tracks and overlap avoidance
- [x] **Asset protection**: tombstone mechanism + orphan protection against upstream deletion
- [x] **Periodic full sweep**: skips archived assets via a local database and refreshes `last_check` every 6 hours by default
- [x] **Component checks**: SHA256-verified `yt-dlp` updates; FFmpeg is probed, never downloaded
- [x] **Docker**: image with FFmpeg and Python plus a `docker-compose.yml` deployment
- [x] **WebUI panel**: overview, asset browsing, allowlisted settings; database read-only, token required for remote listening
- [x] **Operable WebUI**: Operations view for scan/redownload/restart with a local command channel and execution receipts; deleting local assets is never exposed
- [x] **Integrity checks**: sampled `off`/`light`/`full` verification that marks corruption without deleting
- [x] **PyInstaller packaging**: `build.spec` for a directory-distributed executable

### 🟡 Planned
- [ ] **AI summaries**: optional LLM-generated summaries written into NFO `<outline>`
- [ ] **Danmaku word clouds**: locally generated word clouds saved as library artwork
- [ ] **Article submissions for followed creators**: extend `followings` beyond video submissions
- [ ] **Cross-platform release matrix**: win/mac/linux artifacts with checksums

---

## 🤝 Contributing

Issues and pull requests are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for setup, the test requirements, and the architectural boundaries any change must respect (most importantly: **never introduce a path that deletes local assets**).

Security reports: please use [private vulnerability reporting](https://github.com/Stars4422335/BiliArchive-Pro/security/advisories/new) instead of public issues. See [SECURITY.md](SECURITY.md).

## 📄 License

Licensed under the [GNU General Public License v3.0](LICENSE). Modified distributions must remain GPLv3 and provide corresponding source code.

> **Disclaimer**: This project is for personal study, technical research, and private digital asset backup only. Please strictly comply with Bilibili's Terms of Service and respect creators' copyright. **Commercial use or unlawful redistribution of scraped content is strictly prohibited.** Any legal consequences arising from misuse are borne by the user.