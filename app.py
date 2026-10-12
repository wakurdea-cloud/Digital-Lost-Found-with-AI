from flask import Flask, render_template, request, redirect, flash, session, jsonify
from database import get_connection
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from PIL import Image
import imagehash
from difflib import SequenceMatcher
import os
import uuid
from werkzeug.security import generate_password_hash
from flask_mysqldb import MySQL

app = Flask(__name__)

PROFILE_UPLOAD_FOLDER = os.path.join("static", "uploads", "profiles")
os.makedirs(PROFILE_UPLOAD_FOLDER, exist_ok=True)

app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'system'   # तुझा MySQL password असेल तर इथे टाक
app.config['MYSQL_DB'] = 'lost_found_ai'  # तुझ्या database चे नाव

mysql = MySQL(app)
app.secret_key = "lostfound_secret_key"


# ---------------- HOME ----------------
@app.route("/")
def home():

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT
                r.id,
                r.rating,
                r.review_text,
                r.created_at,
                u.name,
                u.profile_photo,
                l.item_name,
                l.location,
                am.score
            FROM reviews r
            JOIN users u
                ON r.user_id = u.id
            JOIN ai_matches am
                ON r.match_id = am.id
            JOIN lost_items l
                ON am.lost_item_id = l.id
            WHERE am.claim_status = 'Approved'
            ORDER BY r.created_at DESC
            LIMIT 5
        """)

        reviews = cursor.fetchall()

    except Exception as e:
        print("HOME REVIEWS ERROR:", e)
        reviews = []

    finally:
        cursor.close()
        conn.close()

    return render_template(
        "index.html",
        reviews=reviews
    )

# ---------------- LOGIN ----------------

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":
        

        email = request.form["email"]
        password = request.form["password"]

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            "SELECT * FROM users WHERE email=%s",
            (email,)
        )

        user = cursor.fetchone()

        conn.close()

        if user and check_password_hash(user["password"], password):

            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            session["user_email"] = user["email"]

            return redirect("/dashboard")

        else:
            flash("Invalid Email or Password")

    return render_template("login.html")


# ---------------- SIGNUP ----------------

@app.route("/signup", methods=["GET", "POST"])
def signup():

    if request.method == "POST":

        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]

        hashed_password = generate_password_hash(password)

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT * FROM users WHERE email=%s",
            (email,)
        )

        user = cursor.fetchone()

        if user:
            flash("Email already registered!")
            conn.close()
            return redirect("/signup")

        cursor.execute(
            "INSERT INTO users(name,email,password) VALUES(%s,%s,%s)",
            (name, email, hashed_password)
        )

        conn.commit()
        conn.close()

        flash("Account Created Successfully!")
        return redirect("/login")

    return render_template("signup.html")


# ---------------- LOGOUT ----------------

@app.route("/logout")
def logout():

    session.clear()
    return redirect("/")


# ---------------- PROFILE ----------------

@app.route("/profile")
def profile():

    if "user_id" not in session:
        return redirect("/login")

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    user_id = session["user_id"]

    # ================= USER DETAILS =================

    cursor.execute("""
        SELECT id, name, email, phone, created_at, profile_photo
        FROM users
        WHERE id = %s
    """, (user_id,))

    user = cursor.fetchone()

    if not user:
        cursor.close()
        conn.close()
        flash("User profile not found!", "error")
        return redirect("/dashboard")


    # ================= LOST REPORTS =================

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM lost_items
        WHERE user_id = %s
        AND is_deleted = 0
    """, (user_id,))

    lost_count = cursor.fetchone()["total"]


    # ================= FOUND REPORTS =================

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM found_items
        WHERE user_id = %s
        AND is_deleted = 0
    """, (user_id,))

    found_count = cursor.fetchone()["total"]


    # ================= AI MATCHES =================

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM ai_matches am

        JOIN lost_items l
            ON am.lost_item_id = l.id

        JOIN found_items f
            ON am.found_item_id = f.id

        WHERE
            (l.user_id = %s OR f.user_id = %s)
            AND am.is_deleted = 0
            AND l.is_deleted = 0
            AND f.is_deleted = 0
    """, (user_id, user_id))

    match_count = cursor.fetchone()["total"]


    cursor.close()
    conn.close()


    # ================= SEND DATA TO HTML =================

    return render_template(
        "profile.html",
        username=user["name"],
        email=user["email"],
        phone=user["phone"],
        created_at=user["created_at"],
        profile_photo=user["profile_photo"],
        lost_count=lost_count,
        found_count=found_count,
        match_count=match_count
    )


