from fastapi import FastAPI, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse
from uuid import uuid4
import os, subprocess, shutil, glob

app = FastAPI(title="Mini Rave — YouTube tools (robusto)")

PAGE = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Mini Rave</title>
  <style>
    body{font-family:system-ui,Arial,sans-serif;max-width:820px;margin:40px auto;padding:0 16px}
    h1{font-size:28px;margin-bottom:6px}
    h2{font-size:20px;margin-top:28px}
    form{display:flex;gap:8px;margin:10px 0;flex-wrap:wrap}
    input[type=url]{flex:1;min-width:360px;padding:10px;border:1px solid #ccc;border-radius:8px}
    button{padding:10px 16px;border:0;border-radius:8px;background:#111;color:#fff;cursor:pointer}
    .note{font-size:13px;color:#555;margin-top:6px}
    .box{border:1px solid #eee;border-radius:12px;padding:14px;margin-top:14px;background:#fafafa}
    .hint{font-size:12px;color:#666}
  </style>
</head>
<body>
  <h1>Mini Rave</h1>
  <div class="note">Usa solo contenuti tuoi o con licenza idonea. <span class="hint">YouTube può avere restrizioni.</span></div>

  <div class="box">
    <h2>1) YouTube ➜ MP3</h2>
    <form action="/download" method="post">
      <input name="url" type="url" placeholder="https://www.youtube.com/watch?v=..." required>
      <button type="submit">Crea MP3</button>
    </form>
  </div>

  <div class="box">
    <h2>2) Mashup: Canzone A sopra Canzone B</h2>
    <form action="/mashup2" method="post">
      <input name="url_a" type="url" placeholder="Link YouTube — Canzone A (voce/sopra)" required>
      <input name="url_b" type="url" placeholder="Link YouTube — Canzone B (base/sotto)" required>
      <button type="submit">Crea Mashup (MP3)</button>
    </form>
    <div class="note">Versione base: normalizza i volumi, abbassa B quando A è forte (side-chain), poi unisce e crea l’MP3.</div>
  </div>

  <div class="box">
    <h2>3) Test Download</h2>
    <form action="/test_download" method="post">
      <input name="url" type="url" placeholder="https://www.youtube.com/watch?v=..." required>
      <button type="submit">Prova Download</button>
    </form>
    <div class="hint">Se fallisce, vedrai il log completo di yt-dlp per capire il motivo.</div>
  </div>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def home():
    return PAGE

def _run(cmd):
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return proc.returncode, proc.stdout

def _cleanup(paths):
    for p in paths:
        try:
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            elif os.path.exists(p):
                os.remove(p)
        except Exception:
            pass

def ytdlp_to_mp3(url: str, out_dir: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    outtmpl = os.path.join(out_dir, "%(title).200B-%(id)s.%(ext)s")
    cmd = [
        "yt-dlp",
        "-f", "bestaudio/best",
        "--no-playlist",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "0",
        "--geo-bypass",
        "--no-warnings",
        "--ignore-errors",
        "--user-agent", "Mozilla/5.0",
        "-o", outtmpl,
        url
    ]
    code, log = _run(cmd)
    if code != 0:
        return ""
    files = glob.glob(os.path.join(out_dir, "*.mp3"))
    return files[0] if files else ""

@app.post("/download")
def download(url: str = Form(...), background_tasks: BackgroundTasks = None):
    workdir = f"/tmp/{uuid4().hex}"
    mp3_path = ytdlp_to_mp3(url, workdir)
    if not mp3_path or not os.path.exists(mp3_path):
        _cleanup([workdir])
        return PlainTextResponse("Errore nel download/conversione. Verifica link/permessi.", status_code=400)
    if background_tasks is not None:
        background_tasks.add_task(_cleanup, [workdir])
    return FileResponse(mp3_path, media_type="audio/mpeg", filename="track.mp3")

@app.post("/mashup2")
def mashup2(url_a: str = Form(...), url_b: str = Form(...), background_tasks: BackgroundTasks = None):
    workdir = f"/tmp/{uuid4().hex}"
    a_mp3 = ytdlp_to_mp3(url_a, os.path.join(workdir, "A"))
    if not a_mp3:
        _cleanup([workdir]); return PlainTextResponse("Errore nel download di A.", status_code=400)
    b_mp3 = ytdlp_to_mp3(url_b, os.path.join(workdir, "B"))
    if not b_mp3:
        _cleanup([workdir]); return PlainTextResponse("Errore nel download di B.", status_code=400)

    a_wav = os.path.join(workdir, "a.wav")
    b_wav = os.path.join(workdir, "b.wav")
    out_mp3 = os.path.join(workdir, "mashup.mp3")

    if _run(["ffmpeg","-y","-i",a_mp3,"-ar","44100","-ac","2",a_wav])[0] != 0:
        _cleanup([workdir]); return PlainTextResponse("Errore conversione A.", status_code=500)
    if _run(["ffmpeg","-y","-i",b_mp3,"-ar","44100","-ac","2",b_wav])[0] != 0:
        _cleanup([workdir]); return PlainTextResponse("Errore conversione B.", status_code=500)

    fc = (
        "[0:a]loudnorm=I=-14:TP=-1.5:LRA=11[a];"
        "[1:a]loudnorm=I=-14:TP=-1.5:LRA=11[b];"
        "[b][a]sidechaincompress=threshold=0.1:ratio=8:attack=5:release=300:makeup=3[m];"
        "[m][a]amix=inputs=2:duration=longest, loudnorm=I=-14:TP=-1.5:LRA=11[out]"
    )
    code, log = _run([
        "ffmpeg","-y",
        "-i", a_wav,
        "-i", b_wav,
        "-filter_complex", fc,
        "-map","[out]",
        "-b:a","320k",
        out_mp3
    ])
    if code != 0 or not os.path.exists(out_mp3):
        _cleanup([workdir]); return PlainTextResponse("Errore nel mix.\n"+log[-800:], status_code=500)

    if background_tasks is not None:
        background_tasks.add_task(_cleanup, [workdir])
    return FileResponse(out_mp3, media_type="audio/mpeg", filename="mashup.mp3")

@app.post("/test_download")
def test_download(url: str = Form(...)):
    workdir = f"/tmp/{uuid4().hex}"
    os.makedirs(workdir, exist_ok=True)
    outtmpl = os.path.join(workdir, "%(title).200B-%(id)s.%(ext)s")
    cmd = [
        "yt-dlp",
        "-f", "bestaudio/best",
        "--no-playlist",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "0",
        "--geo-bypass",
        "--no-warnings",
        "--ignore-errors",
        "--user-agent", "Mozilla/5.0",
        "-o", outtmpl,
        url
    ]
    code, log = _run(cmd)
    mp3s = glob.glob(os.path.join(workdir, "*.mp3"))
    if code != 0 or not mp3s:
        return PlainTextResponse("Errore yt-dlp (comando):\n" + " ".join(cmd) + "\n\nLOG:\n" + log, status_code=400)
    return FileResponse(mp3s[0], media_type="audio/mpeg", filename="test.mp3")

@app.get("/test_download", response_class=HTMLResponse)
def test_download_form():
    return """
    <h2>Test Download YouTube</h2>
    <form action="/test_download" method="post">
        <input name="url" type="url" placeholder="https://www.youtube.com/watch?v=..." required>
        <button type="submit">Scarica MP3</button>
    </form>
    """
