"""
Records a narrated demo of the live SalesSense AI app.

1. Generates Indian-English narration for each scene with Gemini TTS.
2. Warms up the live app (and its AI cache) in an unrecorded browser.
3. Records the real app in Chromium while performing each scene, timed to the narration.
4. Merges video and narration into an MP4 with ffmpeg.

Usage:  python render.py            (live app, real TTS; needs GEMINI_API_KEY)
        python render.py --local URL (any app URL, silent placeholder narration, for testing)
"""

import base64, json, os, subprocess, sys, time, wave
from pathlib import Path
from playwright.sync_api import sync_playwright

LOCAL = "--local" in sys.argv
APP = sys.argv[sys.argv.index("--local") + 1] if LOCAL else "https://salessense-ai-srijan.streamlit.app/~/+/"
OUT = Path("output"); OUT.mkdir(exist_ok=True)
AUD = OUT / "audio"; AUD.mkdir(exist_ok=True)
W, H = 1280, 720
STYLE = ("Indian English accent. A confident, friendly MBA student presenting a software demo to professors. "
         "Clear, natural pace with short pauses between sentences. Warm and professional, not robotic.")

SCENES = [
 ("intro", "This is SalesSense AI, the end-term project of Srijan Pandey, roll number 3 4 1 2 8 5, Section E, for the course AI for Managers. It is a lead-scoring assistant for B2B sales teams, built for Use Case 7."),
 ("rules", "Sales teams have more leads than time. So the app scores every lead out of 100, using eight transparent rules, such as demo requested, purchase urgency, and engagement. Eighty and above is Hot, fifty to seventy-nine is Warm, and below fifty is Cold. The rules produce the number, and Gemini only explains it. It can never change the score."),
 ("technova", "Let's score TechNova Solutions, a large IT company with strong buying signals. It scores 100, so it is a Hot lead. This table shows exactly where every point came from. Below it, Gemini gives a short summary, the key factors, a recommended next action, a sales approach, and the risks it noticed. The final decision always stays with the salesperson."),
 ("dashboard", "For a full lead list, users can upload a CSV or Excel file. Here are thirty sample leads: eight Hot, twelve Warm, and ten Cold, with the top five ranked. Now look at Brightline Retail. It scores 100 on the rules, but the sales notes say the demo is only for market research, and there is no budget. Gemini catches this, and shows a red warning that the notes conflict with the score."),
 ("validation", "Every input is checked before it reaches the scoring engine or the AI. This file has three bad rows. They are rejected with the exact reason, and the valid rows are still scored. The results can be exported to a CRM-ready CSV file in one click."),
 ("safety", "If the Gemini API goes down, the app does not break. The score, the breakdown, and a default next step are still shown. The app was also tested against prompt-injection attempts in the notes, and the score cannot be manipulated."),
 ("close", "The AI only knows what it is given, so SalesSense AI is decision support, not a decision maker. It turns a raw lead list into a ranked, explained call list in seconds. Thank you."),
]

# ------------------------------------------------------------------ narration
def wav_seconds(path):
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()

def silent_wav(path, seconds):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
        w.writeframes(b"\x00\x00" * int(24000 * seconds))

def pick_voice(client):
    try:
        res = client.voices.list(language_code=["en-IN"], type_=["prebuilt"], page_size=50)
        voices = res.voices or []
        for v in voices:
            print("voice:", v.id, v.display_name, v.language_code, v.accent, v.gender, v.pitch, "|", v.description)
        male = [v for v in voices if str(v.gender).lower().endswith("male") and "female" not in str(v.gender).lower()]
        chosen = (male or voices)[0].id if voices else None
        if chosen:
            return chosen
    except Exception as exc:
        print("voices.list failed:", repr(exc)[:300])
    return "Charon"