@app.route("/edit-profile", methods=["GET", "POST"])
def edit_profile():

    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:

        # -----------------------------------------
        # GET CURRENT USER DATA
        # -----------------------------------------

        cursor.execute(
            """
            SELECT name, email, phone, profile_photo
            FROM users
            WHERE id = %s
            """,
            (user_id,)
        )

        user = cursor.fetchone()

        if not user:
            return redirect("/login")


        # -----------------------------------------
        # POST
        # -----------------------------------------

        if request.method == "POST":
            print("EDIT PROFILE POST RECEIVED")
            print("FILES:", request.files)

            username = request.form.get("username", "").strip()
            email = request.form.get("email", "").strip()
            phone = request.form.get("phone", "").strip()

            if not username or not email:
                flash("Name and email are required.", "error")
                return redirect("/edit-profile")


            old_photo = user.get("profile_photo")
            new_photo = request.files.get("profile_photo")
            print("PROFILE PHOTO RECEIVED:", new_photo)

            new_photo_path = old_photo


            # -----------------------------------------
            # PROFILE PHOTO
            # -----------------------------------------

            if new_photo and new_photo.filename:

                # Allowed extensions
                allowed_extensions = {
                    "jpg",
                    "jpeg",
                    "png",
                    "webp"
                }

                original_name = new_photo.filename.lower()

                extension = original_name.rsplit(".", 1)[-1]

                if extension not in allowed_extensions:

                    flash(
                        "Please upload JPG, PNG or WebP image.",
                        "error"
                    )

                    return redirect("/edit-profile")


                # -------------------------------------
                # UNIQUE FILE NAME
                # -------------------------------------

                filename = f"user_{user_id}_{uuid.uuid4().hex}.webp"

                filepath = os.path.join(
                    PROFILE_UPLOAD_FOLDER,
                    filename
                )


                # -------------------------------------
                # OPEN + RESIZE + COMPRESS
                # -------------------------------------

                try:

                    image = Image.open(new_photo)

                    # Convert transparent images safely
                    if image.mode in ("RGBA", "LA"):
                        background = Image.new(
                            "RGB",
                            image.size,
                            "white"
                        )

                        background.paste(
                            image,
                            mask=image.getchannel("A")
                        )

                        image = background

                    else:
                        image = image.convert("RGB")


                    # Maximum profile photo size
                    image.thumbnail(
                        (600, 600),
                        Image.Resampling.LANCZOS
                    )


                    # Save optimized WebP
                    image.save(
                        filepath,
                        "WEBP",
                        quality=85,
                        optimize=True
                    )


                except Exception as image_error:

                    print(
                        "PROFILE IMAGE ERROR:",
                        image_error
                    )

                    flash(
                        "Unable to process profile photo.",
                        "error"
                    )

                    return redirect("/edit-profile")


                # -------------------------------------
                # DATABASE PATH
                # -------------------------------------

                new_photo_path = (
                    f"uploads/profiles/{filename}"
                )


            # -----------------------------------------
            # UPDATE DATABASE
            # -----------------------------------------

            cursor.execute(
                """
                UPDATE users
                SET
                    name = %s,
                    email = %s,
                    phone = %s,
                    profile_photo = %s
                WHERE id = %s
                """,
                (
                    username,
                    email,
                    phone if phone else None,
                    new_photo_path,
                    user_id
                )
            )

            conn.commit()


            # -----------------------------------------
            # DELETE OLD PHOTO ONLY AFTER SUCCESS
            # -----------------------------------------

            if (
                new_photo_path != old_photo
                and old_photo
            ):

                old_file = os.path.join(
                    "static",
                    old_photo
                )

                if os.path.exists(old_file):

                    try:
                        os.remove(old_file)

                    except Exception as delete_error:

                        print(
                            "OLD PHOTO DELETE ERROR:",
                            delete_error
                        )


            # -----------------------------------------
            # UPDATE SESSION
            # -----------------------------------------

            session["user_name"] = username
            session["user_email"] = email


            flash(
                "Profile updated successfully!",
                "success"
            )

            return redirect("/profile")


        # -----------------------------------------
        # GET PAGE
        # -----------------------------------------

        return render_template(
            "edit_profile.html",
            username=user["name"],
            email=user["email"],
            phone=user["phone"] or "",
            profile_photo=user["profile_photo"]
        )

    except Exception as e:

        conn.rollback()

        print(
            "EDIT PROFILE ERROR:",
            e
        )

        flash(
            "Unable to update profile.",
            "error"
        )

        return redirect("/edit-profile")

    finally:

        cursor.close()
        conn.close()






