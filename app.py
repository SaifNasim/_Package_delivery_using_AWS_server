import os
from datetime import datetime, date
from flask import Flask, render_template, request, redirect, url_for, jsonify, abort
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session
from datetime import timedelta
# ---------------- Setup ----------------
load_dotenv()

POSTGRES_HOST = os.getenv("POSTGRES_HOST")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", 5432)
POSTGRES_DB = os.getenv("POSTGRES_DB")
POSTGRES_USER = os.getenv("POSTGRES_USER")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")

if not all([POSTGRES_HOST, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD]):
    raise ValueError("? Postgres credentials missing in .env file!")

# Create PostgreSQL connection
conn = psycopg2.connect(
    host=POSTGRES_HOST,
    port=POSTGRES_PORT,
    dbname=POSTGRES_DB,
    user=POSTGRES_USER,
    password=POSTGRES_PASSWORD
)

# Helper: run queries
def run_query(query, params=None, fetch=False):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, params or ())
        if fetch:
            return cur.fetchall()
        conn.commit()
        return None

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

# Fixed login credentials
MANAGER_ID = "admin"
MANAGER_PASSWORD = "1234"

# Temporary in-memory storage for deliveryman accounts
delivery_accounts = [("saif23", "1234")]  # default account


app.secret_key = "your_secret_key"  # needed for sessions
app.permanent_session_lifetime = timedelta(minutes=10)

# ---------------- Pricing Helper ----------------
def compute_price(package_type: str, quantity: int, weight_kg: float, duration_days: int, fragile: bool) -> float:
    base_by_type = {"Standard": 100.0, "Express": 200.0, "Premium": 300.0}
    base = base_by_type.get(package_type, 100.0)

    weight_fee = 20.0 * max(weight_kg, 0.0)
    fragile_factor = 1.15 if fragile else 1.0
    extra_days = max(duration_days - 1, 0)
    duration_factor = 1.0 + (0.03 * extra_days)

    per_unit = (base + weight_fee) * fragile_factor * duration_factor
    total = per_unit * max(quantity, 1)

    if duration_days >= 5:
        total *= 0.9  # 10% discount

    return round(total, 2)

# ---------------- Front Page ----------------
@app.route("/")
def home():
    return render_template("home.html")

# ---------------- Customer ----------------
@app.route("/customer", methods=["GET"])
def customer_dashboard():
    return render_template("customer_dashboard.html")

@app.route("/customer/price", methods=["POST"])
def customer_price_preview():
    try:
        data = request.json or {}
        package_type = data.get("package_type", "Standard")
        quantity = int(data.get("quantity", 1))
        weight_kg = float(data.get("weight_kg", 0))
        duration_days = int(data.get("duration_days", 1))
        fragile = bool(data.get("fragile", False))
        price = compute_price(package_type, quantity, weight_kg, duration_days, fragile)
        return jsonify({"ok": True, "price": price})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

@app.route("/customer/place_order", methods=["POST"])
def place_order():
    customer_name = request.form.get("customer_name", "").strip()
    customer_email = request.form.get("customer_email", "").strip()
    customer_phone = request.form.get("customer_phone", "").strip()
    delivery_address = request.form.get("delivery_address", "").strip()

    package_type = request.form.get("package_type", "Standard")
    quantity = int(request.form.get("quantity", "1"))
    duration_days = int(request.form.get("duration_days", 1))
    weight_kg = float(request.form.get("weight_kg", 0.0))
    length_cm = float(request.form.get("length_cm", 0.0))
    width_cm = float(request.form.get("width_cm", 0.0))
    height_cm = float(request.form.get("height_cm", 0.0))
    fragile = (request.form.get("fragile") == "on")
    preferred_pickup_date = request.form.get("preferred_pickup_date")
    notes = request.form.get("notes", "").strip()

    if not all([customer_name, customer_email, customer_phone, delivery_address]):
        return "? Missing required customer/contact/addresses.", 400

    total_price = compute_price(package_type, quantity, weight_kg, duration_days, fragile)

    order_data = {
        "customer_name": customer_name,
        "customer_email": customer_email,
        "customer_phone": customer_phone,
        "delivery_address": delivery_address,
        "package_type": package_type,
        "quantity": quantity,
        "duration_days": duration_days,
        "weight_kg": weight_kg,
        "length_cm": length_cm,
        "width_cm": width_cm,
        "height_cm": height_cm,
        "fragile": fragile,
        "preferred_pickup_date": preferred_pickup_date if preferred_pickup_date else None,
        "notes": notes if notes else None,
        "total_price": total_price,
        "status": "pending",
        "created_at": datetime.now().isoformat()
    }

    try:
        run_query("""
            INSERT INTO orders (customer_name, customer_email, customer_phone, delivery_address,
                package_type, quantity, duration_days, weight_kg, length_cm, width_cm, height_cm,
                fragile, preferred_pickup_date, notes, total_price, status, created_at)
            VALUES (%(customer_name)s, %(customer_email)s, %(customer_phone)s, %(delivery_address)s,
                %(package_type)s, %(quantity)s, %(duration_days)s, %(weight_kg)s, %(length_cm)s,
                %(width_cm)s, %(height_cm)s, %(fragile)s, %(preferred_pickup_date)s, %(notes)s,
                %(total_price)s, %(status)s, %(created_at)s)
        """, order_data)
        return render_template("order_success.html", order=order_data)
    except Exception as e:
        return f"? Exception saving order: {e}", 500

