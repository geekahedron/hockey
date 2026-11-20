<?php
/* Ask the existing publish job for today's lists, at most once per 10 minutes.
   The Tims credentials stay in ~/tims-hockey/secrets. This script never
   receives them and never submits a pick. A current today.json is a no-op. */

function hockey_toronto_today($moment = null)
{
    $tz = new DateTimeZone("America/Toronto");
    if ($moment instanceof DateTimeInterface) {
        $stamp = new DateTimeImmutable("@" . $moment->getTimestamp());
        return $stamp->setTimezone($tz)->format("Y-m-d");
    }
    return (new DateTimeImmutable("now", $tz))->format("Y-m-d");
}

function hockey_refresh_decision($fileDate, $toronto, $lastRun, $now, $interval = 600)
{
    if ($fileDate !== "" && $fileDate === $toronto) {
        return "current";
    }
    if ($lastRun !== null && ($now - $lastRun) < $interval) {
        return "limited";
    }
    return "run";
}

function hockey_json_date($path)
{
    if (!is_file($path)) {
        return "";
    }
    $raw = file_get_contents($path);
    if ($raw === false) {
        return "";
    }
    $doc = json_decode($raw, true);
    if (!is_array($doc)) {
        return "";
    }
    $date = isset($doc["date"]) ? (string) $doc["date"] : "";
    return preg_match("/^\d{4}-\d{2}-\d{2}/", $date) ? substr($date, 0, 10) : "";
}

function hockey_home()
{
    $home = getenv("HOME");
    if (is_string($home) && $home !== "") {
        return $home;
    }
    if (function_exists("posix_getpwuid")) {
        $info = posix_getpwuid(posix_geteuid());
        if (is_array($info) && !empty($info["dir"])) {
            return $info["dir"];
        }
    }
    return "";
}

function hockey_root()
{
    $override = getenv("HOCKEY_ROOT");
    if (is_string($override) && $override !== "" && is_file($override . "/job/run_daily.py")) {
        return $override;
    }
    $dir = __DIR__;
    for ($i = 0; $i < 6; $i++) {
        if (is_file($dir . "/job/run_daily.py")) {
            return $dir;
        }
        $parent = dirname($dir);
        if ($parent === $dir) {
            break;
        }
        $dir = $parent;
    }
    $home = hockey_home();
    if ($home !== "" && is_file($home . "/tims-hockey/job/run_daily.py")) {
        return $home . "/tims-hockey";
    }
    return "";
}

function hockey_web_data()
{
    $override = getenv("HOCKEY_WEB_DATA");
    if (is_string($override) && $override !== "") {
        return $override;
    }
    return __DIR__ . "/data";
}

function hockey_respond($status, $date)
{
    if (!headers_sent()) {
        header("Content-Type: application/json; charset=utf-8");
        header("Cache-Control: no-store");
    }
    echo json_encode(array("status" => $status, "date" => $date));
}

function hockey_read_stamp($path)
{
    if (!is_file($path)) {
        return null;
    }
    $text = trim((string) file_get_contents($path));
    if ($text === "" || !preg_match("/^\d+$/", $text)) {
        return null;
    }
    return (int) $text;
}

function hockey_publish_date($publish)
{
    return hockey_json_date($publish . "/today.json");
}

function hockey_sync_web($publish, $web)
{
    if ($publish === "" || $web === "") {
        return false;
    }
    if (!is_dir($web) && !mkdir($web, 0755, true)) {
        return false;
    }
    $cmd = "rsync -a --delete --exclude " . escapeshellarg("/seasons/") . " "
        . escapeshellarg(rtrim($publish, "/") . "/") . " "
        . escapeshellarg(rtrim($web, "/") . "/");
    $code = 1;
    $out = array();
    exec($cmd, $out, $code);
    return $code === 0;
}

function hockey_python()
{
    $python = getenv("HOCKEY_PYTHON");
    if (is_string($python) && $python !== "") {
        return $python;
    }
    $home = hockey_home();
    $venv = $home !== "" ? $home . "/tims-venv/bin/python" : "";
    if ($venv !== "" && is_executable($venv)) {
        return $venv;
    }
    return "python3";
}