@app.route("/dashboard")
def dashboard():

    if "user_id" not in session:
        return redirect("/login")

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    # Lost Count
    cursor.execute(
        """
        SELECT COUNT(*) AS total
        FROM lost_items
        WHERE user_id=%s
        AND is_deleted=0
        """,
    (session["user_id"],)
    )
    lost_count = cursor.fetchone()["total"]

    # Found Count
    
    cursor.execute(
      """
      SELECT COUNT(*) AS total
      FROM found_items
      WHERE user_id=%s
      AND is_deleted=0
      """,
    (session["user_id"],)
     )
    found_count = cursor.fetchone()["total"]

    # Pending Claim Requests
    cursor.execute("""
        SELECT
            am.id,
            l.item_name,
            l.image,
            am.score,
            am.claim_status

        FROM ai_matches am

        JOIN found_items f
            ON am.found_item_id=f.id

        JOIN lost_items l
            ON am.lost_item_id=l.id

           WHERE f.user_id=%s
           AND am.is_deleted=0
           AND l.is_deleted=0
           AND f.is_deleted=0
           AND am.claim_status='Claim Requested'
           AND am.finder_status='Pending'
           """, (session["user_id"],))

    claim_requests = cursor.fetchall()

    # Match Count
    cursor.execute("""
        SELECT COUNT(*) AS total

        FROM ai_matches am

        JOIN lost_items l
            ON am.lost_item_id=l.id

        JOIN found_items f
            ON am.found_item_id=f.id

       WHERE am.is_deleted=0
       AND l.is_deleted=0
       AND f.is_deleted=0
       AND (
       l.user_id=%s
       OR f.user_id=%s
       )
       """, (session["user_id"], session["user_id"]))

    match_count = cursor.fetchone()["total"]

    # Accuracy
    cursor.execute("""
        SELECT AVG(score) AS accuracy

        FROM ai_matches am

        JOIN lost_items l
            ON am.lost_item_id=l.id

        JOIN found_items f
            ON am.found_item_id=f.id

       WHERE am.is_deleted=0
      AND l.is_deleted=0
      AND f.is_deleted=0
      AND (
          l.user_id=%s
          OR f.user_id=%s
      )
    """, (session["user_id"], session["user_id"]))

    result = cursor.fetchone()
    accuracy = round(result["accuracy"] or 0)
    
    # AI Notifications
    cursor.execute("""
        SELECT
            am.id,
            am.score,
            am.status,
            am.claim_status,
            am.finder_status,

            l.user_id AS lost_user,
            f.user_id AS found_user,

            l.item_name AS lost_item,
            f.item_name AS found_item

        FROM ai_matches am

        JOIN lost_items l
            ON am.lost_item_id = l.id

        JOIN found_items f
            ON am.found_item_id = f.id

        WHERE am.is_deleted=0
        AND l.is_deleted=0
        AND f.is_deleted=0
        AND
        (
            l.user_id=%s
        AND (
             am.claim_status='Not Claimed'
        OR (
        am.finder_status='Approved'
        AND am.lost_notification_read='No'
           )
        OR (
        am.finder_status='Rejected'
        AND am.lost_notification_read='No'
           )
        )
        )
        OR
        (
            f.user_id=%s
            AND am.claim_status='Claim Requested'
            AND am.finder_status='Pending'
            AND am.found_notification_read='No'
        )

        ORDER BY am.id DESC
    """, (session["user_id"], session["user_id"]))

    notifications = cursor.fetchall()
    
    
        # ================= AI ANALYTICS =================

    # Total reports
    total_reports = lost_count + found_count

    # Successful / approved claims
    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM ai_matches am
        JOIN lost_items l
            ON am.lost_item_id = l.id
        JOIN found_items f
            ON am.found_item_id = f.id
        WHERE am.is_deleted=0
        AND l.is_deleted=0
        AND f.is_deleted=0
        AND am.finder_status='Approved'
        AND (
            l.user_id=%s
            OR f.user_id=%s
        )
    """, (session["user_id"], session["user_id"]))

    recovered_count = cursor.fetchone()["total"]


    # Pending matches
    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM ai_matches am
        JOIN lost_items l
            ON am.lost_item_id=l.id
        JOIN found_items f
            ON am.found_item_id=f.id
        WHERE am.is_deleted=0
        AND l.is_deleted=0
        AND f.is_deleted=0
        AND am.finder_status='Pending'
        AND (
            l.user_id=%s
            OR f.user_id=%s
        )
    """, (session["user_id"], session["user_id"]))

    pending_matches = cursor.fetchone()["total"]


    # High confidence matches
    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM ai_matches am
        JOIN lost_items l
            ON am.lost_item_id=l.id
        JOIN found_items f
            ON am.found_item_id=f.id
        WHERE am.is_deleted=0
        AND l.is_deleted=0
        AND f.is_deleted=0
        AND am.score >= 80
        AND (
            l.user_id=%s
            OR f.user_id=%s
        )
    """, (session["user_id"], session["user_id"]))

    high_confidence = cursor.fetchone()["total"]


    # Recovery rate
    if match_count > 0:
        recovery_rate = round(
            (recovered_count / match_count) * 100
        )
    else:
        recovery_rate = 0


    # User contribution points
    contribution_points = (
        (found_count * 20) +
        (lost_count * 5) +
        (recovered_count * 50)
    )


    # Contribution level
    if contribution_points >= 500:
        contribution_level = "Community Hero"
    elif contribution_points >= 250:
        contribution_level = "Top Contributor"
    elif contribution_points >= 100:
        contribution_level = "Active Member"
    else:
        contribution_level = "New Member"

    # Recent Reports
    cursor.execute("""
        SELECT
            item_name,
            location,
            lost_date AS report_date,
            image,
            'Lost' AS type

        FROM lost_items

         WHERE user_id=%s
           AND is_deleted=0

        UNION ALL

        SELECT
            item_name,
            location,
            found_date AS report_date,
            image,
            'Found' AS type

        FROM found_items

       WHERE user_id=%s
         AND is_deleted=0

        ORDER BY report_date DESC

        LIMIT 5
    """, (session["user_id"], session["user_id"]))

    recent_reports = cursor.fetchall()

    conn.close()

    return render_template(
        "dashboard.html",
        username=session["user_name"],
        user_id=session["user_id"],
        lost_count=lost_count,
        found_count=found_count,
        match_count=match_count,
        accuracy=accuracy,
        claim_requests=claim_requests,
        notifications=notifications,
        recent_reports=recent_reports,
        total_reports=total_reports,
        recovered_count=recovered_count,
        pending_matches=pending_matches,
        high_confidence=high_confidence,
        recovery_rate=recovery_rate,
        contribution_points=contribution_points,
        contribution_level=contribution_level
    )
    
# ---------------- AI MATCH CREATOR ----------------
# ---------------- ADVANCED AI MATCH ENGINE ----------------

def normalize_text(value):
    if value is None:
        return ""

    return " ".join(str(value).strip().lower().split())


def text_similarity(text1, text2):
    text1 = normalize_text(text1)
    text2 = normalize_text(text2)

    if not text1 or not text2:
        return 0

    if text1 == text2:
        return 100

    return int(SequenceMatcher(None, text1, text2).ratio() * 100)


def location_similarity(location1, location2):
    location1 = normalize_text(location1)
    location2 = normalize_text(location2)

    if not location1 or not location2:
        return 0

    if location1 == location2:
        return 100

    if location1 in location2 or location2 in location1:
        return 90

    return text_similarity(location1, location2)


def compare_dates(date1, date2):
    if not date1 or not date2:
        return 0

    try:
        d1 = str(date1)[:10]
        d2 = str(date2)[:10]

        return 100 if d1 == d2 else 0

    except Exception:
        return 0


def image_similarity(image1, image2):
    """
    Compare two images using perceptual hashing.
    Same/similar images can match even when filenames are different.
    """

    if not image1 or not image2:
        return 0

    path1 = os.path.join("static", "uploads", str(image1))
    path2 = os.path.join("static", "uploads", str(image2))

    if not os.path.exists(path1):
        return 0

    if not os.path.exists(path2):
        return 0

    try:
        img1 = Image.open(path1).convert("RGB")
        img2 = Image.open(path2).convert("RGB")

        hash1 = imagehash.phash(img1)
        hash2 = imagehash.phash(img2)

        distance = hash1 - hash2

        # Perceptual hash distance
        if distance <= 2:
            return 100

        elif distance <= 5:
            return 90

        elif distance <= 8:
            return 80

        elif distance <= 12:
            return 65

        elif distance <= 16:
            return 50

        else:
            return 0

    except Exception as e:
        print("IMAGE MATCH ERROR:", e)
        return 0


def create_ai_matches():

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:

        # -------------------------------------------------
        # GET ACTIVE LOST ITEMS
        # -------------------------------------------------

        cursor.execute("""
            SELECT
                id,
                user_id,
                item_name,
                description,
                lost_date,
                location,
                image
            FROM lost_items
            WHERE is_deleted = 0
        """)

        lost_items = cursor.fetchall()


        # -------------------------------------------------
        # GET ACTIVE FOUND ITEMS
        # -------------------------------------------------

        cursor.execute("""
            SELECT
                id,
                user_id,
                item_name,
                description,
                found_date,
                location,
                image
            FROM found_items
            WHERE is_deleted = 0
        """)

        found_items = cursor.fetchall()


        # -------------------------------------------------
        # COMPARE LOST VS FOUND
        # -------------------------------------------------

        for lost in lost_items:

            for found in found_items:

                # Same user चे items compare करू नयेत
                if lost["user_id"] == found["user_id"]:
                    continue


                # =================================================
                # 1. IMAGE MATCH
                # =================================================

                image_score = 0

                if lost.get("image") and found.get("image"):

                    image_similarity_score = image_similarity(
                        lost["image"],
                        found["image"]
                    )

                    image_score = int(
                        image_similarity_score * 0.50
                    )


                # =================================================
                # 2. ITEM NAME MATCH
                # =================================================

                name_similarity_score = text_similarity(
                    lost.get("item_name"),
                    found.get("item_name")
                )

                name_score = int(
                    name_similarity_score * 0.20
                )


                # =================================================
                # 3. LOCATION MATCH
                # =================================================

                location_similarity_score = location_similarity(
                    lost.get("location"),
                    found.get("location")
                )

                location_score = int(
                    location_similarity_score * 0.30
                )


                # =================================================
                # 4. DATE MATCH
                # =================================================

                date_similarity_score = compare_dates(
                    lost.get("lost_date"),
                    found.get("found_date")
                )

                date_score = int(
                    date_similarity_score * 0.10
                )


                # =================================================
                # 5. DESCRIPTION MATCH
                # =================================================

                description_similarity_score = text_similarity(
                    lost.get("description"),
                    found.get("description")
                )

                description_score = int(
                    description_similarity_score * 0.05
                )


                # =================================================
                # FINAL SCORE
                # =================================================

                final_score = (
                    image_score
                    + name_score
                    + location_score
                    + date_score
                    + description_score
                )

                final_score = min(100, final_score)


                # =================================================
                # DIFFERENT THRESHOLD
                # =================================================

                has_image = (
                    bool(lost.get("image"))
                    and bool(found.get("image"))
                )


                if has_image:

                    # Image available
                    # Stronger condition to avoid false matches

                    match_required_score = 55

                else:

                    # No image
                    # Features वरून match

                    match_required_score = 45


                # =================================================
                # CREATE MATCH
                # =================================================

                if final_score >= match_required_score:

                    cursor.execute("""
                        SELECT id
                        FROM ai_matches
                        WHERE lost_item_id = %s
                        AND found_item_id = %s
                        AND is_deleted = 0
                    """, (
                        lost["id"],
                        found["id"]
                    ))

                    existing = cursor.fetchone()


                    if not existing:

                        cursor.execute("""
                            INSERT INTO ai_matches
                            (
                                lost_item_id,
                                found_item_id,
                                score
                            )
                            VALUES (%s, %s, %s)
                        """, (
                            lost["id"],
                            found["id"],
                            final_score
                        ))

                        print(
                            f"AI MATCH CREATED | "
                            f"Lost ID: {lost['id']} | "
                            f"Found ID: {found['id']} | "
                            f"Score: {final_score}"
                        )


        conn.commit()

    except Exception as e:

        conn.rollback()

        print("AI MATCH ENGINE ERROR:", e)

    finally:

        cursor.close()
        conn.close()
# ---------------- REPORT LOST ----------------
@app.route("/report-lost", methods=["GET", "POST"])
def report_lost():

    if "user_id" not in session:
        return redirect("/login")

    if request.method == "POST":

        image = request.files.get("image")
        item_name = request.form["item_name"]
        location = request.form["location"]
        lost_date = request.form["lost_date"]
        description = request.form.get("description", "").strip()

        filename = None

        # If image is uploaded, save it
        if image and image.filename:
            filename = secure_filename(image.filename)

            upload_folder = os.path.join("static", "uploads")
            os.makedirs(upload_folder, exist_ok=True)

            image.save(os.path.join(upload_folder, filename))

        # If image is NOT uploaded, description is mandatory
        if not image or not image.filename:
            if not description:
                flash(
                    "Description is required when image is not uploaded.",
                    "error"
                )
                return redirect(request.path)

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO lost_items
            (user_id, item_name, description, lost_date, location, image)
            VALUES(%s,%s,%s,%s,%s,%s)
        """, (
            session["user_id"],
            item_name,
            description,
            lost_date,
            location,
            filename
        ))

        conn.commit()

        # AI Match Generate
        create_ai_matches()

        conn.close()

        flash("Lost Item Report Submitted Successfully!")

        return redirect("/dashboard")

    return render_template("report_lost.html")


