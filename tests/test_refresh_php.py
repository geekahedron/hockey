"""The page refresh endpoint is read-only and will not hammer Tims."""
import os
import shutil
import subprocess
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHP = os.path.join(ROOT, "web", "refresh.php")


def test_refresh_script_stays_read_only():
    text = open(PHP, encoding="utf-8").read()
    assert "run_daily.py" in text
    assert "page-refresh.lock" in text
    assert "page-refresh.at" in text
    assert "page-refresh.json" in text
    assert "https://api-web.nhle.com/v1/score/" in text
    assert "no_games" in text
    assert '$_POST["refresh"]' in text
    assert "hockey_accepts_refresh" in text
    assert "TIMS_ENV" in text
    assert "escapeshellarg" in text
    assert "SubmitHockey" not in text
    assert "REFRESH_TOKEN" not in text
    assert "600" in text
    for name in ("hockey_toronto_today", "hockey_refresh_decision"):
        assert "function " + name in text


def test_refresh_decision_and_toronto_date():
    php = shutil.which("php")
    assert php, "php is required"
    lint = subprocess.run([php, "-l", PHP], capture_output=True, text=True)
    assert lint.returncode == 0, lint.stdout + lint.stderr
    script = textwrap.dedent(
        """\
        <?php
        define("HOCKEY_REFRESH_LIB", true);
        require %s;
        $_SERVER["REQUEST_METHOD"] = "GET";
        ob_start();
        hockey_refresh_main();
        $body = ob_get_clean();
        if ($body !== '{"status":"error","date":""}') {
            fwrite(STDERR, $body);
            exit(1);
        }
        $utc = new DateTimeZone("UTC");
        $morning = new DateTimeImmutable("2026-11-20 11:23:00", $utc);
        if (hockey_toronto_today($morning) !== "2026-11-20") exit(2);
        $late = new DateTimeImmutable("2026-11-20 04:30:00", $utc);
        if (hockey_toronto_today($late) !== "2026-11-19") exit(3);
        if (hockey_refresh_decision("2026-11-20", "2026-11-20", null, 1000) !== "current") exit(4);
        if (hockey_refresh_decision("2026-11-19", "2026-11-20", null, 1000) !== "run") exit(5);
        if (hockey_refresh_decision("2026-11-19", "2026-11-20", 500, 1000) !== "limited") exit(6);
        if (hockey_refresh_decision("2026-11-19", "2026-11-20", 400, 1000) !== "run") exit(7);
        if (hockey_refresh_decision("", "2026-11-20", null, 1000) !== "run") exit(8);
        $none = array("games" => array());
        $one = array("games" => array(array("gameState" => "FUT", "gameScheduleState" => "OK")));
        $off = array("games" => array(array("gameState" => "PPD", "gameScheduleState" => "PPD")));
        if (hockey_count_games($none) !== 0) exit(9);
        if (hockey_count_games($one) !== 1) exit(10);
        if (hockey_count_games($off) !== 0) exit(11);
        if (hockey_count_games(null) !== null) exit(12);
        if (hockey_gap_status(0) !== "no_games") exit(13);
        if (hockey_gap_status(2) !== "not_ready") exit(14);
        if (hockey_gap_status(null) !== "not_ready") exit(15);
        $cached = array("date" => "2026-11-20", "status" => "no_games");
        if (hockey_cached_gap($cached, "2026-11-20") !== "no_games") exit(16);
        if (hockey_cached_gap($cached, "2026-11-21") !== "not_ready") exit(17);
        if (hockey_cached_gap(null, "2026-11-20") !== "not_ready") exit(18);
        if (hockey_score_url("2026-11-20") !== "https://api-web.nhle.com/v1/score/2026-11-20") exit(19);
        if (!hockey_accepts_refresh("POST", "1")) exit(20);
        if (hockey_accepts_refresh("POST", "")) exit(21);
        if (hockey_accepts_refresh("GET", "1")) exit(22);
        $_SERVER["REQUEST_METHOD"] = "POST";
        $_POST = array();
        ob_start();
        hockey_refresh_main();
        $empty = ob_get_clean();
        if ($empty !== '{"status":"error","date":""}') {
            fwrite(STDERR, $empty);
            exit(23);
        }
        """
        % repr(PHP)
    )
    proc = subprocess.run([php], input=script, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr + "\ncode " + str(proc.returncode)