def tts(client, voice, text, path):
    variants = [[{"voice": voice, "language": "en-IN"}], [{"voice": voice}]]
    for attempt in range(8):
        speech = variants[0] if attempt == 0 or not _STATE.get("no_lang") else variants[1]
        try:
            it = client.interactions.create(
                model="gemini-3.8-flash-tts",
                input=[{"type": "user_input", "content": [{"type": "text", "text": text,
                        "annotations": [{"type": "speech_metadata", "style": STYLE}]}]}],
                response_format={"type": "audio"},
                generation_config={"speech_config": speech},
            )
            raw = base64.b64decode(it.output_audio.data)
            if raw[:4] != b"RIFF":  # raw PCM: wrap it in a WAV header
                with wave.open(str(path), "wb") as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(raw)
            else:
                path.write_bytes(raw)
            return
        except Exception as exc:
            msg = repr(exc)[:500]
            print(f"TTS attempt {attempt + 1} failed: {msg}")
            if "language" in msg.lower() or "400" in msg:
                _STATE["no_lang"] = True
                continue
            time.sleep(20 * (attempt + 1))
    raise SystemExit("TTS failed repeatedly")

_STATE = {}

def make_audio():
    if LOCAL:
        for name, text in SCENES:
            silent_wav(AUD / f"{name}.wav", len(text.split()) / 2.6)
        return
    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    voice = pick_voice(client)
    print("Using voice:", voice)
    for name, text in SCENES:
        p = AUD / f"{name}.wav"
        if not p.exists():
            tts(client, voice, text, p)
            time.sleep(4)
        print(f"{name}: {wav_seconds(p):.1f}s")

# ------------------------------------------------------------------ browser helpers
CURSOR_JS = """
(() => {
  if (window.__cursorInstalled) return; window.__cursorInstalled = true;
  const add = () => {
    const c = document.createElement('div');
    c.id = '__cursor';
    c.style.cssText = 'position:fixed;left:0;top:0;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;'
      + 'background:rgba(31,56,100,0.35);border:2px solid rgba(31,56,100,0.9);z-index:2147483647;pointer-events:none;'
      + 'transition:transform 0.12s ease;';
    document.documentElement.appendChild(c);
    document.addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
    document.addEventListener('mousedown', () => { c.style.transform = 'scale(0.7)'; }, true);
    document.addEventListener('mouseup', () => { c.style.transform = 'scale(1)'; }, true);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', add); else add();
})();
"""

class Demo:
    def __init__(self, page):
        self.page = page
        self.mx, self.my = W / 2, H / 2

    def move_to(self, loc, steps=18):
        loc.scroll_into_view_if_needed()
        b = loc.bounding_box()
        if b:
            x, y = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
            self.page.mouse.move(x, y, steps=steps)
            self.mx, self.my = x, y
        time.sleep(0.15)

    def click(self, loc):
        self.move_to(loc)
        try:
            loc.click(timeout=6000)
        except Exception:
            loc.click(force=True)
        time.sleep(0.4)

    def type(self, loc, text, delay=35):
        self.click(loc)
        loc.fill("")
        loc.press_sequentially(text, delay=delay)

    def select(self, label, value):
        box = self.page.get_by_label(label, exact=True)
        self.click(box)
        self.page.keyboard.type(value, delay=40)
        self.page.keyboard.press("Enter")
        time.sleep(0.3)

    def radio_yes(self, index):
        loc = self.page.locator('[data-testid="stRadio"]').nth(index).locator("label").filter(has_text="Yes")
        self.click(loc)

    def number(self, label, value):
        box = self.page.get_by_label(label, exact=True)
        self.click(box)
        box.fill("")
        box.press_sequentially(str(value), delay=60)
        box.press("Tab")

    def scroll(self, pixels, step=90, pause=0.035):
        self.page.mouse.move(W * 0.62, H * 0.6)
        n = max(1, abs(int(pixels / step)))
        for _ in range(n):
            self.page.mouse.wheel(0, step if pixels > 0 else -step)
            time.sleep(pause)

    def scroll_to_text(self, text, offset=120):
        loc = self.page.get_by_text(text, exact=False).locator("visible=true").first
        loc.wait_for(timeout=90000)
        for _ in range(60):
            b = loc.bounding_box()
            if b is None or b["y"] < offset + 40:
                break
            self.scroll(min(160, b["y"] - offset), step=40, pause=0.03)
        time.sleep(0.2)

    def top(self):
        self.page.evaluate("document.querySelector('[data-testid=\"stMain\"]')?.scrollTo({top: 0, behavior: 'smooth'})")
        time.sleep(0.8)

    def tab(self, name):
        self.click(self.page.get_by_role("tab", name=name))
        time.sleep(0.8)

    def wait_text(self, text, timeout=90000):
        self.page.get_by_text(text, exact=False).locator("visible=true").first.wait_for(timeout=timeout)

