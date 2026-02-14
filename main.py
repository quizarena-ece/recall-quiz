import os
import json
import uuid
import sqlite3
import qrcode
import google.generativeai as genai

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

# ================= CONFIG =================
load_dotenv()
API_KEY = os.getenv("API_KEY")
genai.configure(api_key=API_KEY)

model = genai.GenerativeModel("gemini-2.5-flash")

DATABASE = "quiz.db"

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ================= DATABASE =================

def get_db():
    return sqlite3.connect(DATABASE, check_same_thread=False)

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS quizzes (
        id TEXT PRIMARY KEY,
        topic TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        quiz_id TEXT,
        question TEXT,
        option1 TEXT,
        option2 TEXT,
        option3 TEXT,
        option4 TEXT,
        answer TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        quiz_id TEXT,
        roll_number TEXT,
        score INTEGER
    )
    """)

    conn.commit()
    conn.close()

init_db()

# ================= HOME =================

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index2.html", {"request": request})

# ================= GENERATE QUIZ =================

@app.post("/generate")
def generate_quiz(request: Request, topic: str = Form(...)):

    quiz_id = str(uuid.uuid4())[:8]

    prompt = f"""
Generate 5 multiple choice questions about {topic}.

Return strictly in this JSON format:

[
  {{
    "question": "...",
    "option1": "...",
    "option2": "...",
    "option3": "...",
    "option4": "...",
    "answer": "..."
  }}
]

NO markdown.
NO explanation.
ONLY JSON.
"""

    response = model.generate_content(prompt)
    raw = response.text.strip()

    # remove markdown blocks if AI adds them
    if raw.startswith("```"):
        raw = raw.split("```")[1]

    try:
        questions = json.loads(raw)
    except:
        return {"error": "AI JSON format issue"}

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("INSERT INTO quizzes VALUES (?, ?)", (quiz_id, topic))

    for q in questions:
        cursor.execute("""
        INSERT INTO questions
        (quiz_id, question, option1, option2, option3, option4, answer)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            quiz_id,
            q["question"],
            q["option1"],
            q["option2"],
            q["option3"],
            q["option4"],
            q["answer"]
        ))

    conn.commit()
    conn.close()

    # ===== QR GENERATE =====
    if not os.path.exists("static/qrcodes"):
        os.makedirs("static/qrcodes")

    quiz_url = f"https://recall-quiz.onrender.com/quiz/{quiz_id}"
    img = qrcode.make(quiz_url)
    img.save(f"static/qrcodes/{quiz_id}.png")

    return templates.TemplateResponse("teacher.html", {
        "request": request,
        "quiz_id": quiz_id,
        "qr_path": f"/static/qrcodes/{quiz_id}.png"
    })

# ================= QUIZ PAGE =================

@app.get("/quiz/{quiz_id}", response_class=HTMLResponse)
def quiz_page(request: Request, quiz_id: str):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM questions WHERE quiz_id=?", (quiz_id,))
    questions = cursor.fetchall()

    conn.close()

    return templates.TemplateResponse("quiz.html", {
        "request": request,
        "questions": questions,
        "quiz_id": quiz_id
    })

# ================= SUBMIT =================

@app.post("/submit/{quiz_id}")
async def submit_quiz(request: Request, quiz_id: str, roll_number: str = Form(...)):

    form = await request.form()

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM questions WHERE quiz_id=?", (quiz_id,))
    questions = cursor.fetchall()

    score = 0

    for q in questions:
        selected = form.get(str(q[0]))
        if selected == q[6]:
            score += 1

    cursor.execute("""
    INSERT INTO attempts (quiz_id, roll_number, score)
    VALUES (?, ?, ?)
    """, (quiz_id, roll_number, score))

    conn.commit()
    conn.close()

    return templates.TemplateResponse("result.html", {
        "request": request,
        "score": score,
        "total": len(questions)
    })

# ================= TEACHER RESULTS =================

@app.get("/teacher_results/{quiz_id}", response_class=HTMLResponse)
def teacher_results(request: Request, quiz_id: str):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT roll_number, score FROM attempts
    WHERE quiz_id=?
    """, (quiz_id,))

    results = cursor.fetchall()
    conn.close()

    return templates.TemplateResponse("teacher_results.html", {
        "request": request,
        "results": results

    })
