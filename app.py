import io
import json
import os
import re
import sqlite3
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import List

import streamlit as st
import streamlit.components.v1 as components
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

# ----------------------------- App Setup -----------------------------
st.set_page_config(
    page_title="ConceptBridge",
    page_icon="🌉",
    layout="wide",
    initial_sidebar_state="expanded",
)

DB_PATH = "conceptbridge.db"
MODEL = "gemini-3.8-flash"

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap');
    :root { --ink:#17233b; --muted:#718096; --line:#e7ebf2; --purple:#6758e8; --pale:#f5f6fb; }
    .stApp { background:#f7f8fc; color:var(--ink); font-family:'DM Sans',sans-serif; }
    [data-testid="stSidebar"] { background:#151d31; }
    [data-testid="stSidebar"] * { color:#f4f6ff; }
    [data-testid="stSidebar"] .stRadio label { padding:8px 10px; border-radius:10px; }
    [data-testid="stSidebar"] hr { border-color:#303950; }
    .hero { background:white; border:1px solid #e5e4fb; border-radius:16px; padding:26px; margin-bottom:18px; }
    .metric-card { background:white; border:1px solid #e9edf4; border-radius:12px; padding:15px; }
    .metric-value { color:#17233b; font-size:24px; font-weight:700; }
    .panel { background:white; border:1px solid #e9edf4; border-radius:12px; padding:24px; margin-bottom:14px; }
    .stButton button { border-radius:8px; font-weight:600; }
    div[data-testid="stExpander"] { background:white; border:1px solid #e9edf4; border-radius:8px; }
    .badge { background:#eef2ff; color:#4338ca; padding:4px 10px; border-radius:6px; font-size:12px; font-weight:bold; }
    footer { visibility:hidden; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ----------------------------- Pydantic Schemas -----------------------------
class ConceptConnection(BaseModel):
    related_concept: str = Field(description="Name of the related concept")
    relationship: str = Field(description="Short relationship label (e.g. 'Extends', 'Opposite of')")
    explanation: str = Field(description="1 sentence explaining the connection")

class LessonResponse(BaseModel):
    explanation: str = Field(description="Clean, simple lesson in Markdown format. Use bullet points and clear headings.")
    connections: List[ConceptConnection] = Field(description="3 to 5 clear concept connections for the mindmap.")
    challenge: str = Field(description="An engaging practice question. Provide EITHER a Multiple Choice Question (list options A/B/C/D), a real-world scenario to solve, or a short-answer question.")

class EvaluationResponse(BaseModel):
    understood: str = Field(description="What the student got right.")
    gap: str = Field(description="Any gaps or wrong choices.")
    improvement: str = Field(description="How to improve.")
    teaching_explanation: str = Field(description="The correct answer explained simply.")
    next_challenge: str = Field(description="A follow-up question (MCQ, scenario, or theory).")

# ----------------------------- Database -----------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS lessons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                level TEXT NOT NULL,
                explanation TEXT NOT NULL,
                connections_json TEXT DEFAULT '[]',
                current_challenge TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'In progress',
                last_reviewed_at TEXT
            )
        """)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(lessons)").fetchall()]
        if "connections_json" not in cols:
            conn.execute("ALTER TABLE lessons ADD COLUMN connections_json TEXT DEFAULT '[]'")
        if "last_reviewed_at" not in cols:
            conn.execute("ALTER TABLE lessons ADD COLUMN last_reviewed_at TEXT")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lesson_id INTEGER NOT NULL,
                challenge TEXT NOT NULL,
                answer TEXT NOT NULL,
                understood TEXT NOT NULL,
                gap TEXT NOT NULL,
                improvement TEXT NOT NULL,
                teaching_explanation TEXT NOT NULL,
                next_challenge TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (lesson_id) REFERENCES lessons(id)
            )
        """)

def query_all(sql, params=()):
    with get_db() as conn:
        return conn.execute(sql, params).fetchall()

def query_one(sql, params=()):
    with get_db() as conn:
        return conn.execute(sql, params).fetchone()

def execute(sql, params=()):
    with get_db() as conn:
        cur = conn.execute(sql, params)
        return cur.lastrowid

init_db()

def get_lesson_connections(row):
    if not row: return []
    raw = row["connections_json"] if "connections_json" in row.keys() else row.get("connections", "[]")
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except:
        return []

# ----------------------------- Spaced Repetition -----------------------------
SPACED_INTERVALS = [1, 3, 7]

def get_repetition_status(lesson, attempt_count: int):
    last_review = None
    if "last_reviewed_at" in lesson.keys():
        last_review = lesson["last_reviewed_at"]
        
    if not last_review:
        last_review = lesson["created_at"]

    try:
        last_dt = datetime.fromisoformat(last_review)
    except Exception:
        last_dt = datetime.now()

    interval_idx = min(attempt_count, len(SPACED_INTERVALS) - 1)
    days_needed = SPACED_INTERVALS[interval_idx]
    due_date = last_dt + timedelta(days=days_needed)
    return {
        "is_due": datetime.now() >= due_date,
        "days_needed": days_needed,
        "due_date": due_date.strftime("%Y-%m-%d")
    }

# ----------------------------- Wikipedia Image Search Helper -----------------------------
def get_concept_cover_image(topic: str):
    """Searches Wikipedia and fetches a real educational image/diagram for the topic."""
    try:
        query = urllib.parse.quote(topic)
        search_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={query}&utf8=&format=json&srlimit=1"
        
        req = urllib.request.Request(search_url, headers={'User-Agent': 'ConceptBridgeApp/1.0'})
        with urllib.request.urlopen(req) as response:
            search_data = json.loads(response.read().decode())
            
        if search_data.get("query", {}).get("search"):
            title = search_data["query"]["search"][0]["title"]
            
            image_url = f"https://en.wikipedia.org/w/api.php?action=query&titles={urllib.parse.quote(title)}&prop=pageimages&format=json&pithumbsize=1000"
            req2 = urllib.request.Request(image_url, headers={'User-Agent': 'ConceptBridgeApp/1.0'})
            with urllib.request.urlopen(req2) as response2:
                image_data = json.loads(response2.read().decode())
                
            pages = image_data.get("query", {}).get("pages", {})
            for page_id, page_info in pages.items():
                if "thumbnail" in page_info:
                    return page_info["thumbnail"]["source"]
    except Exception as e:
        print(f"Wikipedia search failed: {e}")
        pass
    
    safe_topic = urllib.parse.quote(topic)
    return f"https://fakeimg.pl/1200x400/17233b/ffffff?text={safe_topic}&font=museo"

# ----------------------------- AI Client -----------------------------
def get_client():
    key = st.secrets.get("GEMINI_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")
    return genai.Client(api_key=key) if key else None

def friendly_ai_error(exc):
    return f"AI Generation error: {str(exc)[:300]}"

def safe_str(s):
    """Strips special characters to prevent Mermaid from crashing (bomb logo fix)"""
    s = re.sub(r'[^a-zA-Z0-9 ]', '', str(s))
    return " ".join(s.split()) or "Concept"

# ----------------------------- Graph Renderers -----------------------------
def render_concept_graph(topic: str, connections: list):
    """Renders a clean Mindmap inside the lesson."""
    lines = ["graph TD", f'    ROOT["{safe_str(topic)}"]:::root']
    for idx, conn in enumerate(connections):
        rel_concept = safe_str(conn.get("related_concept", "Concept"))
        rel_label = safe_str(conn.get("relationship", "Connects to"))
        lines.append(f'    N{idx}["{rel_concept}"]')
        lines.append(f'    ROOT -->|"{rel_label}"| N{idx}')
    
    lines.append("    classDef root fill:#d8d4fd,stroke:#6758e8,stroke-width:2px,font-weight:bold;")
    mermaid_code = "\n".join(lines)
    html = f"""
    <div class="mermaid" style="display:flex; justify-content:center; background:#f8fafc; padding:20px; border-radius:12px; margin:20px 0;">
        {mermaid_code}
    </div>
    <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
        mermaid.initialize({{ startOnLoad: true, theme: 'neutral' }});
    </script>
    """
    components.html(html, height=300)

# ----------------------------- Session & Navigation -----------------------------
if "page" not in st.session_state: st.session_state.page = "Home"
if "active_lesson_id" not in st.session_state: st.session_state.active_lesson_id = None

with st.sidebar:
    st.markdown("## 🌉 ConceptBridge")
    st.divider()
    pages = ["Home", "My Learning Path", "Knowledge Network", "Progress"]
    selected = st.radio("Navigation", pages, index=pages.index(st.session_state.page) if st.session_state.page in pages else 0)
    if selected != st.session_state.page:
        st.session_state.page = selected
        st.rerun()

def open_lesson(lesson_id):
    st.session_state.active_lesson_id = int(lesson_id)
    st.session_state.page = "My Learning Path"
    st.rerun()

# ----------------------------- Home Page -----------------------------
if st.session_state.page == "Home":
    st.markdown("<div class='hero'><h2>What do you want to learn today?</h2><p>Generate clean lessons with visual mindmaps and smart challenges (MCQs & Scenarios).</p></div>", unsafe_allow_html=True)
    
    with st.form("new_path_form"):
        topic = st.text_input("Enter Topic (e.g. Memory Management, Supply Chain, React Hooks)")
        level = st.selectbox("Level", ["Beginner", "Intermediate", "Advanced"])
        submit = st.form_submit_button("Generate Lesson", type="primary", use_container_width=True)
    
    if submit and topic.strip():
        with st.spinner("Building your clean lesson and mindmap..."):
            try:
                client = get_client()
                prompt = f"Create a clear, simple learning module about {topic.strip()} ({level})."
                resp = client.models.generate_content(
                    model=MODEL, contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=LessonResponse, temperature=0.4)
                )
                data = json.loads(resp.text)
                now_str = datetime.now().isoformat()
                lid = execute(
                    "INSERT INTO lessons (topic, level, explanation, connections_json, current_challenge, created_at, status, last_reviewed_at) VALUES (?, ?, ?, ?, ?, ?, 'In progress', ?)",
                    (topic.strip(), level, data["explanation"], json.dumps(data["connections"]), data["challenge"], now_str, now_str)
                )
                open_lesson(lid)
            except Exception as e:
                st.error(friendly_ai_error(e))

    st.write("---")
    st.markdown("### 📂 Recent Sessions")
    lessons = query_all("SELECT * FROM lessons ORDER BY id DESC LIMIT 5")
    for l in lessons:
        if st.button(f"📖 {l['topic']} ({l['level']})", key=f"rec_{l['id']}", use_container_width=True):
            open_lesson(l['id'])

# ----------------------------- My Learning Path -----------------------------
elif st.session_state.page == "My Learning Path":
    lessons = query_all("SELECT * FROM lessons ORDER BY id DESC")
    if not lessons:
        st.info("No lessons yet. Go to Home to start.")
    else:
        active_id = st.session_state.active_lesson_id or lessons[0]["id"]
        active = query_one("SELECT * FROM lessons WHERE id = ?", (active_id,))
        if not active: active = lessons[0]

        attempts = query_all("SELECT * FROM attempts WHERE lesson_id = ? ORDER BY id DESC", (active["id"],))
        conns = get_lesson_connections(active)

        # Header
        st.title(active['topic'])
        st.markdown(f"<span class='badge'>{active['level']}</span> &nbsp; Status: **{active['status']}**", unsafe_allow_html=True)
        
        # Display the real-world Wikipedia image
        st.image(get_concept_cover_image(active['topic']), use_container_width=True)
        
        # 1. The Clean Explanation
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        st.markdown(active["explanation"])
        
        # 2. The Mindmap (Directly inside the lesson)
        st.markdown("### Concept Mindmap")
        st.caption("How this idea links to others.")
        render_concept_graph(active["topic"], conns)
        st.markdown("</div>", unsafe_allow_html=True)

        # 3. Dynamic Challenge
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        st.markdown("### Practice Challenge")
        st.info(active["current_challenge"])
        
        with st.form("eval_form"):
            answer = st.text_area("Your Answer (Type the MCQ letter, or your reasoning):", height=100)
            sub = st.form_submit_button("Submit for Feedback", type="primary")
            
        if sub and answer.strip():
            with st.spinner("Evaluating..."):
                try:
                    client = get_client()
                    prompt = f"Evaluate the student's answer. Topic: {active['topic']}. Challenge: {active['current_challenge']}. Student Answer: {answer.strip()}"
                    resp = client.models.generate_content(
                        model=MODEL, contents=prompt,
                        config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=EvaluationResponse, temperature=0.3)
                    )
                    fb = json.loads(resp.text)
                    now_str = datetime.now().isoformat()
                    execute(
                        "INSERT INTO attempts (lesson_id, challenge, answer, understood, gap, improvement, teaching_explanation, next_challenge, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (active["id"], active["current_challenge"], answer.strip(), fb["understood"], fb["gap"], fb["improvement"], fb["teaching_explanation"], fb["next_challenge"], now_str)
                    )
                    execute("UPDATE lessons SET current_challenge = ?, last_reviewed_at = ? WHERE id = ?", (fb["next_challenge"], now_str, active["id"]))
                    st.success("Review recorded!")
                    st.rerun()
                except Exception as e:
                    st.error(friendly_ai_error(e))
        st.markdown("</div>", unsafe_allow_html=True)

        # History
        if attempts:
            st.markdown("### Review History")
            for i, att in enumerate(attempts):
                with st.expander(f"Attempt #{len(attempts)-i}: {att['challenge'][:50]}..."):
                    st.markdown(f"**Your Answer:** {att['answer']}\n\n✅ **Understood:** {att['understood']}\n\n⚠️ **Gap:** {att['gap']}\n\n📚 **Tutor Note:** {att['teaching_explanation']}")

# ----------------------------- Knowledge Network -----------------------------
elif st.session_state.page == "Knowledge Network":
    st.title("🌐 Knowledge Vault")
    st.write("A clean map of how all your learned topics connect.")
    lessons = query_all("SELECT * FROM lessons ORDER BY id DESC")
    
    if not lessons:
        st.info("No data yet.")
    else:
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        lines = ["graph LR"]
        for l in lessons:
            l_id = f"L_{l['id']}"
            lines.append(f'    {l_id}["📚 {safe_str(l["topic"])}"]:::lessonNode')
            for idx, c in enumerate(get_lesson_connections(l)):
                c_id = f"C_{l['id']}_{idx}"
                lines.append(f'    {c_id}["{safe_str(c.get("related_concept"))}"]:::subNode')
                lines.append(f'    {l_id} -.->|"{safe_str(c.get("relationship"))}"| {c_id}')
        
        lines.append("    classDef lessonNode fill:#e0e7ff,stroke:#4338ca,stroke-width:2px;")
        lines.append("    classDef subNode fill:#ffffff,stroke:#94a3b8;")
        
        mermaid_code = "\n".join(lines)
        html = f"""
        <div class="mermaid" style="display:flex; justify-content:center; padding:20px;">
            {mermaid_code}
        </div>
        <script type="module">
            import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
            mermaid.initialize({{ startOnLoad: true, theme: 'neutral' }});
        </script>
        """
        components.html(html, height=600, scrolling=True)
        st.markdown('</div>', unsafe_allow_html=True)

# ----------------------------- Progress -----------------------------
elif st.session_state.page == "Progress":
    st.title("📊 Progress & Revisions")
    lessons = query_all("SELECT * FROM lessons ORDER BY id DESC")
    
    # Activity Chart
    attempts = query_all("SELECT * FROM attempts ORDER BY id DESC")
    if attempts:
        counts = {}
        for att in attempts:
            d = att["created_at"][:10]
            counts[d] = counts.get(d, 0) + 1
        
        chart_data = {}
        today = datetime.now()
        for i in range(9, -1, -1):
            day_str = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            chart_data[day_str] = counts.get(day_str, 0)
        st.markdown("### 📈 Recent Activity")
        st.bar_chart(chart_data, color="#6366f1", height=200)

    # Spaced Repetition Due List
    st.markdown("### ⏰ Needs Review")
    due_found = False
    for l in lessons:
        cnt = query_one("SELECT COUNT(*) as n FROM attempts WHERE lesson_id = ?", (l["id"],))["n"]
        stt = get_repetition_status(l, cnt)
        if stt["is_due"]:
            due_found = True
            c1, c2 = st.columns([0.8, 0.2])
            c1.markdown(f"**{l['topic']}** (Interval: {stt['days_needed']} days)")
            if c2.button("Practice", key=f"rev_{l['id']}"): open_lesson(l['id'])
            st.divider()
    if not due_found:
        st.success("You are all caught up! No reviews due today.")