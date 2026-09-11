# JLPT Lightning

A private vocabulary learning app built with Django, HTMX, SQLite, and FSRS. Runs on your computer at **http://127.0.0.1:8765**. No account, cloud service, or internet connection is needed for study after setup.

## Run on Windows — uv only

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) if it is not already available. This workspace also supports a standalone copy at `.tools/uv/uv.exe`.

From PowerShell in the project folder:

```powershell
.\scripts\setup.ps1
.\scripts\start.ps1
```

Open **http://127.0.0.1:8765** in your browser. Stop with **Ctrl+C**.

If Windows blocks unsigned PowerShell scripts, use VS Code **Tasks: Run Task → JLPT: Setup (uv)**, then **JLPT: Start app (uv)**. These tasks invoke the workspace's standalone uv executable directly and do not change Windows execution policy.

Setup imports the four supplied workbooks in `data/vocabulary/` (5,736 words), applies database migrations, and prepares local static assets. Running setup again leaves existing datasets alone; update vocabulary through the import preview in Settings → Manage data.

**There is no Conda environment and no project `.venv`.** The scripts use `uv run --isolated --locked --managed-python`: uv manages Python 3.13 under `.tools/python` and temporary package environments under `.tools/uv-cache`. These are generated caches, not source code. No environment activation is needed. Python packages necessarily execute in an environment; uv owns its lifecycle.

`pyproject.toml` declares supported version ranges; **`uv.lock` pins exact releases and hashes**. Normal launches refuse to change the lockfile. Runtime launches omit development dependencies. No `pip install`, Conda, or `uv sync` step is needed.

### VS Code interpreter

The workspace defaults to uv's managed Python at `.tools/python/cpython-3.13-windows-x86_64-none/python.exe`. This points to the installed Python 3.13 patch release. If VS Code remembered a deleted Conda interpreter, run **Python: Select Interpreter → Enter interpreter path** and select that executable; changing the default setting does not always replace an existing selection.

Use **Tasks: Run Task → JLPT: Start app (uv)** to launch the app with its locked dependencies. The plain managed Python executable contains the standard library; application packages live in uv's temporary environments. VS Code's ordinary Run Python File button does not use the app's uv launch workflow.

For Pylance import resolution and completion, setup also runs `scripts/editor.ps1`. It exports the exact `uv.lock` packages and uses `uv pip sync --target` to prepare `.tools/editor-packages`. This is a package directory, not a virtual environment: it contains no interpreter or activation scripts. `.vscode/settings.json` adds it to Pylance's search path. Runtime commands continue to use uv's isolated environments. After changing `uv.lock` or clearing `.tools`, run **JLPT: Refresh editor imports (uv)** or `.\scripts\editor.ps1`, then **Developer: Reload Window** if old diagnostics remain.

For direct commands without the PowerShell wrappers:

```powershell
# Standard uv installation, using its default managed Python and cache locations:
uv python install 3.13
uv run --isolated --locked --managed-python --no-dev python manage.py local setup
uv run --isolated --locked --managed-python --no-dev python manage.py local serve
```

## Study

### Open the app on your phone at home

1. Stop an existing app terminal with **Ctrl+C**.
2. In VS Code, run **Tasks: Run Task → JLPT: Start app on LAN (phone access)**.
3. Connect the phone to the same router's Wi-Fi. Open the address printed as **On your phone**, such as `http://192.168.1.100:8765`. Use `http`, not `https`; `127.0.0.1` only opens the app on the PC itself.

The LAN task listens on loopback and the PC's detected private IPv4 addresses and adds those exact addresses to Django's allowed hosts. It keeps CSRF protection and uses the same database/profile. It does not require GitHub, internet tunneling, or router port forwarding. Leave the PC and app running during mobile study. Restart the task if the PC's IP address changes.

If the phone cannot connect, check that the PC's Ethernet network profile is **Private** under Windows Settings → Network & Internet → Ethernet. Only use that setting for a network you trust. Then open **PowerShell as Administrator** and add this one-time rule:

