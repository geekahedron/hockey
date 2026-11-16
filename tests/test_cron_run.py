"""The hourly wrapper, with a fake clock and a fake Python. No live Tims."""
import json
import os
import stat
import subprocess


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "job", "cron_run.sh")


def _home(tmp_path, hour, today_doc=None, exit_code=75):
    home = tmp_path / "home"
    bindir = home / "tims-venv" / "bin"
    bindir.mkdir(parents=True)
    publish = home / "tims-hockey" / "publish"
    publish.mkdir(parents=True)
    (publish / "marker.txt").write_text("published")
    (home / "public_html" / "tools" / "hockey" / "data").mkdir(parents=True)
    if today_doc is not None:
        (publish / "today.json").write_text(today_doc)
    py = bindir / "python"
    py.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"-c\" ]; then\n"
        "  exec /usr/bin/python3 -c \"$2\" \"$3\"\n"
        "fi\n"
        "mkdir -p \"$HOME/tims-hockey/logs\"\n"
        "echo \"$@\" >> \"$HOME/tims-hockey/logs/python.args\"\n"
        "exit %d\n" % exit_code
    )
    py.chmod(py.stat().st_mode | stat.S_IEXEC)
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    date_bin = fakes / "date"
    date_bin.write_text(
        "#!/bin/sh\n"
        "hour=\"${CRON_TEST_HOUR:-03}\"\n"
        "day=\"${CRON_TEST_DATE:-2026-11-15}\"\n"
        "case \"$1\" in\n"
        "  +%H) printf '%s\\n' \"$hour\" ;;\n"
        "  +%Y-%m-%d) printf '%s\\n' \"$day\" ;;\n"
        "  '+%Y-%m-%d %H:%M:%S') printf '%s 03:05:00\\n' \"$day\" ;;\n"
        "  *) printf '%s\\n' \"$day\" ;;\n"
        "esac\n"
    )
    date_bin.chmod(date_bin.stat().st_mode | stat.S_IEXEC)
    rsync_bin = fakes / "rsync"
    rsync_bin.write_text(
        "#!/usr/bin/env python3\n"
        "import os, shutil, sys\n"
        "args = sys.argv[1:]\n"
        "delete = False\n"
        "excludes = []\n"
        "paths = []\n"
        "i = 0\n"
        "while i < len(args):\n"
        "    arg = args[i]\n"
        "    if arg == '--delete':\n"
        "        delete = True\n"
        "    elif arg == '--exclude':\n"
        "        i += 1\n"
        "        excludes.append(args[i])\n"
        "    elif arg.startswith('--exclude='):\n"
        "        excludes.append(arg.split('=', 1)[1])\n"
        "    elif arg.startswith('-'):\n"
        "        pass\n"
        "    else:\n"
        "        paths.append(arg)\n"
        "    i += 1\n"
        "src, dest = paths[0].rstrip('/'), paths[1].rstrip('/')\n"
        "logdir = os.path.join(os.environ['HOME'], 'tims-hockey', 'logs')\n"
        "os.makedirs(logdir, exist_ok=True)\n"
        "with open(os.path.join(logdir, 'rsync.args'), 'w') as handle:\n"
        "    handle.write('\\n'.join(args) + '\\n')\n"
        "def excluded(rel):\n"
        "    rel = rel.strip('/')\n"
        "    for pat in excludes:\n"
        "        anchored = pat.startswith('/')\n"
        "        name = pat.strip('/')\n"
        "        if not name:\n"
        "            continue\n"
        "        if anchored and (rel == name or rel.startswith(name + '/')):\n"
        "            return True\n"
        "        if not anchored and (rel == name or rel.startswith(name + '/') or ('/' + name + '/') in ('/' + rel + '/')):\n"
        "            return True\n"
        "    return False\n"
        "os.makedirs(dest, exist_ok=True)\n"
        "for dirpath, dirnames, filenames in os.walk(src):\n"
        "    rel = os.path.relpath(dirpath, src)\n"
        "    rel = '' if rel == '.' else rel\n"
        "    kept = []\n"
        "    for name in dirnames:\n"
        "        child = (rel + '/' + name).strip('/')\n"
        "        if not excluded(child):\n"
        "            kept.append(name)\n"
        "    dirnames[:] = kept\n"
        "    for name in filenames:\n"
        "        child = (rel + '/' + name).strip('/')\n"
        "        if excluded(child):\n"
        "            continue\n"
        "        target = dest if not rel else os.path.join(dest, rel)\n"
        "        os.makedirs(target, exist_ok=True)\n"
        "        shutil.copy2(os.path.join(dirpath, name), os.path.join(target, name))\n"
        "if delete:\n"
        "    for dirpath, dirnames, filenames in os.walk(dest, topdown=False):\n"
        "        rel = os.path.relpath(dirpath, dest)\n"
        "        rel = '' if rel == '.' else rel\n"
        "        for name in list(filenames):\n"
        "            child = (rel + '/' + name).strip('/')\n"
        "            if excluded(child):\n"
        "                continue\n"
        "            if not os.path.isfile(os.path.join(src, child)):\n"
        "                os.remove(os.path.join(dirpath, name))\n"
        "        for name in list(dirnames):\n"
        "            child = (rel + '/' + name).strip('/')\n"
        "            if excluded(child):\n"
        "                continue\n"
        "            dest_dir = os.path.join(dirpath, name)\n"
        "            if not os.path.isdir(os.path.join(src, child)) and not os.listdir(dest_dir):\n"
        "                os.rmdir(dest_dir)\n"
    )
    rsync_bin.chmod(rsync_bin.stat().st_mode | stat.S_IEXEC)
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = "%s:/usr/bin:/bin" % fakes
    env["CRON_TEST_HOUR"] = hour
    env["CRON_TEST_DATE"] = "2026-11-15"
    return home, env


