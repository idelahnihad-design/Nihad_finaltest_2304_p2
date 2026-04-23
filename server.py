import http.server
import socketserver
import urllib.parse
import json
import html as html_lib
import hashlib
import os
import re
from pathlib import Path
import secrets as _secrets

PORT = 8000

# ── Session store (token -> email, lives while server runs) ──────────────────
SESSIONS: dict = {}

def create_session(email: str) -> str:
    token = _secrets.token_hex(24)
    SESSIONS[token] = email
    return token

def get_session_email(cookie_header: str) -> str:
    if not cookie_header:
        return ""
    for part in cookie_header.split(";"):
        part = part.strip()
        if part.startswith("ss_session="):
            return SESSIONS.get(part[len("ss_session="):], "")
    return ""

def delete_session(cookie_header: str):
    for part in (cookie_header or "").split(";"):
        part = part.strip()
        if part.startswith("ss_session="):
            SESSIONS.pop(part[len("ss_session="):], None)

DATA_DIR   = Path(".")
USERS_FILE = DATA_DIR / "users.json"
SKILLS_FILE = DATA_DIR / "skills.json"

LEVEL_COLORS = {
    "Beginner":     ("#d1fae5", "#065f46"),
    "Intermediate": ("#fef3c7", "#92400e"),
    "Advanced":     ("#fee2e2", "#991b1b"),
}
ROLE_ICONS = {
    "student":    "🎓",
    "instructor": "📖",
    "admin":      "🛡️",
    "parent":     "👨‍👩‍👧",
}

# ── helpers ──────────────────────────────────────────────────────────────────

def load_json(path, default):
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def sanitize(value: str) -> str:
    return html_lib.escape(str(value), quote=True)

def hash_password(pw: str) -> str:
    """Salt + SHA-256.  Not bcrypt, but acceptable for an academic prototype."""
    salt = os.urandom(16).hex()
    h = hashlib.sha256((salt + pw).encode()).hexdigest()
    return f"{salt}${h}"

def verify_password(pw: str, stored: str) -> bool:
    try:
        salt, h = stored.split("$", 1)
        return hashlib.sha256((salt + pw).encode()).hexdigest() == h
    except Exception:
        return False

def is_valid_email(email: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email))

def next_user_id(users: list) -> int:
    return max((u.get("id", 0) for u in users), default=0) + 1

# ── seed demo data ────────────────────────────────────────────────────────────

if not SKILLS_FILE.exists():
    save_json(SKILLS_FILE, [
        {"id": 1, "title": "Intro to Python",        "category": "Programming",   "level": "Beginner",     "owner_role": "student",    "owner_name": "Ali"},
        {"id": 2, "title": "Academic Writing Basics", "category": "Writing",       "level": "Intermediate", "owner_role": "instructor", "owner_name": "Dr. Smith"},
        {"id": 3, "title": "Presentation Skills",     "category": "Communication", "level": "Beginner",     "owner_role": "student",    "owner_name": "Sara"},
        {"id": 4, "title": "Data Structures Lab",     "category": "Programming",   "level": "Intermediate", "owner_role": "instructor", "owner_name": "Prof. Lee"},
        {"id": 5, "title": "Public Speaking 101",     "category": "Communication", "level": "Beginner",     "owner_role": "student",    "owner_name": "Rania"},
        {"id": 6, "title": "UI/UX Design Basics",     "category": "Design",        "level": "Beginner",     "owner_role": "student",    "owner_name": "Marco"},
    ])

if not USERS_FILE.exists():
    save_json(USERS_FILE, [])      # empty users store

# ── shared CSS ────────────────────────────────────────────────────────────────

SHARED_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0;
    font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
:root {
  --bg: #0f172a; --surface: rgba(15,23,42,0.82);
  --border: rgba(148,163,184,0.35); --text: #f1f5f9; --muted: #94a3b8;
  --accent1: #38bdf8; --accent2: #a855f7;
  --grad: linear-gradient(135deg,var(--accent1),var(--accent2));
  --err: #f87171; --ok: #4ade80;
}
body { min-height:100vh; background:var(--bg); color:var(--text); display:flex; flex-direction:column; }

/* NAV */
header {
  position:sticky; top:0; z-index:100;
  padding:0.9rem 2rem; display:flex; align-items:center; justify-content:space-between;
  background:rgba(10,18,36,0.9); backdrop-filter:blur(14px);
  border-bottom:1px solid var(--border);
}
.logo { display:flex; align-items:center; gap:0.6rem; text-decoration:none; }
.logo-icon {
  width:38px; height:38px; border-radius:50%;
  display:flex; align-items:center; justify-content:center;
  font-size:1.2rem; font-weight:700;
  background:var(--grad); box-shadow:0 0 14px rgba(56,189,248,0.45);
}
.logo-text { font-weight:700; font-size:1.05rem; color:var(--text); }
.logo-tag  { font-size:0.7rem; color:var(--muted); }
nav { display:flex; align-items:center; gap:0.25rem; }
nav a {
  color:#cbd5e1; text-decoration:none;
  padding:0.38rem 0.85rem; border-radius:999px; font-size:0.9rem;
  border:1px solid transparent; transition:all 0.18s;
}
nav a:hover { border-color:var(--border); background:rgba(255,255,255,0.06); color:var(--text); }
.nav-cta {
  background:var(--grad) !important; color:#0f172a !important;
  font-weight:600; border:none !important;
  box-shadow:0 4px 16px rgba(56,189,248,0.3);
}
.nav-cta:hover { opacity:0.9; transform:translateY(-1px); }