# ---------------- REPORT FOUND ----------------
# ---------------- REPORT FOUND ----------------

@app.route("/report-found", methods=["GET", "POST"])
def report_found():

    if "user_id" not in session:
        return redirect("/login")

    if request.method == "POST":

        image = request.files.get("image")
        item_name = request.form["item_name"]
        location = request.form["location"]
        found_date = request.form["found_date"]
        description = request.form.get("description", "").strip()

        filename = None

        # If image is uploaded, save it
        if image and image.filename:
            filename = secure_filename(image.filename)

            upload_folder = os.path.join("static", "uploads")
            os.makedirs(upload_folder, exist_ok=True)

            image.save(os.path.join(upload_folder, filename))

        # If image is NOT uploaded, description is mandatory
        if not image or not image.filename:
            if not description:
                flash(
                    "Description is required when image is not uploaded.",
                    "error"
                )
                return redirect(request.path)

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO found_items
            (user_id, item_name, description, found_date, location, image)
            VALUES(%s,%s,%s,%s,%s,%s)
        """, (
            session["user_id"],
            item_name,
            description,
            found_date,
            location,
            filename
        ))

        conn.commit()

        # Generate AI Matches
        create_ai_matches()

        conn.close()

        flash("Found Item Report Submitted Successfully!")

        return redirect("/dashboard")

    return render_template("report_found.html")
# ---------------- MATCHES ----------------

@app.route("/matches")
def matches():

    if "user_id" not in session:
        return redirect("/login")

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            am.id AS match_id,
            am.score,
            am.status,
            am.claim_status,
            am.finder_status,

            l.item_name AS lost_item,
            l.image AS lost_image,
            l.location,

            f.item_name AS found_item,
            f.image AS found_image

        FROM ai_matches am

        JOIN lost_items l
            ON am.lost_item_id = l.id

        JOIN found_items f
            ON am.found_item_id = f.id

        WHERE
            am.is_deleted = 0
            AND l.is_deleted = 0
            AND f.is_deleted = 0
            AND (
                l.user_id = %s
                OR f.user_id = %s
            )

        ORDER BY am.id DESC
    """, (
        session["user_id"],
        session["user_id"]
    ))

    matches = cursor.fetchall()

    conn.close()

    return render_template(
        "matches.html",
        matches=matches,
        total_matches=len(matches),
        high_matches=len([
            m for m in matches
            if m["score"] >= 80
        ]),
        pending=len([
            m for m in matches
            if m["claim_status"] == "Not Claimed"
        ])
    )
    
    
    