```powershell
New-NetFirewallRule -Name 'JLPTLightning-LAN-8765' -DisplayName 'JLPT Lightning (private LAN)' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 -Profile Private -RemoteAddress LocalSubnet
```

The rule allows TCP port 8765 from the local subnet on Private networks; it does not enable access on Public networks. These profile/firewall changes are not applied automatically by the app. If you change `--port`, update the firewall rule accordingly. Guest Wi-Fi, VPN routing, or router client isolation can prevent devices from reaching each other.

To stop accepting LAN connections, stop the task and use **JLPT: Start app (uv)** again. To remove the firewall rule, run `Remove-NetFirewallRule -Name 'JLPTLightning-LAN-8765'` in Administrator PowerShell. For PCs with multiple network adapters, the CLI option `--lan --lan-address 192.168.1.100` restricts the LAN listener to one of the detected private addresses.

- **Today:** due reviews, new-word allowance, activity over seven days, and a resumable session.
- **Lessons:** original lessons and batches of up to 20 words. N2/N3 source files label every row “Extra”; the app preserves that grouping.
- **Study:** repeatable flashcards (the default), scheduled reviews, Japanese typing, and meaning quizzes. Choose the level, lesson, and batch explicitly; changing a parent selection resets its dependent choices.
- **Library:** search Japanese/English, bookmark words, tag them, write notes, and group them into personal collections.
- **Settings:** font size, theme, example visibility, direction, ordering, pace, imports, and backups.

Default **Flashcards** sessions always use the selected vocabulary, including completed words and cards suspended from scheduling. They ignore due dates and the daily new-word allowance. The session size still caps the number of cards (20 by default). Use **Continue with this selection** after finishing to study the same batch again. Grades save practice results separately from FSRS, just as typing and quiz scores do.

Choose **Scheduled reviews** for due cards plus eligible new words (10 new words per day by default). That mode can be shorter than a batch or empty when nothing is eligible; the page explains why. Empty sessions preserve any existing resumable session. Starting a nonempty session replaces the previous queue, keeping saved results. A repeated start request opens the same session instead of creating duplicates.

Use **Space** to reveal a flashcard and **1–4** for Again / Hard / Good / Easy. Shortcuts do not intercept typing or Japanese IME composition. Buttons provide the same actions. Every accepted grade is saved atomically, and duplicate requests are safe. Only the latest eligible scheduled review can be undone.

Both card directions have independent schedules. A word consumes the new-word allowance only on its earliest introduction, not when its other direction is introduced. Sibling directions are separated or deferred. The dashboard reports introduced words and actual review events; it does not estimate JLPT pass probability.

Pronunciation uses a **local Japanese device voice**, if the browser supplies one. The control is unavailable when no local Japanese voice exists. No cloud speech service is called. Browser/device pronunciation is not a curated native recording.

## Vocabulary imports

The first worksheet must start with these columns in this order:

```text
serial, lesson, kana, english, example, example_eng
```

Choose `.xlsx`, an explicit level N5–N1, and a stable dataset key such as `jlpt-n5`. Reuse that key and retain serial numbers when updating an existing source. Changing serials creates new source identities; changes in meaning or lesson can be reviewed in the preview before confirmation. Formula cells are rejected, and upload/expanded-size limits apply.

The preview shows additions, exact before/after changes, unchanged rows, missing entries, and source notes. Application takes a backup first and commits all changes together. Missing rows are retained. Existing lesson positions and batches remain stable on reimport; new entries or words moved into another source lesson append to that lesson. Reordering workbook rows alone does not rearrange an established lesson. Duplicate readings are kept as distinct source entries; the app does not infer kanji or combine senses. Personal annotations live separately from source text.