@app.route('/customer/check_order_status_page')
def check_order_status_page():
    return render_template("check_order_status_page.html")

@app.route('/customer/check_order_status', methods=['POST'])
def check_order_status():
    order_id = request.form.get("order_id")
    error = None
    result = None

    if not order_id:
        error = "? Please provide an order ID."
    else:
        rows = run_query("SELECT * FROM orders WHERE id=%s", (order_id,), fetch=True)
        if rows:
            result = rows[0]
        else:
            error = f"? Order {order_id} not found."

    return render_template("check_order_status_page.html", result=result, error=error)

# ---------------- Manager ----------------

@app.route("/manager_login", methods=["GET", "POST"])
def manager_login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if username == MANAGER_ID and password == MANAGER_PASSWORD:
            session["manager_logged_in"] = True
            return redirect(url_for("manager_dashboard"))
        else:
            return render_template("manager_login.html", error="Invalid credentials")

    return render_template("manager_login.html")


@app.route("/manager", methods=["GET"])
def manager_dashboard():
    if not session.get("manager_logged_in"):  # check login first
        return redirect(url_for("manager_login"))

    rows = run_query("SELECT id FROM orders WHERE status='pending'", fetch=True)
    pending_count = len(rows or [])
    return render_template("manager_dashboard.html", pending_count=pending_count)

@app.route("/manager/orders", methods=["GET"])
def manager_orders():
    rows = run_query("SELECT * FROM orders WHERE status='pending' ORDER BY created_at DESC", fetch=True)
    return render_template("manager_orders.html", orders=rows)

@app.route("/manager/pending_count", methods=["GET"])
def manager_pending_count():
    rows = run_query("SELECT id FROM orders WHERE status='pending'", fetch=True)
    return jsonify({"pending": len(rows or [])})

@app.route("/manager/order_action", methods=["POST"])
def order_action():
    order_id = request.form.get("order_id")
    action = request.form.get("action")
    if not order_id or action not in {"accept", "reject"}:
        abort(400, "Invalid request")
    new_status = "accepted" if action == "accept" else "denied"
    try:
        run_query("UPDATE orders SET status=%s WHERE id=%s", (new_status, order_id))
    except Exception as e:
        return f"? Failed to update order: {e}", 500
    return redirect(url_for("manager_orders"))

@app.route("/manager/history", methods=["GET"])
def manager_history():
    rows = run_query(
        "SELECT * FROM orders WHERE status IN ('accepted','denied') ORDER BY created_at DESC",
        fetch=True
    )
    return render_template("manager_history.html", orders=rows)

# ---------------- DELIVERY MAN DASHBOARD ----------------


# Deliveryman signup
@app.route("/delivery/signup", methods=["GET", "POST"])
def delivery_signup():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        # check if username already exists
        if any(acc[0] == username for acc in delivery_accounts):
            return "Account already exists! Try logging in."

        # append new account
        delivery_accounts.append((username, password))
        return redirect(url_for("delivery_login"))

    return render_template("delivery_signup.html")


# Deliveryman login
@app.route("/delivery/login", methods=["GET", "POST"])
def delivery_login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        if (username, password) in delivery_accounts:
            session["deliveryman_id"] = username   # use consistent key
            return redirect(url_for("deliveryman_dashboard"))
        else:
            return "Invalid credentials. Try again."

    return render_template("delivery_login.html")


@app.route('/deliveryman')
def deliveryman_dashboard():
    if "deliveryman_id" not in session:   # consistent key
        return redirect(url_for("delivery_login"))

    rows = run_query(
        "SELECT * FROM orders WHERE status='accepted' AND delivery_status IS NULL",
        fetch=True
    )
    return render_template("deliveryman_dashboard.html", orders=rows or [])





@app.route('/deliveryman/accept_order/<int:order_id>', methods=["POST"])
def dm_accept_order(order_id):
    deliveryman_id = request.form.get("deliveryman_id", "").strip()
    if not deliveryman_id:
        return "? Deliveryman ID is required.", 400

    run_query(
        "UPDATE orders SET deliveryman_id=%s, delivery_status='delivery pending' WHERE id=%s",
        (deliveryman_id, order_id)
    )

    return redirect(url_for("deliveryman_dashboard"))

# ---------------- DELIVERY COMPLETION PAGE ----------------
@app.route('/deliveryman/complete_order_page')
def dm_complete_order_page():
    return render_template("dm_complete_order.html")

@app.route('/dm/complete_order', methods=['GET', 'POST'])
def dm_complete_order():
    error = None
    success = None

    if request.method == 'POST':
        deliveryman_id = request.form.get('deliveryman_id')
        order_id = request.form.get('order_id')

        rows = run_query("SELECT * FROM orders WHERE id=%s", (order_id,), fetch=True)
        order = rows[0] if rows else None

        if not order:
            error = "? Order not found."
        elif order.get("deliveryman_id") != deliveryman_id:
            error = "? You are not assigned to this order."
        else:
            run_query(
                "UPDATE orders SET delivery_status='completed', delivery_completed_at=%s WHERE id=%s",
                (datetime.now().isoformat(), order_id)
            )
            success = f"?? You have completed the delivery! Order ID: {order_id}, Reward: $20"

    return render_template("dm_complete_order.html", error=error, success=success)

# ---------------- Run ----------------
if __name__ == "__main__":
    app.run(debug=True)