/* HERO */
.hero {
  position:relative; overflow:hidden; min-height:88vh;
  display:flex; align-items:center;
  background-image:
    linear-gradient(to right,rgba(10,18,36,0.97) 0%,rgba(10,18,36,0.85) 52%,rgba(10,18,36,0.45) 100%),
    url("https://images.unsplash.com/photo-1522202176988-66273c2fd55f?w=1800&q=80&auto=format&fit=crop");
  background-size:cover; background-position:center 30%;
}
.hero-inner {
  max-width:1100px; width:100%; margin:0 auto;
  padding:5rem 2rem 4rem;
  display:grid; grid-template-columns:1fr 1fr; gap:3rem; align-items:center;
}
.hero-eyebrow {
  display:inline-flex; align-items:center; gap:0.5rem;
  font-size:0.75rem; font-weight:600; letter-spacing:0.08em; text-transform:uppercase;
  color:var(--accent1); background:rgba(56,189,248,0.1);
  border:1px solid rgba(56,189,248,0.3);
  padding:0.3rem 0.8rem; border-radius:999px; margin-bottom:1.2rem;
}
.hero-title {
  font-size:clamp(2.4rem,5vw,3.4rem); font-weight:800;
  line-height:1.08; letter-spacing:-0.02em; margin-bottom:1rem;
}
.hero-title .grad { background:var(--grad); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
.hero-subtitle { font-size:1.05rem; color:#cbd5e1; line-height:1.65; max-width:30rem; margin-bottom:1.8rem; }
.hero-stats { display:flex; gap:2rem; margin-bottom:2rem; }
.stat-val { font-size:1.5rem; font-weight:700; color:var(--text); display:block; }
.stat-label { font-size:0.75rem; color:var(--muted); }
.hero-actions { display:flex; gap:0.75rem; flex-wrap:wrap; }

/* BUTTONS */
.btn {
  display:inline-flex; align-items:center; gap:0.4rem;
  padding:0.65rem 1.4rem; border-radius:999px;
  font-size:0.95rem; font-weight:600;
  text-decoration:none; border:none; cursor:pointer;
  transition:transform 0.14s, box-shadow 0.14s, opacity 0.14s;
}
.btn:hover { transform:translateY(-2px); }
.btn-primary { background:var(--grad); color:#0f172a; box-shadow:0 8px 28px rgba(56,189,248,0.35); }
.btn-primary:hover { box-shadow:0 12px 36px rgba(56,189,248,0.5); }
.btn-ghost { background:rgba(255,255,255,0.07); color:var(--text); border:1px solid var(--border); }
.btn-ghost:hover { background:rgba(255,255,255,0.12); }

/* FEATURE CARDS */
.features { padding:5rem 2rem; max-width:1100px; margin:0 auto; width:100%; }
.section-label { text-align:center; margin-bottom:0.6rem; font-size:0.75rem; font-weight:600; letter-spacing:0.1em; text-transform:uppercase; color:var(--accent1); }
.section-title { text-align:center; font-size:2rem; font-weight:700; margin-bottom:0.6rem; }
.section-sub   { text-align:center; color:var(--muted); font-size:0.95rem; max-width:32rem; margin:0 auto 2.5rem; }
.features-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); gap:1.2rem; }
.feature-card {
  background:var(--surface); border:1px solid var(--border);
  border-radius:1.2rem; padding:1.5rem; backdrop-filter:blur(10px);
  transition:border-color 0.2s, transform 0.2s;
}
.feature-card:hover { border-color:rgba(56,189,248,0.5); transform:translateY(-3px); }
.fc-icon { font-size:2rem; margin-bottom:0.75rem; display:block; }
.fc-title { font-size:1rem; font-weight:700; margin-bottom:0.4rem; }
.fc-desc  { font-size:0.82rem; color:#94a3b8; line-height:1.55; margin-bottom:0.6rem; }
.fc-tag   { font-size:0.7rem; padding:0.18rem 0.55rem; border-radius:999px; background:rgba(56,189,248,0.12); border:1px solid rgba(56,189,248,0.35); color:#7dd3fc; display:inline-block; }

/* SKILLS */
.skills-wrap { background:rgba(255,255,255,0.02); border-top:1px solid var(--border); border-bottom:1px solid var(--border); padding:4rem 2rem; }
.skills-inner { max-width:1100px; margin:0 auto; }
.skills-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(210px,1fr)); gap:1rem; margin-top:2rem; }
.skill-card {
  background:var(--surface); border:1px solid var(--border);
  border-radius:1rem; padding:1.1rem; backdrop-filter:blur(8px);
  transition:border-color 0.2s, transform 0.2s;
  display:flex; flex-direction:column; gap:0.4rem;
}
.skill-card:hover { border-color:rgba(168,85,247,0.5); transform:translateY(-2px); }
.skill-title { font-size:0.95rem; font-weight:600; }
.skill-cat   { font-size:0.75rem; color:var(--muted); }
.skill-owner { font-size:0.75rem; color:#67e8f9; margin-top:auto; padding-top:0.5rem; }
.level-badge { display:inline-block; font-size:0.68rem; font-weight:600; padding:0.15rem 0.5rem; border-radius:999px; }

/* AUTH CARDS */
main { flex:1; display:flex; justify-content:center; }
.page-wrap { width:100%; max-width:1100px; padding:3rem 1.5rem; }
.auth-wrap  { display:flex; align-items:center; justify-content:center; min-height:70vh; }
.card {
  background:var(--surface); border:1px solid var(--border);
  border-radius:1.3rem; padding:2rem; backdrop-filter:blur(10px);
  box-shadow:0 20px 60px rgba(0,0,0,0.6);
}
.card-title { font-size:1.5rem; font-weight:700; margin-bottom:0.3rem; }
.card-sub   { font-size:0.85rem; color:var(--muted); margin-bottom:1.5rem; }

/* FORM */
form { display:flex; flex-direction:column; gap:0.85rem; }
.field { display:flex; flex-direction:column; gap:0.28rem; }
.field label { font-size:0.82rem; font-weight:600; color:#cbd5e1; }
input[type=text], input[type=email], input[type=password], select {
  padding:0.6rem 0.85rem; border-radius:0.65rem;
  border:1px solid var(--border);
  background:rgba(15,23,42,0.95); color:var(--text);
  font-size:0.92rem; outline:none; transition:border-color 0.18s;
}
input:focus, select:focus { border-color:var(--accent1); box-shadow:0 0 0 3px rgba(56,189,248,0.15); }

/* password strength bar */
.pw-bar-wrap { height:4px; border-radius:2px; background:rgba(255,255,255,0.08); margin-top:4px; overflow:hidden; }
.pw-bar      { height:100%; border-radius:2px; width:0; transition:width 0.3s, background 0.3s; }

/* validation hints */
.field-hint { font-size:0.73rem; color:var(--muted); }
.field-error { font-size:0.73rem; color:var(--err); }

/* alert banners */
.alert { border-radius:0.7rem; padding:0.7rem 1rem; font-size:0.85rem; margin-bottom:1rem; display:flex; align-items:center; gap:0.5rem; }
.alert-err { background:rgba(248,113,113,0.12); border:1px solid rgba(248,113,113,0.4); color:#fca5a5; }
.alert-ok  { background:rgba(74,222,128,0.12);  border:1px solid rgba(74,222,128,0.4);  color:#86efac; }

/* tabs (sign-up / login toggle) */
.auth-tabs { display:flex; gap:0; margin-bottom:1.5rem; border-radius:0.75rem; overflow:hidden; border:1px solid var(--border); }
.auth-tab  { flex:1; text-align:center; padding:0.55rem; font-size:0.88rem; font-weight:600; text-decoration:none; color:var(--muted); background:transparent; transition:all 0.18s; }
.auth-tab.active { background:var(--grad); color:#0f172a; }

/* divider */
.divider { display:flex; align-items:center; gap:0.6rem; color:var(--muted); font-size:0.78rem; margin:0.5rem 0; }
.divider::before, .divider::after { content:""; flex:1; height:1px; background:var(--border); }

/* FOOTER */
footer { padding:1rem 2rem; text-align:center; font-size:0.75rem; color:var(--muted); background:rgba(10,18,36,0.95); border-top:1px solid var(--border); }

/* RESPONSIVE */
@media (max-width:768px) {
  header { padding:0.8rem 1rem; }
  .hero-inner { grid-template-columns:1fr; padding:3rem 1.2rem 2.5rem; }
  .hero-stats { gap:1.2rem; }
  .features { padding-left:1.2rem; padding-right:1.2rem; }
}
"""


# ── Chatbot brain ─────────────────────────────────────────────────────────────

CHAT_RULES = [
    (["hello", "hi", "hey", "howdy"],
     "👋 Hey there! I'm SkillBot, your Skill Swap assistant. Ask me anything about the platform!"),

    (["what is skill swap", "about", "explain", "tell me about"],
     "🎓 Skill Swap is a campus skill-trading platform where students, instructors, admins, and parents connect. You can offer skills you know and enroll in skills you want to learn!"),

    (["sign up", "register", "create account", "join"],
     "✍️ To sign up: click the <b>Sign Up</b> button in the top-right nav → fill in your name, email, password, and role → hit 'Create my account'. It only takes 30 seconds!"),

    (["login", "log in", "sign in", "access"],
     "🔑 Click <b>Login</b> in the nav bar → enter your email and password → you'll land on your personal dashboard."),

    (["forgot password", "reset password", "lost password"],
     "🔒 Password reset isn't available yet — it's coming in a future sprint! For now, ask your admin to help."),

    (["skills", "browse", "what skills", "available", "courses"],
     "📚 Head to <a href='/skills' style='color:#38bdf8;'>Browse Skills</a> to see all available skills. Currently we have Programming, Writing, Communication, and Design tracks."),

    (["python", "programming", "coding", "code"],
     "🐍 We have 'Intro to Python' (Beginner) and 'Data Structures Lab' (Intermediate) available right now. Check the <a href='/skills' style='color:#38bdf8;'>Skills page</a>!"),

    (["writing", "academic writing"],
     "✍️ 'Academic Writing Basics' (Intermediate) is offered by Dr. Smith. Visit the <a href='/skills' style='color:#38bdf8;'>Skills page</a> to learn more."),

    (["design", "ui", "ux"],
     "🎨 'UI/UX Design Basics' (Beginner) is available on the platform. Check it out on the <a href='/skills' style='color:#38bdf8;'>Skills page</a>!"),

    (["communication", "speaking", "presentation"],
     "🎤 We have 'Presentation Skills' and 'Public Speaking 101' — both Beginner level. Great for building confidence!"),

    (["role", "roles", "who can", "student", "instructor", "admin", "parent"],
     "👥 Skill Swap has 4 roles:<br>🎓 <b>Student</b> — learn & teach<br>📖 <b>Instructor</b> — guide & publish tracks<br>🛡️ <b>Admin</b> — manage the platform<br>👨‍👩‍👧 <b>Parent</b> — track your student's progress"),

    (["dashboard", "my page", "profile"],
     "📊 Your dashboard shows your enrolled skills, progress, and notifications. Log in first to access it!"),

    (["enroll", "join skill", "take skill", "how to learn"],
     "📝 Enrollment is coming in the next sprint! For now, browse available skills and get familiar with what's offered."),

    (["password", "password rule", "password requirement"],
     "🔐 Your password must be at least <b>8 characters</b> and contain at least <b>one number</b>. The strength bar on the sign-up page shows you how strong it is."),

    (["contact", "help", "support", "problem", "issue"],
     "🙋 For support, reach out to your platform administrator. More help features are coming in future sprints!"),

    (["thank", "thanks", "awesome", "great", "cool", "nice"],
     "😊 You're welcome! Let me know if there's anything else I can help with."),

    (["bye", "goodbye", "see you", "exit"],
     "👋 Goodbye! Come back anytime. Happy skill swapping! 🚀"),
]

def chatbot_reply(message: str) -> str:
    msg = message.lower().strip()
    for keywords, reply in CHAT_RULES:
        if any(kw in msg for kw in keywords):
            return reply
    return "🤔 I'm not sure about that yet! Try asking about <b>signing up</b>, <b>skills</b>, <b>roles</b>, or <b>logging in</b>. I'm still learning! 😊"

# ── request handler ───────────────────────────────────────────────────────────

class SkillSwapHandler(http.server.SimpleHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # suppress noisy logs during demo

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        routes = {
            "/":             self.render_home,
            "/index.html":   self.render_home,
            "/signup":       self.render_signup,
            "/login":        self.render_login,
            "/dashboard":    self.render_dashboard,
            "/profile":      self.render_profile,
            "/edit_profile": self.render_edit_profile,
            "/skills":       self.render_skills,
            "/logout":       self.handle_logout,
        }
        handler = routes.get(path)
        if handler:
            return handler()
        return http.server.SimpleHTTPRequestHandler.do_GET(self)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        routes = {
            "/do_signup":       self.handle_signup,
            "/do_login":        self.handle_login,
            "/do_edit_profile": self.handle_edit_profile,
            "/chat":            self.handle_chat,
        }
        handler = routes.get(path)
        if handler:
            return handler()
        self.send_error(404, "Not Found")

    # ── low-level helpers ────────────────────────────────────────────────────

    def send_html(self, html, status=200):
        b = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8")
        return urllib.parse.parse_qs(raw)

    def redirect(self, location: str, set_cookie: str = ""):
        self.send_response(302)
        self.send_header("Location", location)
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.end_headers()

    def get_session_user(self):
        """Return logged-in user dict from session cookie, or None."""
        email = get_session_email(self.headers.get("Cookie", ""))
        if not email:
            return None
        users = load_json(USERS_FILE, [])
        return next((u for u in users if u.get("email") == email), None)

    def _page(self, title: str, body_html: str, *, show_login_cta=True) -> str:
        session_user = self.get_session_user()
        if session_user:
            uname  = sanitize(session_user.get("name", "Account"))
            uemail = urllib.parse.quote(session_user.get("email", ""))
            nav_right = (
                f'<a href="/profile?email={uemail}" style="color:#a5f3fc;text-decoration:none;'
                f'padding:0.38rem 0.85rem;border-radius:999px;font-size:0.9rem;">👤 {uname}</a>'
                '<a href="/logout" style="background:rgba(248,113,113,0.15);color:#fca5a5;'
                'text-decoration:none;padding:0.38rem 0.85rem;border-radius:999px;'
                'font-size:0.9rem;border:1px solid rgba(248,113,113,0.35);margin-left:0.3rem;">'
                'Log out</a>'
            )
        else:
            nav_right = (
                '<a href="/login" style="color:#cbd5e1;text-decoration:none;padding:0.38rem 0.85rem;border-radius:999px;font-size:0.9rem;">Login</a>'
                + ('<a href="/signup" style="background:linear-gradient(135deg,#38bdf8,#a855f7);color:#0f172a;font-weight:700;padding:0.42rem 1.1rem;border-radius:999px;text-decoration:none;font-size:0.9rem;margin-left:0.4rem;">Sign Up</a>'
                   if show_login_cta else "")
            )
        cta = nav_right  # kept for backward compat
        head = (
            '<!DOCTYPE html>\n'
            '<html lang="en">\n'
            '<head>\n'
            '  <meta charset="UTF-8"/>\n'
            '  <title>' + sanitize(title) + ' – Skill Swap</title>\n'
            '  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>\n'
            '  <style>\n' + SHARED_CSS + '\n  </style>\n'
            '</head>\n'
            '<body>\n'
            '<header>\n'
            '  <a href="/" class="logo">\n'
            '    <div class="logo-icon">⇄</div>\n'
            '    <div>\n'
            '      <div class="logo-text">Skill Swap</div>\n'
            '      <div class="logo-tag">Trade skills · Learn together</div>\n'
            '    </div>\n'
            '  </a>\n'
            '  <nav>\n'
            '    <a href="/" style="color:#cbd5e1;text-decoration:none;padding:0.38rem 0.85rem;border-radius:999px;font-size:0.9rem;">Home</a>\n'
            '    <a href="/skills" style="color:#cbd5e1;text-decoration:none;padding:0.38rem 0.85rem;border-radius:999px;font-size:0.9rem;">Browse Skills</a>\n'
            '    ' + nav_right + '\n'
            '  </nav>\n'
            '</header>\n'
        )
        foot = (
            '\n<!-- ── SKILLBOT CHAT WIDGET ─────────────────────────────── -->\n<style>\n#chat-bubble{position:fixed;bottom:1.5rem;right:1.5rem;z-index:9999;display:flex;flex-direction:column;align-items:flex-end;gap:0.6rem;font-family:system-ui,sans-serif;}\n#chat-toggle{width:56px;height:56px;border-radius:50%;background:linear-gradient(135deg,#38bdf8,#a855f7);border:none;cursor:pointer;font-size:1.5rem;display:flex;align-items:center;justify-content:center;box-shadow:0 8px 24px rgba(56,189,248,0.45);transition:transform 0.2s;}\n#chat-toggle:hover{transform:scale(1.1);}\n#chat-box{width:320px;background:#0f172a;border:1px solid rgba(148,163,184,0.3);border-radius:1.2rem;box-shadow:0 20px 60px rgba(0,0,0,0.7);display:none;flex-direction:column;overflow:hidden;}\n#chat-header{background:linear-gradient(135deg,#38bdf8,#a855f7);padding:0.85rem 1rem;display:flex;align-items:center;justify-content:space-between;}\n#chat-header span{font-weight:700;color:#0f172a;font-size:0.95rem;}\n#chat-close{background:none;border:none;cursor:pointer;font-size:1.1rem;color:#0f172a;line-height:1;}\n#chat-messages{padding:1rem;height:280px;overflow-y:auto;display:flex;flex-direction:column;gap:0.6rem;scrollbar-width:thin;scrollbar-color:rgba(148,163,184,0.3) transparent;}\n.msg{max-width:85%;padding:0.55rem 0.85rem;border-radius:1rem;font-size:0.83rem;line-height:1.45;word-break:break-word;}\n.msg-bot{background:rgba(56,189,248,0.1);border:1px solid rgba(56,189,248,0.2);color:#e2e8f0;align-self:flex-start;border-bottom-left-radius:0.2rem;}\n.msg-user{background:linear-gradient(135deg,#38bdf8,#a855f7);color:#0f172a;align-self:flex-end;font-weight:500;border-bottom-right-radius:0.2rem;}\n.msg-typing{color:#64748b;font-style:italic;font-size:0.78rem;align-self:flex-start;}\n#chat-input-row{display:flex;gap:0.5rem;padding:0.75rem;border-top:1px solid rgba(148,163,184,0.15);}\n#chat-input{flex:1;background:rgba(255,255,255,0.06);border:1px solid rgba(148,163,184,0.25);border-radius:999px;padding:0.5rem 0.85rem;color:#f1f5f9;font-size:0.85rem;outline:none;}\n#chat-input:focus{border-color:#38bdf8;}\n#chat-send{background:linear-gradient(135deg,#38bdf8,#a855f7);border:none;border-radius:50%;width:34px;height:34px;cursor:pointer;font-size:1rem;display:flex;align-items:center;justify-content:center;flex-shrink:0;}\n#chat-badge{position:absolute;top:-4px;right:-4px;background:#f87171;color:#fff;border-radius:50%;width:18px;height:18px;font-size:0.65rem;font-weight:700;display:flex;align-items:center;justify-content:center;}\n</style>\n\n<div id="chat-bubble">\n  <div id="chat-box">\n    <div id="chat-header">\n      <span>🤖 SkillBot</span>\n      <button id="chat-close" onclick="toggleChat()" title="Close">✕</button>\n    </div>\n    <div id="chat-messages">\n      <div class="msg msg-bot">👋 Hi! I\'m <b>SkillBot</b>. Ask me anything about Skill Swap — signing up, skills, roles, or how to get started!</div>\n    </div>\n    <div id="chat-input-row">\n      <input id="chat-input" type="text" placeholder="Ask me anything…" autocomplete="off" onkeydown="if(event.key===\'Enter\')sendMsg()"/>\n      <button id="chat-send" onclick="sendMsg()" title="Send">➤</button>\n    </div>\n  </div>\n  <div style="position:relative;display:inline-block;">\n    <button id="chat-toggle" onclick="toggleChat()" title="Chat with SkillBot">💬</button>\n    <div id="chat-badge">1</div>\n  </div>\n</div>\n\n<script>\nvar chatOpen = false;\nfunction toggleChat(){\n  chatOpen = !chatOpen;\n  var box = document.getElementById(\'chat-box\');\n  box.style.display = chatOpen ? \'flex\' : \'none\';\n  document.getElementById(\'chat-badge\').style.display = \'none\';\n  if(chatOpen) document.getElementById(\'chat-input\').focus();\n}\nfunction appendMsg(text, cls){\n  var msgs = document.getElementById(\'chat-messages\');\n  var d = document.createElement(\'div\');\n  d.className = \'msg \' + cls;\n  d.innerHTML = text;\n  msgs.appendChild(d);\n  msgs.scrollTop = msgs.scrollHeight;\n  return d;\n}\nfunction sendMsg(){\n  var input = document.getElementById(\'chat-input\');\n  var text = input.value.trim();\n  if(!text) return;\n  appendMsg(text, \'msg-user\');\n  input.value = \'\';\n  var typing = appendMsg(\'SkillBot is typing…\', \'msg-typing\');\n  fetch(\'/chat\', {method:\'POST\', headers:{\'Content-Type\':\'application/x-www-form-urlencoded\'}, body:\'message=\'+encodeURIComponent(text)})\n    .then(function(r){ return r.json(); })\n    .then(function(data){\n      typing.remove();\n      appendMsg(data.reply, \'msg-bot\');\n    })\n    .catch(function(){\n      typing.remove();\n      appendMsg(\'⚠️ Could not reach the server. Try again!\', \'msg-bot\');\n    });\n}\n</script>\n<!-- ── END CHAT WIDGET ────────────────────────────────────── -->\n\n<footer>&copy; 2026 Skill Swap &mdash; Academic prototype &mdash; Built with pure Python (no frameworks)</footer>\n'
            '</body>\n'
            '</html>'
        )
        return head + body_html + foot

    # ── page renderers ───────────────────────────────────────────────────────

    def render_home(self):
        skills = load_json(SKILLS_FILE, [])
        cards_html = ""
        for s in skills:
            bg, fg = LEVEL_COLORS.get(s.get("level", ""), ("#e0e7ff", "#3730a3"))
            icon = ROLE_ICONS.get(s.get("owner_role", ""), "👤")
            cards_html += f"""
      <article class="skill-card">
        <div class="skill-title">{sanitize(s['title'])}</div>
        <div class="skill-cat">{sanitize(s['category'])}</div>
        <span class="level-badge" style="background:{bg};color:{fg};">{sanitize(s['level'])}</span>
        <div class="skill-owner">{icon} {sanitize(s['owner_name'])} &middot; {sanitize(s['owner_role'])}</div>
      </article>"""

        body = f"""
<section class="hero">
  <div class="hero-inner">
    <div>
      <div class="hero-eyebrow">✦ Campus Skill Exchange Platform</div>
      <h1 class="hero-title">Swap your skills.<br/><span class="grad">Grow together.</span></h1>
      <p class="hero-subtitle">
        Skill Swap connects students, instructors, and mentors on one campus platform.
        Discover what you want to learn, share what you already know.
      </p>
      <div class="hero-stats">
        <div><span class="stat-val">3</span><span class="stat-label">Roles</span></div>
        <div><span class="stat-val">{len(skills)}</span><span class="stat-label">Active Skills</span></div>
        <div><span class="stat-val">100%</span><span class="stat-label">Free &amp; Open</span></div>
      </div>
      <div class="hero-actions">
        <a href="/signup" class="btn btn-primary">Get Started &rarr;</a>
        <a href="/skills" class="btn btn-ghost">Browse Skills</a>
      </div>
    </div>
    <div></div>
  </div>
</section>

<div style="max-width:1100px;margin:0 auto;width:100%;">
  <section class="features">
    <p class="section-label">Who is it for?</p>
    <h2 class="section-title">One platform, three roles</h2>
    <p class="section-sub">Every member of the campus community has a place on Skill Swap.</p>
    <div class="features-grid">
      <div class="feature-card"><span class="fc-icon">🎓</span><div class="fc-title">Student</div><p class="fc-desc">Enroll in skills you need, offer what you know, and build a portfolio of completed swaps.</p><span class="fc-tag">Learn &amp; Teach</span></div>
      <div class="feature-card"><span class="fc-icon">📖</span><div class="fc-title">Instructor</div><p class="fc-desc">Publish focused skill tracks, share materials, and verify swaps map to course outcomes.</p><span class="fc-tag">Guide</span></div>
      <div class="feature-card"><span class="fc-icon">👨‍👩‍👧</span><div class="fc-title">Parent</div><p class="fc-desc">Track your student's enrolled skills and completions from a simple, clear dashboard.</p><span class="fc-tag">Support</span></div>
    </div>
  </section>
</div>

<div class="skills-wrap">
  <div class="skills-inner">
    <p class="section-label">Live demo data</p>
    <h2 class="section-title">Featured Skills</h2>
    <p class="section-sub">Loaded from <code>skills.json</code>. Enrollment, search &amp; ratings coming in later sprints.</p>
    <div class="skills-grid">{cards_html}</div>
    <div style="text-align:center;margin-top:2rem;">
      <a href="/skills" class="btn btn-ghost">View all skills &rarr;</a>
    </div>
  </div>
</div>"""
        self.send_html(self._page("Home", body))

    # ── SIGN-UP ──────────────────────────────────────────────────────────────

    def render_signup(self, error="", prefill_name="", prefill_email=""):
        alert = f'<div class="alert alert-err">⚠ {sanitize(error)}</div>' if error else ""
        body = f"""
<main>
  <div class="page-wrap auth-wrap">
    <div class="card" style="max-width:440px;width:100%;">
      <div class="auth-tabs">
        <a href="/signup" class="auth-tab active">Create account</a>
        <a href="/login"  class="auth-tab">Login</a>
      </div>
      <h1 class="card-title">Join Skill Swap 🚀</h1>
      <p class="card-sub">Start trading skills with your campus community.</p>
      {alert}
      <form method="POST" action="/do_signup" novalidate>

        <div class="field">
          <label for="name">Full name</label>
          <input id="name" type="text" name="name" placeholder="e.g. Ali Hassan"
                 value="{sanitize(prefill_name)}" required autocomplete="name"/>
        </div>

        <div class="field">
          <label for="email">Email address</label>
          <input id="email" type="email" name="email" placeholder="you@example.com"
                 value="{sanitize(prefill_email)}" required autocomplete="email"/>
          <span class="field-hint">Use your campus or personal email.</span>
        </div>

        <div class="field">
          <label for="password">Password</label>
          <input id="password" type="password" name="password"
                 placeholder="At least 8 characters" required autocomplete="new-password"
                 oninput="updateBar(this.value)"/>
          <div class="pw-bar-wrap"><div class="pw-bar" id="pwBar"></div></div>
          <span class="field-hint" id="pwHint">Minimum 8 characters, at least one number.</span>
        </div>

        <div class="field">
          <label for="role">I am a…</label>
          <select id="role" name="role" required>
            <option value="student"   >🎓 Student</option>
            <option value="instructor">📖 Instructor</option>
            <option value="parent"    >👨‍👩‍👧 Parent</option>
          </select>
        </div>

        <button class="btn btn-primary" type="submit" style="margin-top:0.4rem;width:100%;justify-content:center;">
          Create my account &rarr;
        </button>

      </form>
      <div class="divider">already have an account?</div>
      <a href="/login" class="btn btn-ghost" style="width:100%;justify-content:center;">Login instead</a>
    </div>
  </div>
</main>
<script>
function updateBar(pw) {{
  var bar = document.getElementById("pwBar");
  var hint = document.getElementById("pwHint");
  var score = 0;
  if (pw.length >= 8)  score++;
  if (pw.length >= 12) score++;
  if (/[0-9]/.test(pw)) score++;
  if (/[^a-zA-Z0-9]/.test(pw)) score++;
  var pct  = [0, 30, 55, 80, 100][score];
  var clrs = ["#f87171","#fb923c","#facc15","#4ade80","#22d3ee"];
  var msgs = ["Too short","Weak","Fair","Good","Strong"];
  bar.style.width = pct + "%";
  bar.style.background = clrs[score];
  hint.textContent = score === 0 ? "Minimum 8 characters, at least one number." : msgs[score];
}}
function removeTag(btn, field) {{
  var hiddenId = field === 'skills' ? 'skills_input' : 'interests';
  var hidden   = document.getElementById(hiddenId);
  var label    = btn.parentElement.childNodes[0].textContent.trim();
  var existing = hidden.value ? hidden.value.split(',').map(function(t){{return t.trim();}}).filter(Boolean) : [];
  hidden.value = existing.filter(function(t){{return t !== label;}}).join(',');
  btn.parentElement.remove();
}}
</script>"""
        self.send_html(self._page("Sign Up", body, show_login_cta=False))

    def handle_signup(self):
        data  = self.read_body()
        name  = data.get("name",  [""])[0].strip()
        email = data.get("email", [""])[0].strip().lower()
        pw    = data.get("password", [""])[0]
        role  = data.get("role",  ["student"])[0]
        skills_raw   = data.get("skills_input", [""])[0].strip()
        interests_raw = data.get("interests",   [""])[0].strip()

        # ── Acceptance Criteria validations ─────────────────────────────────
        # AC1: all fields required
        if not name or not email or not pw:
            return self.render_signup("All fields are required.", name, email)

        # AC2: valid email format
        if not is_valid_email(email):
            return self.render_signup("Please enter a valid email address.", name, email)

        # AC3: password minimum 8 chars + at least 1 digit
        if len(pw) < 8:
            return self.render_signup("Password must be at least 8 characters.", name, email)
        if not re.search(r"\d", pw):
            return self.render_signup("Password must contain at least one number.", name, email)

        # AC4: email must be unique
        users = load_json(USERS_FILE, [])
        if any(u.get("email") == email for u in users):
            return self.render_signup("An account with that email already exists. Try logging in.", name, email)

        def _parse(raw):
            return [t.strip() for t in raw.split(",") if t.strip()][:20]

        new_user = {
            "id":       next_user_id(users),
            "name":     name,
            "email":    email,
            "password": hash_password(pw),
            "role":     role,
        }
        if role in ("student", "instructor", "parent"):
            new_user["skills_list"] = _parse(skills_raw)
            new_user["interests"]   = _parse(interests_raw)
        users.append(new_user)
        save_json(USERS_FILE, users)

        # AC6: create session + redirect to dashboard (logged in immediately)
        token  = create_session(email)
        cookie = f"ss_session={token}; Path=/; HttpOnly; SameSite=Lax"
        self.redirect("/dashboard?new=1", set_cookie=cookie)

    # ── LOGIN ────────────────────────────────────────────────────────────────

    def render_login(self, error="", prefill_email=""):
        alert = f'<div class="alert alert-err">⚠ {sanitize(error)}</div>' if error else ""
        body = f"""
<main>
  <div class="page-wrap auth-wrap">
    <div class="card" style="max-width:420px;width:100%;">
      <div class="auth-tabs">
        <a href="/signup" class="auth-tab">Create account</a>
        <a href="/login"  class="auth-tab active">Login</a>
      </div>
      <h1 class="card-title">Welcome back 👋</h1>
      <p class="card-sub">Sign in to access your Skill Swap dashboard.</p>
      {alert}
      <form method="POST" action="/do_login">
        <div class="field">
          <label for="email">Email address</label>
          <input id="email" type="email" name="email"
                 placeholder="you@example.com" value="{sanitize(prefill_email)}" required/>
        </div>
        <div class="field">
          <label for="password">Password</label>
          <input id="password" type="password" name="password" placeholder="Your password" required/>
        </div>
        <button class="btn btn-primary" type="submit" style="margin-top:0.4rem;width:100%;justify-content:center;">
          Login &rarr;
        </button>
      </form>
      <div class="divider">don't have an account?</div>
      <a href="/signup" class="btn btn-ghost" style="width:100%;justify-content:center;">Create account</a>
    </div>
  </div>
</main>"""
        self.send_html(self._page("Login", body, show_login_cta=False))

    def handle_login(self):
        data  = self.read_body()
        email = data.get("email", [""])[0].strip().lower()
        pw    = data.get("password", [""])[0]

        if not email or not pw:
            return self.render_login("Please enter your email and password.", email)

        users = load_json(USERS_FILE, [])
        user  = next((u for u in users if u.get("email") == email), None)

        if not user or not verify_password(pw, user.get("password", "")):
            return self.render_login("Incorrect email or password.", email)

        token  = create_session(email)
        cookie = f"ss_session={token}; Path=/; HttpOnly; SameSite=Lax"
        self.redirect("/dashboard", set_cookie=cookie)

    # ── DASHBOARD ────────────────────────────────────────────────────────────


    def handle_logout(self):
        delete_session(self.headers.get("Cookie", ""))
        cookie = "ss_session=; Path=/; Max-Age=0"
        self.redirect("/", set_cookie=cookie)

    def handle_chat(self):
        data    = self.read_body()
        message = data.get("message", [""])[0].strip()
        reply   = chatbot_reply(message) if message else "Please type a message first! 😊"
        resp    = json.dumps({"reply": reply})
        b       = resp.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def render_dashboard(self):
        user = self.get_session_user()
        if not user:
            return self.redirect("/login")
        qs     = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        is_new = qs.get("new", [""])[0] == "1"
        name   = sanitize(user.get("name",  "Guest"))
        role   = user.get("role", "student")
        email  = user.get("email", "")
        intros = {
            "student":    ("Browse skills, enroll in swaps, and track everything you're learning.", "📚"),
            "instructor": ("Create guided skill tracks and see which students are joining your swaps.", "📋"),
            "admin":      ("Oversee users, skills, and platform health from one central place.", "📊"),
            "parent":     ("Stay updated on your student's enrolled skills and completions.", "🔔"),
        }
        intro, icon = intros.get(role, ("Explore the platform.", "👋"))

        complete_btn = ""
        if role in ("student", "instructor", "parent") and email:
            edit_url = f"/edit_profile?email={urllib.parse.quote(email)}"
            complete_btn = f"""
      <div style="margin-top:1.2rem;padding:1rem;border-radius:0.9rem;
                  background:rgba(56,189,248,0.08);border:1px solid rgba(56,189,248,0.25);">
        <p style="font-size:0.88rem;color:#cbd5e1;margin-bottom:0.6rem;">
          ✨ <strong>One more step!</strong> Complete your profile by adding your skills and interests so others can find you.
        </p>
        <a href="{edit_url}" class="btn btn-primary" style="font-size:0.88rem;">
          Complete your profile &rarr;
        </a>
      </div>"""

        welcome = (
            f'<div class="alert alert-ok" style="margin-bottom:1rem;">'
            f'🎉 Account created! Welcome to Skill Swap, <strong>{name}</strong>.</div>'
            if is_new else ""
        )

        body = f"""
<main>
  <div class="page-wrap" style="display:flex;align-items:flex-start;justify-content:center;">
    <div class="card" style="max-width:520px;width:100%;margin-top:1rem;">
      {welcome}
      <div style="font-size:2.5rem;margin-bottom:0.5rem;">{icon}</div>
      <h1 class="card-title">{role.capitalize()} Dashboard</h1>
      <p class="card-sub">
        Welcome, <strong>{name}</strong>. {sanitize(intro)}<br/><br/>
        In upcoming sprints this page will show enrolled skills, materials, progress tracking, and notifications.
      </p>
      <div style="display:flex;flex-wrap:wrap;gap:0.7rem;margin-top:0.5rem;">
        <a href="/skills" class="btn btn-primary">Browse Skills</a>
        <a href="/"       class="btn btn-ghost">Back to Home</a>
      </div>
      {complete_btn}
    </div>
  </div>
</main>"""
        self.send_html(self._page(f"{role.capitalize()} Dashboard", body, show_login_cta=False))


    # ── PROFILE ──────────────────────────────────────────────────────────────

    def _user_from_qs(self):
        """Helper: returns (user_dict, email) from ?email= query param."""
        qs    = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        email = qs.get("email", [""])[0].strip().lower()
        users = load_json(USERS_FILE, [])
        user  = next((u for u in users if u.get("email") == email), None)
        return user, email

    def render_profile(self):
        user, email = self._user_from_qs()
        if not user:
            return self.redirect("/login")

        qs      = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        success = qs.get("success", [""])[0]
        success_html = (f'<div class="alert alert-ok">✓ {sanitize(success)}</div>'
                        if success else "")

        name       = sanitize(user.get("name",       "Unknown"))
        role       = user.get("role", "student")
        uid        = user.get("id",   "—")
        bio        = sanitize(user.get("bio",        ""))
        phone      = sanitize(user.get("phone",      ""))
        address    = sanitize(user.get("address",    ""))
        education  = sanitize(user.get("education",  ""))
        experience = sanitize(user.get("experience", ""))

        role_info = {
            "student":    ("🎓", "Student",       "Browse skills, propose swaps, and track your learning progress."),
            "instructor": ("📖", "Instructor",    "Post skill tracks, approve swap requests, and guide learners."),
            "admin":      ("🛡️", "Administrator", "Manage users, skill categories, and platform health."),
            "parent":     ("👨‍👩‍👧", "Parent",      "Track your student\'s enrolled skills and completions."),
        }.get(role, ("👤", role.capitalize(), ""))
        icon, role_label, role_intro = role_info

        skills    = load_json(SKILLS_FILE, [])
        my_skills = [s for s in skills if s.get("owner_name", "").lower() == user.get("name", "").lower()]
        skills_html = ""
        for s in my_skills:
            bg, fg = LEVEL_COLORS.get(s.get("level", ""), ("#e0e7ff", "#3730a3"))
            skills_html += (
                f'<article class="skill-card">'
                f'<div class="skill-title">{sanitize(s["title"])}</div>'
                f'<div class="skill-cat">{sanitize(s["category"])}</div>'
                f'<span class="level-badge" style="background:{bg};color:{fg};">{sanitize(s["level"])}</span>'
                f'</article>'
            )
        if not skills_html:
            skills_html = ('<p style="color:var(--muted);font-size:0.9rem;">'
                           'No skills listed yet. '
                           '<a href="/skills" style="color:var(--accent1);">Browse skills</a>'
                           ' to get started.</p>')

        initials  = "".join(w[0].upper() for w in user.get("name", "?").split()[:2])
        edit_url  = f"/edit_profile?email={urllib.parse.quote(email)}"

        # ── helper: render an info row only when value is present ────────────
        def info_row(label, value, icon_char):
            if not value:
                return (f'<div style="display:flex;align-items:center;gap:0.6rem;'
                        f'padding:0.55rem 0;border-bottom:1px solid var(--border);">'
                        f'<span style="font-size:1rem;">{icon_char}</span>'
                        f'<span style="font-size:0.82rem;color:var(--muted);flex:1;">{label}</span>'
                        f'<span style="font-size:0.82rem;color:var(--muted);font-style:italic;">Not set</span>'
                        f'</div>')
            return (f'<div style="display:flex;align-items:flex-start;gap:0.6rem;'
                    f'padding:0.55rem 0;border-bottom:1px solid var(--border);">'
                    f'<span style="font-size:1rem;margin-top:1px;">{icon_char}</span>'
                    f'<span style="font-size:0.82rem;color:var(--muted);min-width:90px;">{label}</span>'
                    f'<span style="font-size:0.88rem;color:var(--text);flex:1;">{value}</span>'
                    f'</div>')

        contact_rows = (
            info_row("Email",     sanitize(email), "✉️") +
            info_row("Phone",     phone,           "📞") +
            info_row("Address",   address,         "📍")
        )
        background_rows = (
            info_row("Education", education,  "🎓") +
            info_row("Experience",experience, "💼")
        )

        # skills & interests tag blocks (students only)
        def render_tags(items, accent):
            if not items:
                return '<p style="font-size:0.82rem;color:var(--muted);font-style:italic;">None added yet.</p>'
            return " ".join(
                f'<span style="display:inline-block;margin:0.2rem;padding:0.25rem 0.75rem;'
                f'border-radius:999px;font-size:0.78rem;font-weight:600;'
                f'background:{accent}22;border:1px solid {accent}66;color:{accent};">'
                f'{sanitize(t)}</span>'
                for t in items
            )

        student_tags_html = ""
        if role in ("student", "instructor", "parent"):
            skills_tags    = render_tags(user.get("skills_list", []), "#38bdf8")
            interests_tags = render_tags(user.get("interests",   []), "#a855f7")
            student_tags_html = f"""
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:1.2rem;margin-bottom:1.2rem;">
      <div class="card">
        <div class="card-title" style="font-size:0.95rem;margin-bottom:0.5rem;">🛠 My Skills</div>
        <p style="font-size:0.78rem;color:var(--muted);margin-bottom:0.6rem;">What I can offer or teach</p>
        <div>{skills_tags}</div>
      </div>
      <div class="card">
        <div class="card-title" style="font-size:0.95rem;margin-bottom:0.5rem;">💡 My Interests</div>
        <p style="font-size:0.78rem;color:var(--muted);margin-bottom:0.6rem;">What I want to learn</p>
        <div>{interests_tags}</div>
      </div>
    </div>"""
        bio_block = (
            f'<p style="font-size:0.88rem;color:#cbd5e1;margin-top:0.5rem;line-height:1.6;">{bio}</p>'
            if bio else
            '<p style="font-size:0.82rem;color:var(--muted);font-style:italic;margin-top:0.4rem;">No bio yet.</p>'
        )

        body = f"""
<main>
  <div class="page-wrap" style="max-width:760px;">
    {success_html}

    <!-- ── identity card ── -->
    <div class="card" style="display:flex;align-items:center;gap:1.4rem;flex-wrap:wrap;margin-bottom:1.2rem;">
      <div style="width:72px;height:72px;border-radius:50%;flex-shrink:0;
                  background:var(--grad);
                  display:flex;align-items:center;justify-content:center;
                  font-size:1.5rem;font-weight:700;color:#0f172a;">
        {initials}
      </div>
      <div style="flex:1;min-width:0;">
        <div style="font-size:1.3rem;font-weight:700;margin-bottom:0.15rem;">{name}</div>
        <div style="font-size:0.82rem;color:var(--muted);margin-bottom:0.5rem;">
          ID&nbsp;#{uid} &nbsp;&middot;&nbsp;
          <span style="display:inline-block;padding:0.15rem 0.65rem;border-radius:999px;
                       font-size:0.72rem;font-weight:600;
                       background:var(--grad);color:#0f172a;">
            {icon} {role_label}
          </span>
        </div>
        {bio_block}
      </div>
      <a href="{edit_url}" class="btn btn-ghost"
         style="font-size:0.85rem;white-space:nowrap;align-self:flex-start;">
        ✏ Edit Profile
      </a>
    </div>

    <!-- ── two-column layout ── -->
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:1.2rem;margin-bottom:1.2rem;">

      <!-- Contact info -->
      <div class="card">
        <div class="card-title" style="font-size:0.95rem;margin-bottom:0.2rem;">Contact Info</div>
        <p class="card-sub" style="font-size:0.78rem;margin-bottom:0.6rem;">How to reach you</p>
        <div style="border-top:1px solid var(--border);">
          {contact_rows}
        </div>
      </div>

      <!-- Background -->
      <div class="card">
        <div class="card-title" style="font-size:0.95rem;margin-bottom:0.2rem;">Background</div>
        <p class="card-sub" style="font-size:0.78rem;margin-bottom:0.6rem;">Education &amp; experience</p>
        <div style="border-top:1px solid var(--border);">
          {background_rows}
        </div>
      </div>

    </div>

    {student_tags_html}

    <!-- ── actions ── -->
    <div style="display:flex;gap:0.7rem;flex-wrap:wrap;margin-bottom:2.5rem;">
      <a href="/skills" class="btn btn-primary">Browse Skills</a>
      <a href="/dashboard?name={urllib.parse.quote(user.get('name',''))}&role={role}"
         class="btn btn-ghost">Dashboard</a>
      <a href="/login"  class="btn btn-ghost">Log out</a>
    </div>
  </div>
</main>

<style>
@media(max-width:600px){{
  div[style*="grid-template-columns:1fr 1fr"]{{
    grid-template-columns:1fr !important;
  }}
}}
</style>"""
        self.send_html(self._page("My Profile", body, show_login_cta=False))

    def render_edit_profile(self):
        qs    = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        error = qs.get("error", [""])[0]
        user, email = self._user_from_qs()
        if not user:
            return self.redirect("/login")

        # pre-fill all fields
        is_student = user.get("role", "student") in ("student", "instructor", "parent")
        val = {
            "name":         sanitize(user.get("name",         "")),
            "bio":          sanitize(user.get("bio",          "")),
            "phone":        sanitize(user.get("phone",        "")),
            "address":      sanitize(user.get("address",      "")),
            "education":    sanitize(user.get("education",    "")),
            "experience":   sanitize(user.get("experience",   "")),
            "skills_input": sanitize(", ".join(user.get("skills_list", []))),
            "interests":    sanitize(", ".join(user.get("interests",   []))),
        }
        alert_html  = (f'<div class="alert alert-err">⚠ {sanitize(error)}</div>' if error else "")
        if is_student:
            existing_skills    = val["skills_input"]
            existing_interests = val["interests"]
            student_section = f"""
        <p style="font-size:0.75rem;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;
                  color:var(--accent1);margin:1.1rem 0 0.75rem;">Skills &amp; Interests</p>

        <!-- hidden fields submitted with form -->
        <input type="hidden" id="skills_input" name="skills_input" value="{existing_skills}"/>
        <input type="hidden" id="interests"    name="interests"    value="{existing_interests}"/>

        <!-- ── Skills tag widget ── -->
        <div class="field">
          <label>&#128295; My Skills</label>
          <div id="skills-tags" style="display:flex;flex-wrap:wrap;gap:0.4rem;min-height:2rem;
               padding:0.5rem;border-radius:0.65rem;border:1px solid var(--border);
               background:rgba(15,23,42,0.95);cursor:text;" onclick="document.getElementById('skills-text').focus()">
          </div>
          <div style="display:flex;gap:0.5rem;margin-top:0.4rem;">
            <input id="skills-text" type="text" placeholder="Type a skill and press Enter or Add"
                   style="flex:1;padding:0.5rem 0.75rem;border-radius:0.65rem;border:1px solid var(--border);
                          background:rgba(15,23,42,0.95);color:var(--text);font-size:0.88rem;outline:none;"
                   onkeydown="if(event.key==='Enter'){{event.preventDefault();addTag('skills')}}"/>
            <button type="button" onclick="addTag('skills')"
                    style="padding:0.5rem 1rem;border-radius:0.65rem;border:none;cursor:pointer;
                           background:linear-gradient(135deg,#38bdf8,#a855f7);color:#0f172a;font-weight:600;font-size:0.85rem;">
              Add
            </button>
          </div>
          <span class="field-hint">Type one skill at a time and press <b>Enter</b> or click <b>Add</b>.</span>
        </div>

        <!-- ── Interests tag widget ── -->
        <div class="field">
          <label>&#128161; My Interests</label>
          <div id="interests-tags" style="display:flex;flex-wrap:wrap;gap:0.4rem;min-height:2rem;
               padding:0.5rem;border-radius:0.65rem;border:1px solid var(--border);
               background:rgba(15,23,42,0.95);cursor:text;" onclick="document.getElementById('interests-text').focus()">
          </div>
          <div style="display:flex;gap:0.5rem;margin-top:0.4rem;">
            <input id="interests-text" type="text" placeholder="Type an interest and press Enter or Add"
                   style="flex:1;padding:0.5rem 0.75rem;border-radius:0.65rem;border:1px solid var(--border);
                          background:rgba(15,23,42,0.95);color:var(--text);font-size:0.88rem;outline:none;"
                   onkeydown="if(event.key==='Enter'){{event.preventDefault();addTag('interests')}}"/>
            <button type="button" onclick="addTag('interests')"
                    style="padding:0.5rem 1rem;border-radius:0.65rem;border:none;cursor:pointer;
                           background:linear-gradient(135deg,#38bdf8,#a855f7);color:#0f172a;font-weight:600;font-size:0.85rem;">
              Add
            </button>
          </div>
          <span class="field-hint">Type one interest at a time and press <b>Enter</b> or click <b>Add</b>.</span>
        </div>

        <script>
        (function(){{
          function initTags(field, hiddenId, containerID) {{
            var hidden    = document.getElementById(hiddenId);
            var container = document.getElementById(containerID);
            var tags = hidden.value ? hidden.value.split(',').map(function(t){{return t.trim();}}).filter(Boolean) : [];
            tags.forEach(function(t){{ renderTag(t, field, hiddenId, containerID); }});
          }}
          function renderTag(text, field, hiddenId, containerID) {{
            var container = document.getElementById(containerID);
            var span = document.createElement('span');
            span.style.cssText = 'display:inline-flex;align-items:center;gap:0.3rem;padding:0.22rem 0.65rem;' +
              'border-radius:999px;font-size:0.78rem;font-weight:600;' +
              (field==='skills' ? 'background:rgba(56,189,248,0.15);border:1px solid rgba(56,189,248,0.4);color:#38bdf8;'
                                : 'background:rgba(168,85,247,0.15);border:1px solid rgba(168,85,247,0.4);color:#a855f7;');
            span.innerHTML = text + '<button type="button" onclick="removeTag(this,\\'' + field + '\\')" ' +
              'style="background:none;border:none;cursor:pointer;color:inherit;font-size:0.85rem;line-height:1;padding:0;">&#x2715;</button>';
            container.appendChild(span);
          }}
          window.addTag = function(field) {{
            var inputEl   = document.getElementById(field + '-text');
            var hiddenId  = field === 'skills' ? 'skills_input' : 'interests';
            var containerID = field + '-tags';
            var text = inputEl.value.trim();
            if (!text) return;
            var hidden = document.getElementById(hiddenId);
            var existing = hidden.value ? hidden.value.split(',').map(function(t){{return t.trim();}}).filter(Boolean) : [];
            if (existing.length >= 20) {{ alert('Maximum 20 tags allowed.'); return; }}
            if (existing.map(function(t){{return t.toLowerCase();}}).indexOf(text.toLowerCase()) !== -1) {{
              inputEl.value = ''; return;
            }}
            existing.push(text);
            hidden.value = existing.join(',');
            renderTag(text, field, hiddenId, containerID);
            inputEl.value = '';
          }};
          window.removeTag = function(btn, field) {{
            var hiddenId = field === 'skills' ? 'skills_input' : 'interests';
            var hidden   = document.getElementById(hiddenId);
            var label    = btn.parentElement.childNodes[0].textContent.trim();
            var existing = hidden.value ? hidden.value.split(',').map(function(t){{return t.trim();}}).filter(Boolean) : [];
            hidden.value = existing.filter(function(t){{return t !== label;}}).join(',');
            btn.parentElement.remove();
          }};
          initTags('skills',    'skills_input', 'skills-tags');
          initTags('interests', 'interests',    'interests-tags');
        }})();
        </script>"""
        else:
            student_section = ""
        profile_url = f"/profile?email={urllib.parse.quote(email)}"

        ta_style = ("resize:vertical;padding:0.6rem 0.85rem;border-radius:0.65rem;"
                    "border:1px solid var(--border);background:rgba(15,23,42,0.95);"
                    "color:var(--text);font-size:0.92rem;outline:none;"
                    "font-family:inherit;width:100%;")

        body = f"""
<main>
  <div class="page-wrap" style="display:flex;align-items:flex-start;justify-content:center;">
    <div class="card" style="max-width:540px;width:100%;">
      <h1 class="card-title">Edit Profile ✏</h1>
      <p class="card-sub">Keep your profile up to date.</p>
      {alert_html}
      <form method="POST" action="/do_edit_profile" novalidate>
        <input type="hidden" name="email" value="{sanitize(email)}" />

        <!-- ── Basic info ── -->
        <p style="font-size:0.75rem;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;
                  color:var(--accent1);margin:0.2rem 0 0.75rem;">Basic Info</p>

        <div class="field">
          <label for="name">Full name <span style="color:var(--err);">*</span></label>
          <input id="name" type="text" name="name" value="{val['name']}"
                 placeholder="Your full name" required maxlength="100"/>
        </div>

        <div class="field">
          <label for="bio">Bio</label>
          <textarea id="bio" name="bio" rows="3" maxlength="300"
                    placeholder="A short sentence about yourself…"
                    style="{ta_style}">{val['bio']}</textarea>
          <span class="field-hint">Max 300 characters.</span>
        </div>

        <!-- ── Contact ── -->
        <p style="font-size:0.75rem;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;
                  color:var(--accent1);margin:1.1rem 0 0.75rem;">Contact</p>

        <div class="field">
          <label for="phone">📞 Phone number</label>
          <input id="phone" type="tel" name="phone" value="{val['phone']}"
                 placeholder="e.g. +1 416 555 0100" maxlength="30"/>
        </div>

        <div class="field">
          <label for="address">📍 Address</label>
          <input id="address" type="text" name="address" value="{val['address']}"
                 placeholder="City, Province / Country" maxlength="200"/>
        </div>

        <!-- ── Background ── -->
        <p style="font-size:0.75rem;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;
                  color:var(--accent1);margin:1.1rem 0 0.75rem;">Background</p>

        <div class="field">
          <label for="education">🎓 Education</label>
          <textarea id="education" name="education" rows="2" maxlength="400"
                    placeholder="e.g. Computer Science — Centennial College, 2025"
                    style="{ta_style}">{val['education']}</textarea>
        </div>

        <div class="field">
          <label for="experience">💼 Experience</label>
          <textarea id="experience" name="experience" rows="3" maxlength="600"
                    placeholder="e.g. Junior Dev Intern at Acme Corp (Summer 2024) — worked on REST APIs…"
                    style="{ta_style}">{val['experience']}</textarea>
          <span class="field-hint">Max 600 characters.</span>
        </div>

        {student_section}

        <!-- ── Buttons ── -->
        <div style="display:flex;gap:0.6rem;margin-top:1rem;">
          <button class="btn btn-primary" type="submit" style="flex:1;justify-content:center;">
            Save changes
          </button>
          <a href="{profile_url}" class="btn btn-ghost" style="flex:1;justify-content:center;">
            Cancel
          </a>
        </div>

      </form>
    </div>
  </div>
</main>"""
        self.send_html(self._page("Edit Profile", body, show_login_cta=False))

    def handle_edit_profile(self):
        data = self.read_body()
        email      = data.get("email",      [""])[0].strip().lower()
        name       = data.get("name",       [""])[0].strip()
        bio        = data.get("bio",        [""])[0].strip()
        phone      = data.get("phone",      [""])[0].strip()
        address    = data.get("address",    [""])[0].strip()
        education  = data.get("education",  [""])[0].strip()
        experience   = data.get("experience",   [""])[0].strip()
        skills_input = data.get("skills_input", [""])[0].strip()
        interests    = data.get("interests",    [""])[0].strip()

        # validation
        if not name:
            p = urllib.parse.urlencode({"email": email, "error": "Full name is required."})
            return self.redirect("/edit_profile?" + p)
        if len(name) > 100:
            p = urllib.parse.urlencode({"email": email, "error": "Name must be 100 characters or fewer."})
            return self.redirect("/edit_profile?" + p)

        users   = load_json(USERS_FILE, [])
        updated = False
        for u in users:
            if u.get("email") == email:
                u["name"]       = name
                u["bio"]        = bio[:300]
                u["phone"]      = phone[:30]
                u["address"]    = address[:200]
                u["education"]  = education[:400]
                u["experience"] = experience[:600]
                if u.get("role") in ("student", "instructor", "parent"):
                    import re as _re
                    def _parse_tags(raw):
                        # split on comma or semicolon, then strip whitespace
                        parts = _re.split(r"[,;]+", raw)
                        return [p.strip() for p in parts if p.strip()][:20]
                    u["skills_list"] = _parse_tags(skills_input)
                    u["interests"]   = _parse_tags(interests)
                updated = True
                break

        if not updated:
            return self.redirect("/login")

        save_json(USERS_FILE, users)
        p = urllib.parse.urlencode({"email": email, "success": "Profile updated successfully."})
        self.redirect("/profile?" + p)

        # ── BROWSE SKILLS ────────────────────────────────────────────────────────

    def render_skills(self):
        skills = load_json(SKILLS_FILE, [])
        cards_html = ""
        for s in skills:
            bg, fg = LEVEL_COLORS.get(s.get("level", ""), ("#e0e7ff", "#3730a3"))
            icon = ROLE_ICONS.get(s.get("owner_role", ""), "👤")
            cards_html += f"""
      <article class="skill-card">
        <div class="skill-title">{sanitize(s['title'])}</div>
        <div class="skill-cat">{sanitize(s['category'])}</div>
        <span class="level-badge" style="background:{bg};color:{fg};">{sanitize(s['level'])}</span>
        <div class="skill-owner">{icon} {sanitize(s['owner_name'])} &middot; {sanitize(s['owner_role'])}</div>
      </article>"""

        body = f"""
<main>
  <div class="page-wrap">
    <div style="margin-bottom:2rem;">
      <p class="section-label">Skill Library</p>
      <h1 style="font-size:2rem;font-weight:800;margin-bottom:0.4rem;">Browse Skills</h1>
      <p style="color:var(--muted);max-width:30rem;font-size:0.92rem;">
        Showing all {len(skills)} skills from <code>skills.json</code>.
        Search, filters, and enrollment will be added in a later sprint.
      </p>
    </div>
    <div class="skills-grid">{cards_html}</div>
  </div>
</main>"""
        self.send_html(self._page("Browse Skills", body))


# ── run ───────────────────────────────────────────────────────────────────────

with socketserver.TCPServer(("", PORT), SkillSwapHandler) as httpd:
    print(f"✅  Skill Swap running at http://localhost:{PORT}")
    httpd.serve_forever()