N1 is **supported but empty** until you supply a workbook. The source files have no dedicated kanji spelling field. Examples are displayed as supplied and have not been independently edited. Quiz generation excludes known homophone ambiguity and overlapping semicolon glosses; it cannot guarantee semantic equivalence detection from unstructured English meanings. Typing permits self-assessment for valid variants that do not exactly match the supplied answer.

## Data and backups

The default data location is `%LOCALAPPDATA%\JLPTLightning` on Windows. Set `JLPT_DATA_DIR` before launch to select another **local disk** folder. Do not put the live WAL database on a network share or actively synchronize its files while the app runs.

The folder contains the database, local secret, lock file, rotating logs, and backups. Database backups use SQLite's consistent backup API, with an integrity check. Backups are taken before imports/migrations, and on the first launch of each day. The last seven daily snapshots are retained; manual and pre-change backups remain until you remove them. A snapshot on the same disk is convenient recovery, not protection against disk loss—copy downloaded backups to another disk when desired.

Settings → Manage data offers vocabulary CSV, versioned JSON containing source and learning records, and a full SQLite backup. CSV escapes spreadsheet formula prefixes; JSON and SQLite preserve original text exactly. JSON is an interoperability export; **full restoration uses SQLite backups**.

To restore, stop the app and run:

```powershell
.\scripts\restore.ps1 -Backup 'D:\Backups\manual-20260911-120000.sqlite3'
.\scripts\start.ps1
```

The command validates the file, saves the current database, and restores the backup. A process lock prevents maintenance while the supported launcher is running. Do not use Django's development server for everyday use: `local serve` enforces that lock, handles backup/migration checks, and uses Waitress bound only to loopback.

## Development and verification

```powershell
# Uses installed Microsoft Edge, avoiding a separate browser download:
.\scripts\check.ps1 --browser-channel msedge -p no:cacheprovider

# Or install Playwright Chromium, then run the checks without a channel override:
. .\scripts\uv-common.ps1
& $UvExecutable run --isolated --locked --managed-python playwright install chromium
.\scripts\check.ps1
```

Test data uses `.runtime/checks` when using the wrapper. Tests verify the full supplied corpus, imports and identity preservation, FSRS grades, UTC/Japan day boundaries, rollback, duplicate/stale submissions, undo, suspension, practice isolation, settings/exports, backups, and keyboard/browser flows. Browser tests use a Django test database, not personal progress.

Change dependencies deliberately:

```powershell
. .\scripts\uv-common.ps1
& $UvExecutable lock --upgrade-package django --managed-python
# Review the uv.lock diff and run the full checks before keeping an update.
.\scripts\check.ps1 --browser-channel msedge -p no:cacheprovider
```

Stay on the supported Django 5.2 LTS line. Upgrading FSRS requires schedule compatibility tests and a database backup, because serialized scheduler states and parameters are persisted. Do not regenerate the lockfile at launch or silently upgrade packages on a learner's behalf.

## Structure

`data/vocabulary/` contains the versioned source workbooks. `static/` contains frontend assets; generated assets go into the ignored `staticfiles/` directory. Personal study data and backups live in the application data folder described above.

`learning/catalog.py` handles validated imports and catalog queries; `learning/study.py` owns scheduling and atomic study actions; `learning/storage.py` handles backups and exports. Django views render templates and delegate mutations to those services. Local CSS, small JavaScript modules, and the HTMX asset shipped by `django-htmx` provide the interface without a Node build pipeline.

SQLite uses WAL, foreign keys, FULL synchronous writes, a five-second busy timeout, and short IMMEDIATE transactions. Only revision-keyed catalog summaries are cached in memory. Study pages are `no-store`; versioned static files are served by WhiteNoise. CSRF protection, host validation, escaped text, and a same-origin content security policy remain enabled with `DEBUG=False`.

The app is scoped to **one learner**, with optional access from devices on the same trusted LAN. All devices share the PC's live database and profile; there is no offline synchronization. Public hosting, authentication, kanji enrichment, N1 sourcing, and native mobile packaging are not part of this release.