@app.route("/submit-review/<int:match_id>", methods=["POST"])
def submit_review(match_id):

    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]

    rating = request.form.get("rating")
    review_text = request.form.get("review_text", "").strip()

    if not rating or not review_text:
        flash("Please provide rating and review.", "error")
        return redirect(f"/match-details/{match_id}")

    try:
        rating = int(rating)
    except ValueError:
        flash("Invalid rating.", "error")
        return redirect(f"/match-details/{match_id}")

    if rating < 1 or rating > 5:
        flash("Rating must be between 1 and 5.", "error")
        return redirect(f"/match-details/{match_id}")

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:

        # Check whether user is part of this match
        cursor.execute("""
            SELECT
                am.id,
                am.claim_status,
                l.user_id AS lost_user,
                f.user_id AS found_user
            FROM ai_matches am
            JOIN lost_items l
                ON am.lost_item_id = l.id
            JOIN found_items f
                ON am.found_item_id = f.id
            WHERE am.id = %s
        """, (match_id,))

        match = cursor.fetchone()

        if not match:
            flash("Match not found.", "error")
            return redirect("/matches")

        # Only Lost User or Found User can review
        if user_id not in (match["lost_user"], match["found_user"]):
            flash("You are not authorized to review this match.", "error")
            return redirect(f"/match-details/{match_id}")

        # Review only after approval
        if match["claim_status"] != "Approved":
            flash("Review is available after the match is approved.", "error")
            return redirect(f"/match-details/{match_id}")

        # Prevent duplicate review
        cursor.execute("""
            SELECT id
            FROM reviews
            WHERE user_id = %s
              AND match_id = %s
        """, (user_id, match_id))

        existing_review = cursor.fetchone()

        if existing_review:
            flash("You have already submitted a review for this match.", "error")
            return redirect(f"/match-details/{match_id}")

        # Save review
        cursor.execute("""
            INSERT INTO reviews
            (user_id, match_id, rating, review_text)
            VALUES (%s, %s, %s, %s)
        """, (
            user_id,
            match_id,
            rating,
            review_text
        ))

        conn.commit()

        flash("Thank you! Your review has been submitted.", "success")

    except Exception as e:

        conn.rollback()
        print("SUBMIT REVIEW ERROR:", e)

        flash("Unable to submit review.", "error")

    finally:

        cursor.close()
        conn.close()

    return redirect(f"/match-details/{match_id}")