def _run(env):
    return subprocess.run(
        ["/bin/sh", SCRIPT],
        env=env,
        capture_output=True,
        text=True,
    )


def test_wrapper_skips_outside_the_toronto_window(tmp_path):
    home, env = _home(tmp_path, "02")
    proc = _run(env)
    assert proc.returncode == 0
    log = (home / "tims-hockey" / "logs" / "cron.log").read_text()
    assert "skip hour 2" in log
    assert not (home / "tims-hockey" / "logs" / "python.args").exists()


def test_wrapper_retries_a_not_ready_slate_and_rsyncs(tmp_path):
    home, env = _home(tmp_path, "03", exit_code=75)
    proc = _run(env)
    assert proc.returncode == 75
    assert (home / "public_html" / "tools" / "hockey" / "data" / "marker.txt").read_text() == "published"
    log = (home / "tims-hockey" / "logs" / "cron.log").read_text().strip().splitlines()
    assert len(log) == 1
    assert "exit 75 rsync" in log[0]


def test_wrapper_skips_when_today_is_already_graded(tmp_path):
    home, env = _home(
        tmp_path,
        "09",
        today_doc='{"date": "2026-11-15", "status": "graded"}\n',
        exit_code=0,
    )
    proc = _run(env)
    assert proc.returncode == 0
    log = (home / "tims-hockey" / "logs" / "cron.log").read_text()
    assert "skip today graded" in log
    assert not (home / "tims-hockey" / "logs" / "python.args").exists()


def test_wrapper_runs_when_today_is_still_pending(tmp_path):
    home, env = _home(
        tmp_path,
        "13",
        today_doc='{"date": "2026-11-15", "status": "pending"}\n',
        exit_code=0,
    )
    proc = _run(env)
    assert proc.returncode == 0
    assert (home / "tims-hockey" / "logs" / "python.args").exists()
    log = (home / "tims-hockey" / "logs" / "cron.log").read_text()
    assert "exit 0 rsync" in log


def test_wrapper_rsync_keeps_the_backtest_tree(tmp_path):
    home, env = _home(tmp_path, "03", exit_code=0)
    web = home / "public_html" / "tools" / "hockey" / "data"
    kept = web / "seasons" / "2025-26"
    kept.mkdir(parents=True)
    (kept / "season.json").write_text('{"kept": true}\n')
    (kept / "days").mkdir()
    (kept / "days" / "index.json").write_text('{"days": []}\n')
    (web / "stray.txt").write_text("gone")
    publish = home / "tims-hockey" / "publish"
    planted = publish / "seasons" / "2025-26"
    planted.mkdir(parents=True)
    (planted / "season.json").write_text('{"from": "publish"}\n')
    proc = _run(env)
    assert proc.returncode == 0, proc.stderr
    assert (kept / "season.json").read_text() == '{"kept": true}\n'
    assert (kept / "days" / "index.json").read_text() == '{"days": []}\n'
    assert not (web / "stray.txt").exists()
    manifest = json.loads((web / "seasons.json").read_text())
    assert [row["id"] for row in manifest] == ["2026-27", "2025-26"]
    assert manifest[0]["base"] == "data/"
    assert manifest[1]["base"] == "data/seasons/2025-26/"
    assert manifest[1]["backtest"] is True
    args = (home / "tims-hockey" / "logs" / "rsync.args").read_text().splitlines()
    assert "--delete" in args
    assert "--exclude" in args
    assert "/seasons/" in args
    assert (publish / "marker.txt").read_text() == "published"
    assert (web / "marker.txt").read_text() == "published"


def test_real_rsync_exclude_does_not_touch_seasons(tmp_path):
    text = open(SCRIPT).read()
    assert "rsync -a --delete --exclude '/seasons/'" in text
    src = tmp_path / "publish"
    dest = tmp_path / "data"
    (src / "seasons" / "2025-26").mkdir(parents=True)
    (src / "seasons" / "2025-26" / "season.json").write_text('{"from": "publish"}\n')
    (src / "today.json").write_text('{"date": "2026-11-15"}\n')
    (src / "seasons.json").write_text('[{"id": "2026-27"}]\n')
    kept = dest / "seasons" / "2025-26"
    kept.mkdir(parents=True)
    (kept / "season.json").write_text('{"kept": true}\n')
    (kept / "days").mkdir()
    (kept / "days" / "2025-10-07.json").write_text("{}\n")
    (dest / "stray.txt").write_text("gone")
    (dest / "old.json").write_text("{}\n")
    proc = subprocess.run(
        ["rsync", "-a", "--delete", "--exclude", "/seasons/", str(src) + "/", str(dest) + "/"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert (kept / "season.json").read_text() == '{"kept": true}\n'
    assert (kept / "days" / "2025-10-07.json").read_text() == "{}\n"
    assert not (dest / "stray.txt").exists()
    assert not (dest / "old.json").exists()
    assert (dest / "today.json").is_file()
    assert (dest / "seasons.json").is_file()
    assert not (dest / "seasons" / "2025-26" / "from-publish").exists()


def test_wrapper_does_not_rsync_a_hard_error(tmp_path):
    home, env = _home(tmp_path, "04", exit_code=1)
    proc = _run(env)
    assert proc.returncode == 1
    assert not (home / "public_html" / "tools" / "hockey" / "data" / "marker.txt").exists()
    log = (home / "tims-hockey" / "logs" / "cron.log").read_text()
    assert "exit 1" in log
    assert "rsync" not in log