def title_html(sub, small):
    return f"""<html><body style="margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
    background:linear-gradient(135deg,#1f3864,#2a78d6);font-family:Segoe UI,Arial,sans-serif;color:white">
    <div style="text-align:center"><div style="font-size:64px;font-weight:700;letter-spacing:1px">SalesSense AI</div>
    <div style="font-size:26px;margin-top:14px;opacity:.95">{sub}</div>
    <div style="font-size:20px;margin-top:34px;opacity:.85;line-height:1.6">{small}</div></div></body></html>"""

def open_app(page):
    page.goto(APP, wait_until="domcontentloaded", timeout=120000)
    for _ in range(40):  # handle the sleeping-app screen
        btn = page.get_by_role("button", name="Yes, get this app back up!")
        if btn.count() and btn.first.is_visible():
            btn.first.click(); time.sleep(20)
        if page.get_by_text("Analyze lead").count():
            break
        time.sleep(3)
    page.get_by_text("Analyze lead").first.wait_for(timeout=180000)
    time.sleep(2)

# ------------------------------------------------------------------ scene actions
def fill_lead(d, company, industry, size, vendor, dm, demo, urgency, interaction, visits, opens, notes):
    p = d.page
    d.type(p.get_by_label("Company name *", exact=True), company)
    d.type(p.get_by_label("Industry", exact=True), industry)
    d.select("Company size (employees)", size)
    d.type(p.get_by_label("Current vendor / solution", exact=True), vendor)
    if dm: d.radio_yes(0)
    if demo: d.radio_yes(1)
    d.select("Purchase urgency", urgency)
    d.select("Previous interaction", interaction)
    d.number("Website visits (last 30 days)", visits)
    d.number("Email opens (last 30 days)", opens)
    if notes:
        d.type(p.get_by_label("Sales notes (optional)", exact=True), notes, delay=18)

def act(name, d):
    p = d.page
    if name == "intro":
        p.set_content(title_html("AI-assisted B2B lead scoring and recommendations",
            "Srijan Pandey &nbsp;|&nbsp; Roll No. 341285 &nbsp;|&nbsp; Section E<br>AI for Managers: Applications &amp; Strategy &nbsp;|&nbsp; FORE School of Management"))
        time.sleep(5)
        open_app(p)
        d.move_to(p.get_by_text("Gemini connected").first)
    elif name == "rules":
        d.tab("How scoring works")
        time.sleep(2)
        d.scroll(260, step=40, pause=0.05)
    elif name == "technova":
        d.top(); d.tab("Score a lead")
        fill_lead(d, "TechNova Solutions", "IT Services", "1000+", "Competitor A", True, True, "High", "Positive", 12, 8, "")
        d.click(p.get_by_role("button", name="Analyze lead"))
        d.wait_text("HOT LEAD")
        d.scroll_to_text("HOT LEAD", offset=140)
        time.sleep(2.5)
        d.wait_text("Recommended next action")
        d.scroll_to_text("AI analysis (Gemini)", offset=90)
        d.scroll(380, step=30, pause=0.06)
    elif name == "dashboard":
        d.top(); d.tab("Upload leads & dashboard")
        d.click(p.get_by_role("button", name="Load sample data (30 leads)"))
        d.wait_text("Lead distribution by tier")
        d.scroll_to_text("Total leads scored", offset=110)
        time.sleep(1.5)
        d.scroll(330, step=30, pause=0.05)
        d.scroll_to_text("AI analysis for one lead", offset=110)
        d.click(p.get_by_label("Choose a lead"))
        p.keyboard.type("Brightline", delay=50); p.keyboard.press("Enter"); time.sleep(0.6)
        d.click(p.get_by_role("button", name="Generate AI analysis"))
        d.wait_text("sales notes conflict")
        d.scroll_to_text("sales notes conflict", offset=300)
    elif name == "validation":
        d.top()
        d.click(p.get_by_role("button", name="Load sample with errors"))
        d.wait_text("failed validation")
        d.scroll_to_text("failed validation", offset=220)
        time.sleep(3)
        d.move_to(p.get_by_role("button", name="Download CRM export (CSV)"))
    elif name == "safety":
        d.top()
        d.click(p.get_by_text("Simulate AI outage", exact=True))
        d.wait_text("AI outage simulated")
        time.sleep(1)
        d.scroll_to_text("AI analysis for one lead", offset=110)
        d.click(p.get_by_role("button", name="Generate AI analysis"))
        d.wait_text("currently unavailable")
        d.scroll_to_text("currently unavailable", offset=380)
    elif name == "close":
        d.top()
        d.click(p.get_by_text("Simulate AI outage", exact=True))
        time.sleep(1.5)
        p.set_content(title_html("Transparent rules for the score. Gemini for the reasoning. A human for the decision.",
            "Live app: salessense-ai-srijan.streamlit.app<br>Srijan Pandey &nbsp;|&nbsp; 341285 &nbsp;|&nbsp; Section E"))