# ---------------- MATCH DETAILS ----------------
@app.route("/match-details/<int:match_id>")
def match_details(match_id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            am.id,
            am.score,
            am.status,
            am.claim_status,
            am.finder_status,
            am.lost_notification_read,
            am.found_notification_read,

            l.user_id AS lost_user,
            l.item_name AS lost_item,
            l.image AS lost_image,
            l.location AS lost_location,
            l.lost_date,
            l.description AS lost_description,

            f.user_id AS found_user,
            f.id AS found_id,
            f.item_name AS found_item,
            f.image AS found_image,
            f.location AS found_location,
            f.found_date,
            f.description AS found_description

        FROM ai_matches am

        JOIN lost_items l
            ON am.lost_item_id = l.id

        JOIN found_items f
            ON am.found_item_id = f.id

        WHERE am.id=%s
    """, (match_id,))

    match = cursor.fetchone()

    if not match:
        conn.close()
        flash("Match not found.")
        return redirect("/matches")

    # ==============================
    # AI ANALYSIS SCORES
    # ==============================

    # Item Name Match
    item_score = 0

    if (
        match["lost_item"]
        and match["found_item"]
        and match["lost_item"].strip().lower()
        == match["found_item"].strip().lower()
    ):
        item_score = 40


        # Location Match
    location_score = 0

    if match["lost_location"] and match["found_location"]:

        lost_location = match["lost_location"].strip().lower()
        found_location = match["found_location"].strip().lower()

        if lost_location == found_location:
            location_score = 30

        elif (
            lost_location in found_location
            or found_location in lost_location
        ):
            location_score = 25

        else:
            similarity = SequenceMatcher(
                None,
                lost_location,
                found_location
            ).ratio()

            if similarity >= 0.85:
                location_score = 25

            elif similarity >= 0.70:
                location_score = 20
    # Description Match
    description_score = 0

    if (
        match["lost_description"]
        and match["found_description"]
        and match["lost_description"].strip().lower()
        == match["found_description"].strip().lower()
    ):
        description_score = 15


    # Date Match
    date_score = 0

    if (
        match["lost_date"]
        and match["found_date"]
        and str(match["lost_date"])[:10]
        == str(match["found_date"])[:10]
    ):
        date_score = 15


    # Add scores to match
    match["item_score"] = item_score
    match["location_score"] = location_score
    match["description_score"] = description_score
    match["date_score"] = date_score


    # ==============================
    # MARK NOTIFICATION AS READ
    # ==============================

    if match["lost_user"] == session["user_id"]:

        cursor.execute("""
            UPDATE ai_matches
            SET lost_notification_read='Yes'
            WHERE id=%s
        """, (match_id,))

    elif match["found_user"] == session["user_id"]:

        cursor.execute("""
            UPDATE ai_matches
            SET found_notification_read='Yes'
            WHERE id=%s
        """, (match_id,))


    conn.commit()
    conn.close()

    return render_template(
        "match_details.html",
        match=match
    )
# ---------------- CLAIM ITEM ----------------

@app.route("/claim-item/<int:match_id>")
def claim_item(match_id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE ai_matches
        SET claim_status='Claim Requested'
        WHERE id=%s
    """, (match_id,))

    conn.commit()
    conn.close()

    flash("Your claim request has been submitted successfully!")

    return redirect("/matches")

