import json, os
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

APP_DIR = os.path.dirname(__file__)
DATA_PATH = os.path.join(APP_DIR, "data", "questions.json")
PROGRESS_PATH = os.path.join(APP_DIR, "data", "progress.json")

app = FastAPI(title="Salesforce Admin Trainer PRO")

app.mount("/static", StaticFiles(directory=os.path.join(APP_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(APP_DIR, "templates"))

def load_questions():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def load_progress():
    if os.path.exists(PROGRESS_PATH):
        with open(PROGRESS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"daily": {}, "by_category": {}, "history": []}

def save_progress(progress):
    with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=2)

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    questions = load_questions()
    progress = load_progress()
    total_answered = sum(d.get("answered",0) for d in progress.get("daily", {}).values())
    total_correct = sum(d.get("correct",0) for d in progress.get("daily", {}).values())
    accuracy = round(100*total_correct/max(total_answered,1))
    streak = compute_streak(progress.get("daily", {}))
    milestones = compute_milestones(total_answered, streak, accuracy)
    return templates.TemplateResponse("home.html", {
        "request": request,
        "total_questions": len(questions),
        "total_answered": total_answered,
        "accuracy": accuracy,
        "streak": streak,
        "milestones": milestones
    })

def compute_streak(daily_map):
    if not daily_map:
        return 0
    dates = sorted(daily_map.keys())
    # compute consecutive UTC days ending today
    today = datetime.utcnow().date()
    streak = 0
    day = today
    while True:
        key = day.strftime("%Y-%m-%d")
        if key in daily_map and daily_map[key].get("answered",0) > 0:
            streak += 1
            day = day - timedelta(days=1)
        else:
            break
    return streak

def compute_milestones(total_answered, streak, accuracy):
    milestones = []
    for t in [25, 50, 100, 150, 200, 300]:
        milestones.append({"label": f"{t} questions", "done": total_answered >= t})
    milestones.append({"label":"3-day streak", "done": streak >= 3})
    milestones.append({"label":"7-day streak", "done": streak >= 7})
    milestones.append({"label":"Accuracy 60%+", "done": accuracy >= 60})
    milestones.append({"label":"Accuracy 75%+", "done": accuracy >= 75})
    return milestones

@app.get("/quiz", response_class=HTMLResponse)
def quiz_get(request: Request):
    questions = load_questions()
    idx = int(request.query_params.get("q", "0"))
    if idx >= len(questions):
        return RedirectResponse(url="/results?total={}&correct={}".format(0, 0), status_code=302)
    question = questions[idx]
    return templates.TemplateResponse("quiz.html", {
        "request": request,
        "question": question,
        "index": idx,
        "question_number": idx + 1,
        "total_questions": len(questions)
    })

@app.post("/quiz", response_class=HTMLResponse)
def quiz_post(request: Request, index: int = Form(...), selected_option: int = Form(...)):
    questions = load_questions()
    total = len(questions)
    if index < 0 or index >= total:
        return RedirectResponse(url="/quiz", status_code=302)
    q = questions[index]
    correct_idx = q["answer_index"]
    is_correct = int(selected_option) == int(correct_idx)

    # Update progress with detailed tracking
    progress = load_progress()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if today not in progress["daily"]:
        progress["daily"][today] = {"answered":0, "correct":0}
    progress["daily"][today]["answered"] += 1
    if is_correct:
        progress["daily"][today]["correct"] += 1

    cat = q.get("category", "General")
    if cat not in progress["by_category"]:
        progress["by_category"][cat] = {"answered":0, "correct":0}
    progress["by_category"][cat]["answered"] += 1
    if is_correct:
        progress["by_category"][cat]["correct"] += 1

    progress["history"].append({
        "date": today, "category": cat, "correct": is_correct
    })
    save_progress(progress)

    feedback = "✅ Correct!" if is_correct else "❌ Incorrect."
    next_idx = index + 1
    if next_idx >= total:
        return RedirectResponse(url=f"/results?total={total}&correct=-1", status_code=302)

    return templates.TemplateResponse("feedback.html", {
        "request": request,
        "feedback": feedback,
        "correct_answer": q["options"][correct_idx],
        "explanation": q.get("explanation",""),
        "next_index": next_idx
    })

@app.get("/progress", response_class=HTMLResponse)
def progress_view(request: Request):
    progress = load_progress()
    daily = progress.get("daily", {})
    by_cat = progress.get("by_category", {})
    total_answered = sum(d.get("answered",0) for d in daily.values())
    total_correct = sum(d.get("correct",0) for d in daily.values())
    accuracy = round(100*total_correct/max(total_answered,1))
    streak = compute_streak(daily)
    milestones = compute_milestones(total_answered, streak, accuracy)

    # Prepare data for charts
    days_sorted = sorted(daily.keys())
    day_labels = days_sorted
    answered_series = [daily[d]["answered"] for d in days_sorted]
    correct_series = [daily[d]["correct"] for d in days_sorted]

    cat_labels = list(by_cat.keys())
    cat_answered = [by_cat[c]["answered"] for c in cat_labels]
    cat_correct = [by_cat[c]["correct"] for c in cat_labels]

    return templates.TemplateResponse("progress.html", {
        "request": request,
        "total_answered": total_answered,
        "total_correct": total_correct,
        "accuracy": accuracy,
        "streak": streak,
        "milestones": milestones,
        "day_labels": day_labels,
        "answered_series": answered_series,
        "correct_series": correct_series,
        "cat_labels": cat_labels,
        "cat_answered": cat_answered,
        "cat_correct": cat_correct
    })

@app.get("/download-progress")
def download_progress():
    if not os.path.exists(PROGRESS_PATH):
        with open(PROGRESS_PATH, "w") as f:
            f.write(json.dumps({"daily":{}, "by_category":{}, "history":[]}))
    return FileResponse(PROGRESS_PATH, filename="progress.json")