# ------------------------------------------------------------------ run
def run_scenes(browser, record):
    kw = dict(viewport={"width": W, "height": H}, device_scale_factor=1, color_scheme="light")
    if record:
        kw.update(record_video_dir=str(OUT / "raw"), record_video_size={"width": W, "height": H})
    ctx = browser.new_context(**kw)
    ctx.add_init_script(CURSOR_JS)
    page = ctx.new_page()
    t0 = time.monotonic()
    d = Demo(page)
    timeline = []
    for name, text in SCENES:
        dur = wav_seconds(AUD / f"{name}.wav")
        start = time.monotonic() - t0
        act(name, d)
        page.evaluate("window.getSelection().removeAllRanges()")
        page.evaluate(CURSOR_JS) if name in ("intro", "close") else None
        elapsed = time.monotonic() - t0 - start
        if record:
            remaining = dur + 0.7 - elapsed
            if remaining > 0:
                time.sleep(remaining)
        timeline.append({"scene": name, "start": round(start, 2), "audio": round(dur, 2),
                         "actions": round(elapsed, 2)})
        print(f"{'REC' if record else 'warm'} {name}: start {start:.1f}s audio {dur:.1f}s actions {elapsed:.1f}s")
    if record:
        time.sleep(1.5)
    video_path = page.video.path() if record else None
    ctx.close()
    return timeline, video_path

def main():
    make_audio()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--disable-gpu"])
        try:
            run_scenes(browser, record=False)  # warm up the app and Gemini cache
        except Exception as exc:
            print("Warm-up problem (continuing):", repr(exc)[:300])
        timeline, raw = run_scenes(browser, record=True)
        browser.close()
    json.dump(timeline, open(OUT / "timeline.json", "w"), indent=1)
    # merge audio at scene offsets
    inputs = ["-i", raw]
    filters, labels = [], []
    for i, t in enumerate(timeline, start=1):
        inputs += ["-i", str(AUD / f"{t['scene']}.wav")]
        ms = int(t["start"] * 1000)
        filters.append(f"[{i}:a]aresample=48000,adelay={ms}|{ms}[a{i}]")
        labels.append(f"[a{i}]")
    filters.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0:dropout_transition=0,volume=1.25,alimiter=limit=0.9[aout]")
    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[aout]",
           "-c:v", "libx264", "-preset", "medium", "-crf", "22", "-pix_fmt", "yuv420p", "-r", "30",
           "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(OUT / "SalesSense_AI_Demo.mp4")]
    subprocess.run(cmd, check=True)
    print("DONE", OUT / "SalesSense_AI_Demo.mp4")

if __name__ == "__main__":
    main()