# ---------------- ACCEPT CLAIM ----------------
@app.route("/accept-claim/<int:match_id>")
def accept_claim(match_id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_connection()
    cursor = conn.cursor()

    # Claim approve करा
    cursor.execute("""
        UPDATE ai_matches
        SET
            finder_status = 'Approved',
            claim_status = 'Approved',
            status = 'Claim Approved',
            lost_notification_read = 'No'
        WHERE id = %s
    """, (match_id,))

    conn.commit()
    cursor.close()
    conn.close()

    flash("Claim Approved Successfully!", "success")

    return redirect("/dashboard")

# ---------------- REJECT CLAIM ----------------

@app.route("/reject-claim/<int:match_id>")
def reject_claim(match_id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE ai_matches
        SET
            finder_status='Rejected',
            claim_status='Rejected',
            status='Rejected'
        WHERE id=%s
    """, (match_id,))

    conn.commit()
    conn.close()

    flash("Claim Rejected!")

    return redirect("/dashboard")

# ---------------- MY REPORTS ----------------

@app.route("/my-reports")
def my_reports():

    if "user_id" not in session:
        return redirect("/login")

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            id,
            item_name,
            image,
            location,
            lost_date AS report_date,
            'Lost' AS type

        FROM lost_items

        WHERE user_id=%s
        AND is_deleted=0

        UNION ALL

        SELECT
            id,
            item_name,
            image,
            location,
            found_date AS report_date,
            'Found' AS type

        FROM found_items

        WHERE user_id=%s
        AND is_deleted=0

        ORDER BY report_date DESC
    """, (session["user_id"], session["user_id"]))

    reports = cursor.fetchall()

    conn.close()

    return render_template(
        "my_reports.html",
        reports=reports
    )
@app.route("/delete-report/<int:id>")
def delete_report(id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:

        # Check whether this report belongs to current user
        cursor.execute("""
            SELECT id
            FROM lost_items
            WHERE id=%s AND user_id=%s AND is_deleted=0
        """, (id, session["user_id"]))

        lost_item = cursor.fetchone()

        if lost_item:

            # Soft delete AI matches
            cursor.execute("""
                UPDATE ai_matches
                SET is_deleted=1
                WHERE lost_item_id=%s
            """, (id,))

            # Soft delete normal matches
            cursor.execute("""
                UPDATE matches
                SET is_deleted=1
                WHERE lost_item_id=%s
            """, (id,))

            # Soft delete lost report
            cursor.execute("""
                UPDATE lost_items
                SET is_deleted=1
                WHERE id=%s AND user_id=%s
            """, (id, session["user_id"]))

        else:

            # Check found report
            cursor.execute("""
                SELECT id
                FROM found_items
                WHERE id=%s AND user_id=%s AND is_deleted=0
            """, (id, session["user_id"]))

            found_item = cursor.fetchone()

            if not found_item:
                flash("Report not found.", "error")
                return redirect("/my-reports")

            # Soft delete AI matches
            cursor.execute("""
                UPDATE ai_matches
                SET is_deleted=1
                WHERE found_item_id=%s
            """, (id,))

            # Soft delete normal matches
            cursor.execute("""
                UPDATE matches
                SET is_deleted=1
                WHERE found_item_id=%s
            """, (id,))

            # Soft delete found report
            cursor.execute("""
                UPDATE found_items
                SET is_deleted=1
                WHERE id=%s AND user_id=%s
            """, (id, session["user_id"]))

        conn.commit()

        flash("Report deleted successfully!", "success")

    except Exception as e:

        conn.rollback()

        print("DELETE REPORT ERROR:", e)

        flash("Unable to delete report.", "error")

    finally:

        cursor.close()
        conn.close()

    return redirect("/my-reports")


@app.route("/change-password", methods=["GET", "POST"])
def change_password():

    if "user_id" not in session:
        return redirect("/login")

    if request.method == "POST":

        current_password = request.form["current_password"]
        new_password = request.form["new_password"]
        confirm_password = request.form["confirm_password"]

        if new_password != confirm_password:
            flash("New passwords do not match.", "error")
            return redirect("/change-password")

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            "SELECT * FROM users WHERE id=%s",
            (session["user_id"],)
        )

        user = cursor.fetchone()

        if not check_password_hash(user["password"], current_password):
            flash("Current password is incorrect.", "error")
            conn.close()
            return redirect("/change-password")

        hashed_password = generate_password_hash(new_password)

        cursor.execute(
            "UPDATE users SET password=%s WHERE id=%s",
            (hashed_password, session["user_id"])
        )

        conn.commit()
        conn.close()

        flash("Password changed successfully.", "success")

        return redirect("/profile")

    return render_template("change_password.html")


# ---------------- DELETE ACCOUNT ----------------
# ---------------- DELETE ACCOUNT ----------------

@app.route("/delete-account", methods=["POST"])
def delete_account():

    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]

    conn = get_connection()
    cursor = conn.cursor()

    try:

        # Get user's lost item IDs
        cursor.execute(
            "SELECT id FROM lost_items WHERE user_id = %s",
            (user_id,)
        )
        lost_ids = [row[0] for row in cursor.fetchall()]

        # Get user's found item IDs
        cursor.execute(
            "SELECT id FROM found_items WHERE user_id = %s",
            (user_id,)
        )
        found_ids = [row[0] for row in cursor.fetchall()]

        # Delete messages related to user's AI matches
        for item_id in lost_ids:
            cursor.execute("""
                DELETE m
                FROM messages m
                JOIN ai_matches am
                    ON m.match_id = am.id
                WHERE am.lost_item_id = %s
            """, (item_id,))

        for item_id in found_ids:
            cursor.execute("""
                DELETE m
                FROM messages m
                JOIN ai_matches am
                    ON m.match_id = am.id
                WHERE am.found_item_id = %s
            """, (item_id,))

        # Delete AI matches
        for item_id in lost_ids:
            cursor.execute(
                "DELETE FROM ai_matches WHERE lost_item_id = %s",
                (item_id,)
            )

        for item_id in found_ids:
            cursor.execute(
                "DELETE FROM ai_matches WHERE found_item_id = %s",
                (item_id,)
            )

        # Delete normal matches
        for item_id in lost_ids:
            cursor.execute(
                "DELETE FROM matches WHERE lost_item_id = %s",
                (item_id,)
            )

        for item_id in found_ids:
            cursor.execute(
                "DELETE FROM matches WHERE found_item_id = %s",
                (item_id,)
            )

        # Delete user's lost reports
        cursor.execute(
            "DELETE FROM lost_items WHERE user_id = %s",
            (user_id,)
        )

        # Delete user's found reports
        cursor.execute(
            "DELETE FROM found_items WHERE user_id = %s",
            (user_id,)
        )

        # Delete user account
        cursor.execute(
            "DELETE FROM users WHERE id = %s",
            (user_id,)
        )

        conn.commit()

        session.clear()

        flash("Your account has been deleted successfully.", "success")

        return redirect("/login")

    except Exception as e:

        conn.rollback()

        print("DELETE ACCOUNT ERROR:", e)

        flash("Unable to delete account.", "error")

        return redirect("/profile")

    finally:

        cursor.close()
        conn.close()

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():

    if request.method == "POST":

        email = request.form["email"]
        new_password = request.form["new_password"]
        confirm_password = request.form["confirm_password"]

        if new_password != confirm_password:
            flash("Passwords do not match.", "error")
            return redirect("/forgot-password")

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            "SELECT * FROM users WHERE email=%s",
            (email,)
        )

        user = cursor.fetchone()

        if not user:
            flash("Email not found.", "error")
            conn.close()
            return redirect("/forgot-password")

        hashed = generate_password_hash(new_password)

        cursor.execute(
            "UPDATE users SET password=%s WHERE email=%s",
            (hashed, email)
        )

        conn.commit()
        conn.close()

        flash("Password reset successfully. Please login.", "success")

        return redirect("/login")

    return render_template("forgot_password.html")

# ================= SECURE CHAT =================

