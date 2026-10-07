# Install, update and run

## Install

The installer is **`ybx.py`**, a self-contained Python program (standard library
only). It downloads the latest version, sets up an isolated `.venv`, adds a
`yolo-box-editor` command (with the short alias `ybe`) and then **starts the app
in the background** so it is ready at <http://127.0.0.1:5000> (pass `--no-start`
to skip that; on an upgrade a running instance is restarted). All downloads use
Python's `urllib` — no curl, git or archive tools are needed. The launcher
installs to `~/.local/bin` on Linux/macOS and `%LOCALAPPDATA%\yolo-box-editor\bin`
on Windows (this is added to your `PATH`; open a new terminal to use `ybe`).
Pick whichever bootstrap you have:

```bash
# one-liner (Linux/macOS): curl fetches the thin `ybx.sh` bootstrap, which runs Python
curl -fsSL https://raw.githubusercontent.com/tabebqena/yolo-box-editor/main/ybx.sh | bash -s -- install

# download the Python installer and run it (no bash pipe)
curl -fsSL https://raw.githubusercontent.com/tabebqena/yolo-box-editor/main/ybx.py -o ybx.py
python3 ybx.py install

# entirely from Python (no curl at all)
python3 -c "import urllib.request; open('ybx.py','wb').write(urllib.request.urlopen('https://raw.githubusercontent.com/tabebqena/yolo-box-editor/main/ybx.py').read())"
python3 ybx.py install

# from a clone (offline, uses this checkout)
git clone git@github.com:tabebqena/yolo-box-editor.git
cd yolo-box-editor
./ybx.sh install --from .        # or: python3 ybx.py install --from .
```

On **Windows** (PowerShell) either bootstrap works:

```powershell
# save and run the PowerShell bootstrap
irm https://raw.githubusercontent.com/tabebqena/yolo-box-editor/main/ybx.ps1 -OutFile ybx.ps1
.\ybx.ps1 install

# or run the Python installer directly
py -3 -c "import urllib.request; open('ybx.py','wb').write(urllib.request.urlopen('https://raw.githubusercontent.com/tabebqena/yolo-box-editor/main/ybx.py').read())"
py -3 ybx.py install
```

`ybx.sh` (and `ybx.ps1`) are only thin bootstraps: they find Python and hand off
to `ybx.py`. Once installed, use the **`ybe`** command (also `yolo-box-editor`)
for everything — you never need the installer again:

```bash
ybe version        # print the installed version
ybe check-update   # exit 0 = update available, 1 = current, 2 = unknown
ybe update         # update in place, keeping your files and venv (alias: upgrade)
ybe uninstall      # remove the app, venv and launchers (keeps your files)
```

The installer can also be run directly for the same jobs, plus installing a
specific ref:

```bash
ybx.py install --from .            # install from this checkout
ybx.py update --latest             # latest commit on main (unreleased; no git needed)
ybx.py update --commit 1a2b3c4     # a specific commit (no git needed)
ybx.py uninstall --purge --yes     # remove the whole user folder too
```

`check-update` prints three lines: `exit code:`, `current_version:` and
`latest_version:` (exit 0 = update available, 1 = current, 2 = unknown).

## Start, stop, logs

The app starts **in the background by default**:

```bash
ybe start --data /path/to/data.yaml   # start in the background
ybe status                            # is it running?
ybe logs -f                           # follow the log file
ybe stop                              # stop it
```

`ybe` with no arguments prints a short help. Run it in the foreground (visible
in the terminal) with `ybe start --fg --data /path/to/data.yaml`. While
daemonized, logs are written to `<home>/ybe.log` and the PID to
`<home>/ybe.pid` (both git-ignored); the frequent `/api/presence` heartbeat is
excluded from the log.

## Run without the installer

If you prefer to manage Python yourself, `pip install -r app/requirements.txt`
and run `python app/app.py`:

