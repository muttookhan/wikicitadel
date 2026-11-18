#!/usr/bin/env python3
"""wiki_openrefine_trial.py — OpenRefine bench trial (headless).

Marathon R10 lane BB (ideas board R8 research, Tier A): OpenRefine
(BSD-3-Clause) as an EXTERNAL bench tool on the Kopia precedent
(Round 9). The tool lives OUTSIDE the trees; never vendored; no
runtime dependency added. This wrapper runs a bounded headless
trial against a COPY of a tabular/bibliographic working file
(never an in-tree original): starts the refine server on a
throwaway port with a throwaway workspace, creates a project
from the copy, applies an operations JSON file, exports the
cleaned rows AND the operation history (get-operations), and
writes an evidence JSON: input hash, operations applied, output
hash, history artefact location. If the binary/Java cannot be
obtained or run, the evidence records the exact door failure —
a door failure is a statement about the door, never a trial
result; an unrun trial is never claimed as run.

Usage:
  run --refine PATH --input COPY --operations OPS.json
      --work DIR --evidence FILE [--port N]
Exit 0 trial ran, evidence written; 2 door failure (evidence
still written). Stdlib only.
"""
import argparse, hashlib, json, re, subprocess, sys
import time, urllib.parse, urllib.request, uuid
from http.cookiejar import CookieJar
_OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(CookieJar()))
from pathlib import Path


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _post(url, fields, files=None):
    boundary = "----bb" + uuid.uuid4().hex
    body = b""
    for k, v in fields.items():
        body += (f"--{boundary}\r\nContent-Disposition: "
                 f"form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode()
    for k, (fn, data) in (files or {}).items():
        body += (f"--{boundary}\r\nContent-Disposition: form-data;"
                 f" name=\"{k}\"; filename=\"{fn}\"\r\n"
                 f"Content-Type: text/csv\r\n\r\n").encode()
        body += data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        url, data=body, headers={
            "Content-Type": f"multipart/form-data; "
                            f"boundary={boundary}"})
    with _OPENER.open(req, timeout=60) as r:
        return r.geturl() + "\n" + r.read().decode(
            "utf-8", "replace")


def _get(url):
    with _OPENER.open(url, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def _post_form(url, fields):
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/x-www-form-urlencoded"})
    with _OPENER.open(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--refine", required=True)
    r.add_argument("--input", required=True)
    r.add_argument("--operations", required=True)
    r.add_argument("--work", required=True)
    r.add_argument("--evidence", required=True)
    r.add_argument("--port", type=int, default=3343)
    a = ap.parse_args(argv)
    ev = {"tool": "openrefine-bench-trial", "ran": False}
    refine, inp = Path(a.refine), Path(a.input)
    if not refine.is_file():
        ev["door_failure"] = {"stage": "obtain",
            "error": f"refine binary not found: {refine}"}
        Path(a.evidence).write_text(json.dumps(ev, indent=2) + "\n")
        return 2
    if not inp.is_file():
        ev["door_failure"] = {"stage": "input",
            "error": f"input copy not found: {inp}"}
        Path(a.evidence).write_text(json.dumps(ev, indent=2) + "\n")
        return 2
    work = Path(a.work); work.mkdir(parents=True, exist_ok=True)
    ops = json.loads(Path(a.operations).read_text(encoding="utf-8"))
    ev.update({"input": str(inp), "input_sha256": sha256(inp),
               "operations": ops})
    proc = subprocess.Popen(
        [str(refine), "-p", str(a.port), "-d", str(work / "ws"),
         "-x", "refine.headless=true"],
        stdout=open(work / "server.log", "wb"),
        stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{a.port}"
    try:
        for _ in range(90):
            try:
                _get(base + "/"); break
            except Exception:
                if proc.poll() is not None:
                    raise RuntimeError(
                        f"refine exited rc={proc.returncode}; "
                        f"see {work}/server.log")
                time.sleep(1)
        else:
            raise RuntimeError("server did not come up in 90s")
        token = json.loads(_get(base + "/command/core/"
                                "get-csrf-token"))["token"]
        csrf = {"csrf_token": token}
        resp = _post(base + "/command/core/"
                     "create-project-from-upload"
                     f"?csrf_token={token}",
                     {**csrf, "project-name": "bb-trial",
                      "format": "text/line-based/*sv"},
                     {"project-file": (inp.name,
                                        inp.read_bytes())})
        m = re.search(r"project=([0-9]+)", resp) or \
            re.search(r'"projectID"\s*:\s*"?([0-9]+)', resp)
        if not m:
            raise RuntimeError("create-project response carried "
                               f"no project id: {resp[:300]!r}")
        pid = m.group(1)
        ev["project_id"] = pid
        _post_form(base + "/command/core/apply-operations"
                   f"?csrf_token={token}&project={pid}",
                   {"operations": json.dumps(ops)})
        hist = _get(base + "/command/core/get-operations"
                    f"?project={pid}")
        (work / "history.json").write_text(hist, encoding="utf-8")
        cleaned = _post_form(base + "/command/core/export-rows"
                             f"?csrf_token={token}&project={pid}",
                             {"format": "csv",
                              "engine": json.dumps(
                                  {"facets": [],
                                   "mode": "row-based"})})
        (work / "cleaned.csv").write_text(cleaned,
                                          encoding="utf-8")
        _post_form(base + "/command/core/delete-project"
                   f"?csrf_token={token}&project={pid}", {})
        ev.update({"ran": True,
                   "output": str(work / "cleaned.csv"),
                   "output_sha256": sha256(work / "cleaned.csv"),
                   "history_artefact": str(work / "history.json"),
                   "history_sha256": sha256(work / "history.json")})
        Path(a.evidence).write_text(json.dumps(ev, indent=2) + "\n")
        return 0
    except Exception as e:
        ev["door_failure"] = {"stage": "run",
                              "error": f"{type(e).__name__}: {e}"}
        Path(a.evidence).write_text(json.dumps(ev, indent=2) + "\n")
        return 2
    finally:
        proc.terminate()
        try: proc.wait(timeout=10)
        except Exception: proc.kill()


if __name__ == "__main__":
    sys.exit(main())
