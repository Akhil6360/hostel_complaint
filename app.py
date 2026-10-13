
import sqlite3
from functools import wraps

from flask import (
    Flask, render_template, request,
    redirect, url_for, session
)
from werkzeug.security import (
    generate_password_hash, check_password_hash
)

app = Flask(__name__)
app.secret_key = "change-this-to-a-random-secret"

DATABASE = "hostelpulse.db"


# Database connection
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


# Create users table
def init_users_table():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            student_id TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            room TEXT NOT NULL,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'student'
        )
    """)
    conn.commit()
    conn.close()


# Create complaints table
def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student TEXT NOT NULL,
            room TEXT,
            category TEXT,
            description TEXT,
            priority TEXT,
            status TEXT DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


init_users_table()
init_db()


# Predict complaint priority using keywords
def predict_priority(category, description):
    text = (category + " " + description).lower()

    high_words = [
        "fire", "smoke", "electric shock", "sparking",
        "gas leak", "emergency", "injury", "unsafe",
        "flood", "water leak", "exposed wire"
    ]

    medium_words = [
        "water", "electricity", "power", "wifi",
        "internet", "fan", "light", "door", "lock",
        "bathroom", "toilet", "leak", "broken"
    ]

    if any(word in text for word in high_words):
        return "High"

    if any(word in text for word in medium_words):
        return "Medium"

    return "Low"


# Login protection
def login_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        return function(*args, **kwargs)
    return wrapper


# Home page
@app.route("/")
def home():
    if "username" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


# Student registration
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        student_id = request.form.get("student_id", "").strip()
        email = request.form.get("email", "").strip().lower()
        room = request.form.get("room", "").strip()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not all([
            full_name, student_id, email,
            room, username, password
        ]):
            return render_template(
                "register.html",
                error="Please fill in all fields."
            )

        if username.lower() in ("admin", "student"):
            return render_template(
                "register.html",
                error="Please choose a different username."
            )

        if len(password) < 8:
            return render_template(
                "register.html",
                error="Password must contain at least 8 characters."
            )

        password_hash = generate_password_hash(password)
        conn = get_db()

        try:
            conn.execute("""
                INSERT INTO users
                (full_name, student_id, email, room,
                 username, password_hash, role)
                VALUES (?, ?, ?, ?, ?, ?, 'student')
            """, (
                full_name, student_id, email, room,
                username, password_hash
            ))
            conn.commit()

        except sqlite3.IntegrityError:
            return render_template(
                "register.html",
                error="Student ID, email, or username is already registered."
            )
        finally:
            conn.close()

        return redirect(url_for("login"))

    return render_template("register.html")


# Login
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,)
        ).fetchone()
        conn.close()

        if user and check_password_hash(
            user["password_hash"], password
        ):
            session.clear()
            session["username"] = user["username"]
            session["role"] = user["role"]
            session["full_name"] = user["full_name"]
            return redirect(url_for("dashboard"))

        # Demo accounts
        if username == "admin" and password == "admin123":
            session.clear()
            session["username"] = "admin"
            session["role"] = "admin"
            session["full_name"] = "Administrator"
            return redirect(url_for("dashboard"))

        if username == "student" and password == "student123":
            session.clear()
            session["username"] = "student"
            session["role"] = "student"
            session["full_name"] = "Demo Student"
            return redirect(url_for("dashboard"))

        return render_template(
            "login.html",
            error="Invalid username or password."
        )

    return render_template("login.html")


# Dashboard
@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_db()

    # Admin sees all complaints; students see their own
    if session.get("role") == "admin":
        rows = conn.execute(
            "SELECT * FROM complaints ORDER BY id DESC"
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT * FROM complaints
               WHERE student = ?
               ORDER BY id DESC""",
            (session.get("full_name", ""),)
        ).fetchall()

    profile = conn.execute(
        """SELECT full_name, student_id, email, room
           FROM users WHERE username = ?""",
        (session["username"],)
    ).fetchone()

    conn.close()

    complaints = [dict(row) for row in rows]
    profile = dict(profile) if profile else None

    total = len(complaints)
    pending = sum(c["status"] == "Pending" for c in complaints)
    progress = sum(c["status"] == "In Progress" for c in complaints)
    resolved = sum(c["status"] == "Resolved" for c in complaints)

    return render_template(
        "index.html",
        username=session["username"],
        profile=profile,
        complaints=complaints,
        total=total,
        pending=pending,
        progress=progress,
        resolved=resolved
    )


# Complaint form
@app.route("/complaint")
@login_required
def complaint():
    return render_template("complaint.html")


# Submit complaint
@app.route("/submit-complaint", methods=["POST"])
@login_required
def submit_complaint():
    category = request.form.get("category", "").strip()
    description = request.form.get("description", "").strip()

    if not category or not description:
        return "Please provide a category and description.", 400

    # Use registered student details instead of trusting form input
    if session.get("role") == "student":
        conn = get_db()
        user = conn.execute(
            "SELECT full_name, room FROM users WHERE username = ?",
            (session["username"],)
        ).fetchone()
        conn.close()

        if user:
            student = user["full_name"]
            room = user["room"]
        elif session["username"] == "student":
            student = "Demo Student"
            room = request.form.get("room", "").strip()
        else:
            return "Student profile not found. Please log in again.", 400

    elif session.get("role") == "admin":
        student = request.form.get("student", "").strip()
        room = request.form.get("room", "").strip()

        if not student:
            student = "Administrator"
    else:
        return "Invalid user role.", 403

    priority = predict_priority(category, description)

    conn = get_db()
    conn.execute("""
        INSERT INTO complaints
        (student, room, category, description, priority, status)
        VALUES (?, ?, ?, ?, ?, 'Pending')
    """, (student, room, category, description, priority))
    conn.commit()
    conn.close()

    return render_template("success.html", student=student)


# Admin status update
@app.route("/update-status/<int:complaint_id>", methods=["POST"])
@login_required
def update_status(complaint_id):
    if session.get("role") != "admin":
        return "Only the admin can update complaint status.", 403

    new_status = request.form.get("status", "")

    if new_status not in ["Pending", "In Progress", "Resolved"]:
        return "Invalid complaint status.", 400

    conn = get_db()
    conn.execute(
        "UPDATE complaints SET status = ? WHERE id = ?",
        (new_status, complaint_id)
    )
    conn.commit()
    conn.close()

    return redirect(url_for("dashboard"))


# Logout
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True)