```bash
python app/app.py --data /path/to/data.yaml
python app/app.py --data /path/to/data.yaml --readonly   # viewer only
python app/app.py --create-user alice                   # register a login user (prompts), exit
python app/app.py --list-users                           # show registered users, then exit
python app/app.py --data /path/to/data.yaml --debug      # verbose browser console
python app/app.py --no-resume                            # Load-a-dataset dialog, no auto-open
python app/app.py --data /path/to/data.yaml --keep-pipe  # keep each run's {PIPE_PATH} file
python app/app.py --data /path/to/data.yaml --keep-filter-pipes  # keep filter-chain pipe files
python app/app.py --data /path/to/data.yaml --home ./my-user-files  # custom user folder
python app/app.py --no-update-check                      # never check GitHub for updates
python app/app.py --flask-debug                          # dev only: Werkzeug debugger + auto-reloader
python app/app.py --data /path/to/data.yaml --log-file ./ybe.log  # log to a file
```

Open <http://127.0.0.1:5000>. You can also leave out `--data`: a **Load a
dataset** dialog opens where you paste the `data.yaml` path and click **Load**
(the same field lives in **Settings → Dataset**) — or just run
`python app/app.py`, which reopens the dataset you used last (add `--no-resume`
to start with the *Load a dataset* dialog instead). The dataset, split, filter
chain, last image and view switches are all restored, so the app comes back as
you left it.

`--debug` writes verbose messages to the **browser console** (prefixed `[ybe]`):
the loaded config, image loads, saves, tag writes, user actions / `after_success`
chains, hook runs, rescans and box edits. It also surfaces uncaught errors and
unhandled promise rejections.

The app ships with a ready-to-use account so `ybe start` works with no extra
setup: sign in as **`admin`** with password **`admin`**, then change the password
in **Settings → Account → Change password** (the current password is required).
**Sign out** ends the session. Accounts can also be managed from the
command line: `--create-user NAME` registers a user (or resets an existing
password) and exits, prompting for the password twice with no echo so it never
reaches the shell history or process list; `--list-users` prints the registered
names.

Accounts are stored as salted hashes (never plaintext) in `users.json` in your
user folder, and the file is owner-only. This is a convenience gate, **not strong
security**: over plain `http://` the password is sent in clear text, and the
default `admin` password is public until you change it. Use it on localhost or a
trusted network, or behind an HTTPS reverse proxy.

## Changelog and releases

`app/CHANGES` holds short per-version notes (`## <version>` sections). On the
first open after installing a new version, the app shows that version's notes in
a **What's new** dialog (once per version, per browser). The full developer
changelog lives in [../CHANGELOG.md](../CHANGELOG.md).

`.github/workflows/release.yml` tags and publishes a GitHub release automatically
when the **major or minor** part of `app/VERSION` changes on `main`. Patch bumps
are left for manual tagging. The release body is the matching `app/CHANGES`
section.

An update (`ybe update`) replaces `<dir>/app/` atomically and refreshes
`<dir>/ybx.py` (the installer updates itself too); your `actions/`, `hooks/`,
`filters/`, `scripts/`, `shortcuts.txt` and the `.venv` are never touched. It
picks the latest GitHub release, else the newest tag, else the `main` branch
(override with `--version <tag|branch|commit>`). To move to unreleased code
instead, use `--latest` or pin one with `--commit <sha>`; both download over
HTTP with Python's `urllib` and need no `git` or `curl`. `uninstall` stops the
app and removes the launchers, `<dir>/app`, `<dir>/.venv` and `<dir>/ybx.py`,
keeping your files; add `--purge --yes` to delete `<dir>` entirely.

## Update notices in the app

The app checks GitHub for a newer version at every start and at most once a
week (the result is cached in `<home>/.update_check.json`). When one is found it
shows a **daily notification** with a **How to update** button, and the same
info lives in **Settings → Updates** (with a manual **Check now**). On
Linux/macOS/Windows that is `ybe update`; for a manual (`pip install`) setup it
is `git pull` then `pip install -r app/requirements.txt`. Disable the check with
`--no-update-check`.
