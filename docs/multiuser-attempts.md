# Multi-user: attempt history and why this is a branch

This document records the two attempts at multi-user support. The code in this
branch is **attempt #2**; it was **reverted from `main`** and is kept here as a
reference. Attempt #1 reached a different conclusion.

## Attempt #1 — one instance per user (recommended)

The first effort concluded that genuine multi-user support needs **one container
(or process) per user**, not in-process roles. The reasoning:

- The app's trust model is **single-operator**: the browser UI and the Flask
  backend share one trust domain, and the backend deliberately executes code
  (shell actions/hooks/filters, in-process backend plugins).
- A server-side role check protects the **HTTP API**, but not the code the app
  runs. Any action/extension that executes can read and write **every** user's
  files and the admin's dataset.
- Extensions and scripts are written for **one user** (global home paths, a
  single `state`, shared envs, `cwd=<home>`); retrofitting each one is unbounded.
- Therefore the real isolation boundary is the **process/OS**. With one instance
  per user, every instance stays single-user and **no extension or script has to
  change**; shared datasets can be delivered read-only while each instance owns
  its labels.

Costs considered: orchestration, resource usage, shared dataset delivery,
auth/proxy/port management, and admin UX.

## Attempt #2 — roles inside one process (this branch)

What this branch adds:

- account **roles** (admin / restricted) and stable account ids (`users.json`
  v2), with a lone account = admin and no accounts = the local operator;
- per-account **state** behind a `STATE` proxy (`ybe/state.py`) so several users
  can hold different datasets at once, persisted per user (`ybe/userstate.py`);
- **materialised datasets** per restricted user (`ybe/userdata.py`): the admin
  designates a `data.yaml`, images are **symlinked**, labels are written in the
  user's own folder, with a label size cap;
- a per-account **policy** (`ybe/policy.py`) and **run allowlists**
  (`ybe/access.py`), enforced server-side, plus admin **Users / Datasets /
  Access** tabs.

### Why it was reverted

It closed the *HTTP* surface (authoring/installing/running gated by role) but not
the *execution* surface: allowed actions/extensions still run as the same OS user
and can reach other users' data. It also accumulated cross-cutting machinery
(contextvar state proxy, per-user resolvers, policy, provisioning) that reverses
the app's deliberate single-user simplicity, and it cannot realistically be
extended to every existing extension/script.

### What was kept on `main`

Only the changes that stand on their own, without the multi-user authority
model:

- `dataset.parse_dataset()` — a pure parse helper split out of `scan_splits`.
- `apiPost(url, body, {method})` — a general HTTP-helper option.
- a README version sync and a test for `parse_dataset`.

Everything else in this branch is multi-user-specific.

## Recommendation

If multi-user is pursued again, build on **attempt #1**: run **one instance per
user** and keep the app single-user. This branch is a useful inventory of the
per-user dataset/allowlist ideas (materialised symlinked datasets, label caps,
allowlists) that a container-per-user design can reuse at the orchestration
layer instead of inside the process.