function hockey_write_manifest($root, $publish)
{
    $cmd = "PYTHONPATH=" . escapeshellarg($root) . " " . escapeshellarg(hockey_python())
        . " -c " . escapeshellarg("import sys\nfrom job.publish import write_seasons_manifest\nwrite_seasons_manifest(sys.argv[1])\n")
        . " " . escapeshellarg($publish);
    $ignored = array();
    $code = 1;
    exec($cmd, $ignored, $code);
    return $code === 0;
}

function hockey_run_publish($root, $publish)
{
    $python = hockey_python();
    $logDir = $root . "/logs";
    if (!is_dir($logDir)) {
        mkdir($logDir, 0755, true);
    }
    $cmd = escapeshellarg($python) . " " . escapeshellarg($root . "/job/run_daily.py")
        . " --publish " . escapeshellarg($publish)
        . " --log " . escapeshellarg($logDir . "/daily.log");
    $env = array(
        "TIMS_ENV" => $root . "/secrets/tims.env",
        "HOME" => hockey_home() !== "" ? hockey_home() : $root,
        "PATH" => getenv("PATH") ? getenv("PATH") : "/usr/bin:/bin",
    );
    $spec = array(0 => array("pipe", "r"), 1 => array("pipe", "w"), 2 => array("pipe", "w"));
    $pipes = array();
    $proc = proc_open($cmd, $spec, $pipes, $root, $env);
    if (!is_resource($proc)) {
        return 1;
    }
    fclose($pipes[0]);
    stream_get_contents($pipes[1]);
    stream_get_contents($pipes[2]);
    fclose($pipes[1]);
    fclose($pipes[2]);
    return proc_close($proc);
}

function hockey_refresh_main()
{
    $method = isset($_SERVER["REQUEST_METHOD"]) ? $_SERVER["REQUEST_METHOD"] : "GET";
    if ($method !== "POST") {
        if (!headers_sent()) {
            header("Allow: POST");
            http_response_code(405);
        }
        hockey_respond("error", "");
        return;
    }
    $root = hockey_root();
    $publish = $root !== "" ? $root . "/publish" : "";
    $web = hockey_web_data();
    $shown = hockey_publish_date($publish);
    if ($shown === "") {
        $shown = hockey_json_date($web . "/today.json");
    }
    $toronto = hockey_toronto_today();
    if ($root === "" || $publish === "") {
        hockey_respond("error", $shown);
        return;
    }
    $logDir = $root . "/logs";
    if (!is_dir($logDir)) {
        mkdir($logDir, 0755, true);
    }
    $lockPath = $logDir . "/page-refresh.lock";
    $lock = fopen($lockPath, "c");
    if ($lock === false || !flock($lock, LOCK_EX)) {
        if (is_resource($lock)) {
            fclose($lock);
        }
        hockey_respond("busy", $shown);
        return;
    }
    $shown = hockey_publish_date($publish);
    $webDate = hockey_json_date($web . "/today.json");
    $toronto = hockey_toronto_today();
    if ($webDate === $toronto) {
        flock($lock, LOCK_UN);
        fclose($lock);
        hockey_respond("current", $toronto);
        return;
    }
    if ($shown === $toronto) {
        hockey_sync_web($publish, $web);
        flock($lock, LOCK_UN);
        fclose($lock);
        hockey_respond("current", $toronto);
        return;
    }
    if ($shown === "") {
        $shown = $webDate;
    }
    $now = time();
    $stampPath = $logDir . "/page-refresh.at";
    $last = hockey_read_stamp($stampPath);
    if (hockey_refresh_decision($shown, $toronto, $last, $now) === "limited") {
        flock($lock, LOCK_UN);
        fclose($lock);
        hockey_respond("limited", $shown);
        return;
    }
    file_put_contents($stampPath, (string) $now);
    $code = hockey_run_publish($root, $publish);
    if ($code === 0 || $code === 75) {
        hockey_write_manifest($root, $publish);
        hockey_sync_web($publish, $web);
    }
    $after = hockey_json_date($web . "/today.json");
    if ($after === "") {
        $after = hockey_publish_date($publish);
    }
    flock($lock, LOCK_UN);
    fclose($lock);
    if ($after === $toronto) {
        hockey_respond("updated", $after);
        return;
    }
    if ($code === 75 || $code === 0) {
        hockey_respond("not_ready", $after);
        return;
    }
    hockey_respond("error", $after);
}

if (!defined("HOCKEY_REFRESH_LIB")) {
    hockey_refresh_main();
}
