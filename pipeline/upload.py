"""YouTube Data API v3 upload with plain urllib (no google client libs).

Setup once (only the account owner can do this):
  1. Google Cloud project -> enable "YouTube Data API v3" -> OAuth client (Desktop app) -> download client_secret.json
     to ~/.nordic-ledger/client_secret.json
  2. python3 pipeline/upload.py --auth   (opens a URL; paste the code)  -> token saved to ~/.nordic-ledger/token.json
Note: videos uploaded through an *unverified* API project are forced to private until Google's API audit passes.
Until then, run.py falls back to writing an upload package for browser upload (see run.py --package).
"""
from __future__ import annotations
import json, os, sys, time, urllib.request, urllib.parse, urllib.error, webbrowser
from pathlib import Path

CONF = Path(os.environ.get("NL_HOME", Path.home() / ".nordic-ledger"))
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube"


def _post(url, data=None, headers=None, raw=None, method="POST"):
    body = raw if raw is not None else (urllib.parse.urlencode(data).encode() if data else None)
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.status, dict(r.headers), r.read()


def auth():
    cs = json.loads((CONF / "client_secret.json").read_text())["installed"]
    url = ("https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": cs["client_id"], "redirect_uri": "urn:ietf:wg:oauth:2.0:oob", "response_type": "code",
        "scope": SCOPES, "access_type": "offline", "prompt": "consent"}))
    print("Open this URL, approve, paste the code:\n", url); webbrowser.open(url)
    code = input("code: ").strip()
    _, _, b = _post("https://oauth2.googleapis.com/token", {"code": code, "client_id": cs["client_id"], "client_secret": cs["client_secret"],
                                                           "redirect_uri": "urn:ietf:wg:oauth:2.0:oob", "grant_type": "authorization_code"})
    tok = json.loads(b); tok["obtained"] = time.time()
    (CONF / "token.json").write_text(json.dumps(tok)); print("token saved")


def access_token():
    cs = json.loads((CONF / "client_secret.json").read_text())["installed"]
    tok = json.loads((CONF / "token.json").read_text())
    if time.time() - tok.get("obtained", 0) > tok.get("expires_in", 3600) - 120:
        _, _, b = _post("https://oauth2.googleapis.com/token", {"refresh_token": tok["refresh_token"], "client_id": cs["client_id"],
                                                               "client_secret": cs["client_secret"], "grant_type": "refresh_token"})
        new = json.loads(b); tok.update(new); tok["obtained"] = time.time(); (CONF / "token.json").write_text(json.dumps(tok))
    return tok["access_token"]


def upload_video(mp4: Path, meta: dict, publish_at_iso: str | None = None) -> str:
    at = access_token()
    status = {"privacyStatus": meta.get("privacyStatus", "private"), "selfDeclaredMadeForKids": False,
              "containsSyntheticMedia": bool(meta.get("containsSyntheticMedia", False))}
    if publish_at_iso: status["privacyStatus"] = "private"; status["publishAt"] = publish_at_iso
    body = json.dumps({"snippet": {"title": meta["title"][:100], "description": meta["description"], "tags": meta.get("tags", []),
                                   "categoryId": meta.get("categoryId", "27"), "defaultLanguage": "en", "defaultAudioLanguage": "en"},
                       "status": status}).encode()
    size = mp4.stat().st_size
    st, hdrs, _ = _post("https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status", raw=body,
                        headers={"Authorization": f"Bearer {at}", "Content-Type": "application/json; charset=UTF-8",
                                 "X-Upload-Content-Length": str(size), "X-Upload-Content-Type": "video/mp4"})
    loc = hdrs.get("Location") or hdrs.get("location")
    chunk = 32 * 1024 * 1024; sent = 0
    with open(mp4, "rb") as f:
        while sent < size:
            data = f.read(chunk); end = sent + len(data) - 1
            for attempt in range(5):
                try:
                    req = urllib.request.Request(loc, data=data, method="PUT", headers={
                        "Authorization": f"Bearer {access_token()}", "Content-Length": str(len(data)),
                        "Content-Range": f"bytes {sent}-{end}/{size}"})
                    with urllib.request.urlopen(req, timeout=600) as r:
                        resp = r.read()
                        if r.status in (200, 201): return json.loads(resp)["id"]
                    break
                except urllib.error.HTTPError as e:
                    if e.code == 308: break  # resume incomplete: continue with next chunk
                    if e.code in (500, 502, 503, 504) and attempt < 4: time.sleep(2 ** attempt); continue
                    raise
            sent = end + 1
            print(f"  uploaded {sent/size:.0%}", file=sys.stderr)
    raise RuntimeError("upload ended without video id")


def set_thumbnail(video_id: str, jpg: Path):
    at = access_token()
    _post(f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={video_id}", raw=jpg.read_bytes(),
          headers={"Authorization": f"Bearer {at}", "Content-Type": "image/jpeg"})


def add_captions(video_id: str, srt: Path):
    at = access_token(); boundary = "nlbound"
    meta = json.dumps({"snippet": {"videoId": video_id, "language": "en", "name": "English", "isDraft": False}})
    body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta}\r\n--{boundary}\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + srt.read_bytes() + f"\r\n--{boundary}--".encode()
    _post("https://www.googleapis.com/upload/youtube/v3/captions?uploadType=multipart&part=snippet", raw=body,
          headers={"Authorization": f"Bearer {at}", "Content-Type": f"multipart/related; boundary={boundary}"})


if __name__ == "__main__":
    if "--auth" in sys.argv: auth()
    else:
        d = Path(sys.argv[1]); meta = json.loads((d / "metadata.json").read_text())
        vid = upload_video(next(d.glob("*.mp4")), meta, sys.argv[2] if len(sys.argv) > 2 else None)
        print("video id", vid)
        if meta.get("thumbnail"): set_thumbnail(vid, Path(meta["thumbnail"]))
        if (d / "subtitles.srt").exists(): add_captions(vid, d / "subtitles.srt")