@app.route("/chat/<int:match_id>", methods=["GET", "POST"])
def secure_chat(match_id):

    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    # Check approved match
    cursor.execute("""
        SELECT
            am.id,
            am.lost_item_id,
            am.found_item_id,
            am.finder_status,

            li.user_id AS lost_user,
            li.item_name AS lost_item,

            fi.user_id AS found_user,
            fi.item_name AS found_item

        FROM ai_matches am

        JOIN lost_items li
            ON am.lost_item_id = li.id

        JOIN found_items fi
            ON am.found_item_id = fi.id

        WHERE am.id = %s
    """, (match_id,))

    match = cursor.fetchone()

    if not match:
        cursor.close()
        conn.close()

        flash("Match not found.")
        return redirect("/dashboard")

    # Only approved matches can use chat
    if match["finder_status"] != "Approved":

        cursor.close()
        conn.close()

        flash("Chat is available only after the claim is approved.")
        return redirect("/dashboard")

    # Only lost user OR found user can access chat
    if user_id not in [match["lost_user"], match["found_user"]]:

        cursor.close()
        conn.close()

        flash("Unauthorized access.")
        return redirect("/dashboard")

    # Determine receiver
    if user_id == match["lost_user"]:
        receiver_id = match["found_user"]
    else:
        receiver_id = match["lost_user"]

    # Send message
    if request.method == "POST":

        message = request.form.get("message", "").strip()

        if message:

            cursor.execute("""
                INSERT INTO messages
                (match_id, sender_id, receiver_id, message)
                VALUES (%s, %s, %s, %s)
            """, (
                match_id,
                user_id,
                receiver_id,
                message
            ))

            conn.commit()

    # Get chat messages
    cursor.execute("""
        SELECT
            m.id,
            m.sender_id,
            m.receiver_id,
            m.message,
            m.created_at,
            m.is_read,
            u.name
        FROM messages m

        JOIN users u
            ON m.sender_id = u.id

        WHERE m.match_id = %s

        ORDER BY m.created_at ASC
    """, (match_id,))

    messages = cursor.fetchall()

    # Mark received messages as read
    cursor.execute("""
        UPDATE messages
        SET is_read = 'Yes'
        WHERE match_id = %s
        AND receiver_id = %s
    """, (match_id, user_id))

    conn.commit()

    cursor.close()
    conn.close()

    return render_template(
        "chat.html",
        match=match,
        messages=messages,
        user_id=user_id
    )
    
@app.route("/send-message/<int:match_id>", methods=["POST"])
def send_message(match_id):

    if "user_id" not in session:
        return redirect("/login")

    sender_id = session["user_id"]
    message = request.form.get("message", "").strip()

    if not message:
        flash("Message cannot be empty.")
        return redirect(f"/chat/{match_id}")

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    # Check approved match
    cursor.execute("""
        SELECT
            finder_status,
            l.user_id AS lost_user,
            f.user_id AS found_user
        FROM ai_matches am
        JOIN lost_items l ON am.lost_item_id = l.id
        JOIN found_items f ON am.found_item_id = f.id
        WHERE am.id = %s
    """, (match_id,))

    match = cursor.fetchone()

    if not match:
        cursor.close()
        conn.close()
        flash("Match not found.")
        return redirect("/matches")

    if match["finder_status"] != "Approved":
        cursor.close()
        conn.close()
        flash("Chat is not available.")
        return redirect("/matches")

    # Determine receiver
    if sender_id == match["lost_user"]:
        receiver_id = match["found_user"]

    elif sender_id == match["found_user"]:
        receiver_id = match["lost_user"]

    else:
        cursor.close()
        conn.close()
        flash("Unauthorized access.")
        return redirect("/dashboard")

    cursor.execute("""
        INSERT INTO messages
        (match_id, sender_id, receiver_id, message)
        VALUES (%s, %s, %s, %s)
    """, (
        match_id,
        sender_id,
        receiver_id,
        message
    ))

    conn.commit()

    cursor.close()
    conn.close()

    return redirect(f"/chat/{match_id}")

# ================= NOTIFICATIONS =================

@app.route("/notifications")
def notifications_page():

    if "user_id" not in session:
        return redirect("/login")

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            am.id,
            am.score,
            am.status,
            am.claim_status,
            am.finder_status,

            l.item_name AS lost_item,
            f.item_name AS found_item,

            l.user_id AS lost_user,
            f.user_id AS found_user

        FROM ai_matches am

        JOIN lost_items l
            ON am.lost_item_id = l.id

        JOIN found_items f
            ON am.found_item_id = f.id

        WHERE am.is_deleted = 0
          AND l.is_deleted = 0
          AND f.is_deleted = 0
          AND (
                (
                    l.user_id = %s
                    AND (
                        am.claim_status = 'Not Claimed'
                        OR (
                            am.finder_status = 'Approved'
                            AND am.lost_notification_read = 'No'
                        )
                        OR (
                            am.finder_status = 'Rejected'
                            AND am.lost_notification_read = 'No'
                        )
                    )
                )

                OR

                (
                    f.user_id = %s
                    AND am.claim_status = 'Claim Requested'
                    AND am.finder_status = 'Pending'
                    AND am.found_notification_read = 'No'
                )
          )

        ORDER BY am.id DESC
    """, (
        session["user_id"],
        session["user_id"]
    ))

    notifications = cursor.fetchall()

    conn.close()

    return render_template(
        "notifications.html",
        notifications=notifications,
        username=session.get("user_name", "User")
    )
    
@app.route("/my-reports-search")
def my_reports_search():

    if "user_id" not in session:
        return jsonify([])

    query = request.args.get("q", "").strip()

    if not query:
        return jsonify([])

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    search = f"%{query}%"
    user_id = session["user_id"]
    cursor.execute("""
    SELECT
        id,
        item_name,
        location,
        lost_date AS report_date,
        image,
        'Lost' AS type
    FROM lost_items
    WHERE user_id = %s
      AND is_deleted = 0
      AND (
          item_name LIKE %s
          OR location LIKE %s
          OR description LIKE %s
      )

    UNION ALL

    SELECT
        id,
        item_name,
        location,
        found_date AS report_date,
        image,
        'Found' AS type
         FROM found_items
         WHERE user_id = %s
         AND is_deleted = 0
         AND (
          item_name LIKE %s
          OR location LIKE %s
          OR description LIKE %s
      )

    ORDER BY report_date DESC
     """, (
    user_id, search, search, search,
    user_id, search, search, search
    ))
    results = cursor.fetchall()

    cursor.close()
    conn.close()

    return jsonify(results)
# ---------------- RUN APP ----------------
if __name__ == "__main__":
    app.run(debug=False, use_reloader=False)