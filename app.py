import os
import bcrypt
import mysql.connector
from flask import Flask, render_template, request, redirect, url_for, session, flash
from functools import wraps
from mysql.connector import Error

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'a_default_secure_key')  # Use env variable for security

# MySQL connection config
def get_db_connection():
    try:
        return mysql.connector.connect(
            host='l', #use your own localhost sql server name
            user='', #use your own user name of sql
            password='', #hey there,use your mysql password here
            database='' #use your database name
        )
    except Error as e:
        print(f"Error connecting to MySQL: {e}")
        return None

# Decorator to require login
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in first.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('profile'))
    return render_template('welcome.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')

        if not all([username, email, password]):
            flash('Please fill in all fields.', 'danger')
            return redirect(url_for('register'))

        db = get_db_connection()
        if not db:
            flash('Database connection failed.', 'danger')
            return redirect(url_for('register'))

        try:
            cursor = db.cursor(dictionary=True)
            cursor.execute("SELECT * FROM users WHERE username=%s OR email=%s", (username, email))
            existing_user = cursor.fetchone()

            if existing_user:
                flash('Username or email already exists.', 'warning')
                return redirect(url_for('register'))

            # Hash password and convert to string for VARCHAR column
            hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            cursor.execute(
                "INSERT INTO users (username, email, password) VALUES (%s, %s, %s)",
                (username, email, hashed_password)
            )
            db.commit()
            flash('Registered successfully! Please log in.', 'success')
            return redirect(url_for('login'))
        except Error as e:
            flash(f'Registration failed: {e}', 'danger')
        finally:
            cursor.close()
            db.close()

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        db = get_db_connection()
        if not db:
            flash('Database connection failed.', 'danger')
            return render_template('login.html')

        try:
            cursor = db.cursor(dictionary=True)
            cursor.execute("SELECT * FROM users WHERE email=%s", (email,))
            user = cursor.fetchone()

            # Encode stored password string to bytes for bcrypt
            if user and bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
                session['user_id'] = user['id']
                session['user_name'] = user['username']
                flash('Logged in successfully!', 'success')
                return redirect(url_for('profile'))
            else:
                flash('Invalid email or password.', 'danger')
        except Error as e:
            flash(f'Login failed: {e}', 'danger')
        finally:
            cursor.close()
            db.close()

    return render_template('login.html')

@app.route('/logout', methods=['POST'])
@login_required
def logout():
    session.clear()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('login'))

@app.route('/profile')
@login_required
def profile():
    db = get_db_connection()
    if not db:
        flash('Database connection failed.', 'danger')
        return redirect(url_for('home'))

    try:
        cursor = db.cursor(dictionary=True)
        cursor.force_binary = False
        cursor.execute(
            "SELECT id, title FROM stories WHERE user_id=%s ORDER BY created_at DESC LIMIT 5",
            (session['user_id'],)
        )
        recent_stories = cursor.fetchall()

        cursor.execute(
            """
            SELECT s.id, s.title FROM stories s
            JOIN bookmarks b ON s.id = b.story_id
            WHERE b.user_id = %s
            ORDER BY b.created_at DESC LIMIT 5
            """,
            (session['user_id'],)
        )
        bookmarked_stories = cursor.fetchall()
    except Error as e:
        flash(f'Error fetching profile data: {e}', 'danger')
        recent_stories = []
        bookmarked_stories = []
    finally:
        cursor.close()
        db.close()

    return render_template(
        'profile.html',
        recent_stories=recent_stories,
        bookmarked_stories=bookmarked_stories
    )

@app.route('/post_story', methods=['GET', 'POST'])
@login_required
def post_story():
    if request.method == 'POST':
        title = request.form.get('title')
        genre = request.form.get('genre')
        content = request.form.get('content')
        user_id = session['user_id']

        if not all([title, genre, content]):
            flash('Please fill in all fields.', 'danger')
            return redirect(url_for('post_story'))

        db = get_db_connection()
        if not db:
            flash('Database connection failed.', 'danger')
            return redirect(url_for('post_story'))

        try:
            cursor = db.cursor()
            cursor.execute(
                "INSERT INTO stories (user_id, title, genre, content) VALUES (%s, %s, %s, %s)",
                (user_id, title, genre, content)
            )
            db.commit()
            flash('Story posted successfully!', 'success')
            return redirect(url_for('profile'))
        except Error as e:
            flash(f'Error posting story: {e}', 'danger')
        finally:
            cursor.close()
            db.close()

    return render_template('post_story.html')

@app.route('/read_stories')
@login_required
def read_stories():
    genre = request.args.get('genre')
    db = get_db_connection()
    if not db:
        flash('Database connection failed.', 'danger')
        return render_template('read_stories.html', stories=[], genres=[])

    try:
        cursor = db.cursor(dictionary=True)
        # Fetch distinct genres
        cursor.execute("SELECT DISTINCT genre FROM stories")
        genres = [row['genre'] for row in cursor.fetchall()]

        # Fetch stories with comment and like counts
        query = """
            SELECT s.*, u.username, 
                   COUNT(c.id) AS comment_count, 
                   (SELECT COUNT(*) FROM likes l WHERE l.story_id = s.id) AS like_count
            FROM stories s
            JOIN users u ON s.user_id = u.id
            LEFT JOIN comments c ON s.id = c.story_id
            %s
            GROUP BY s.id
            ORDER BY s.created_at DESC
        """
        params = ()
        if genre:
            query = query % "WHERE s.genre = %s"
            params = (genre,)
        else:
            query = query % ""

        cursor.execute(query, params)
        stories = cursor.fetchall()

        # Fetch comments for each story
        for story in stories:
            cursor.execute(
                """
                SELECT c.comment, u.username 
                FROM comments c
                JOIN users u ON c.user_id = u.id
                WHERE c.story_id = %s
                ORDER BY c.created_at ASC
                """,
                (story['id'],)
            )
            story['comments'] = cursor.fetchall()
    except Error as e:
        flash(f'Error fetching stories: {e}', 'danger')
        stories = []
        genres = []
    finally:
        cursor.close()
        db.close()

    return render_template(
        'read_stories.html',
        stories=stories,
        genres=genres,
        selected_genre=genre
    )

@app.route('/story/<int:story_id>')
@login_required
def view_story(story_id):
    db = get_db_connection()
    if not db:
        flash('Database connection failed.', 'danger')
        return redirect(url_for('read_stories'))

    try:
        cursor = db.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT s.*, u.username 
            FROM stories s
            JOIN users u ON s.user_id = u.id
            WHERE s.id = %s
            """,
            (story_id,)
        )
        story = cursor.fetchone()

        if not story:
            flash('Story not found.', 'warning')
            return redirect(url_for('read_stories'))

        cursor.execute(
            """
            SELECT c.comment, u.username 
            FROM comments c
            JOIN users u ON c.user_id = u.id
            WHERE c.story_id = %s
            ORDER BY c.created_at ASC
            """,
            (story_id,)
        )
        comments = cursor.fetchall()

        cursor.execute(
            "SELECT COUNT(*) AS like_count FROM likes WHERE story_id = %s",
            (story_id,)
        )
        like_count = cursor.fetchone()['like_count']

        cursor.execute(
            "SELECT * FROM likes WHERE story_id = %s AND user_id = %s",
            (story_id, session['user_id'])
        )
        liked = cursor.fetchone() is not None

        cursor.execute(
            "SELECT * FROM bookmarks WHERE story_id = %s AND user_id = %s",
            (story_id, session['user_id'])
        )
        bookmarked = cursor.fetchone() is not None
    except Error as e:
        flash(f'Error fetching story: {e}', 'danger')
        return redirect(url_for('read_stories'))
    finally:
        cursor.close()
        db.close()

    return render_template(
        'view_story.html',
        story=story,
        comments=comments,
        like_count=like_count,
        liked=liked,
        bookmarked=bookmarked
    )

@app.route('/like/<int:story_id>', methods=['POST'])
@login_required
def like_story(story_id):
    user_id = session['user_id']
    db = get_db_connection()
    if not db:
        return ('', 500)

    try:
        cursor = db.cursor()
        cursor.execute(
            "SELECT * FROM likes WHERE user_id = %s AND story_id = %s",
            (user_id, story_id)
        )
        if cursor.fetchone():
            cursor.execute(
                "DELETE FROM likes WHERE user_id = %s AND story_id = %s",
                (user_id, story_id)
            )
        else:
            cursor.execute(
                "INSERT INTO likes (user_id, story_id) VALUES (%s, %s)",
                (user_id, story_id)
            )
        db.commit()
    except Error:
        db.rollback()
        return ('', 500)
    finally:
        cursor.close()
        db.close()

    return ('', 204)

@app.route('/bookmark/<int:story_id>', methods=['POST'])
@login_required
def bookmark_story(story_id):
    user_id = session['user_id']
    db = get_db_connection()
    if not db:
        return ('', 500)

    try:
        cursor = db.cursor()
        cursor.execute(
            "SELECT * FROM bookmarks WHERE user_id = %s AND story_id = %s",
            (user_id, story_id)
        )
        if cursor.fetchone():
            cursor.execute(
                "DELETE FROM bookmarks WHERE user_id = %s AND story_id = %s",
                (user_id, story_id)
            )
        else:
            cursor.execute(
                "INSERT INTO bookmarks (user_id, story_id) VALUES (%s, %s)",
                (user_id, story_id)
            )
        db.commit()
    except Error:
        db.rollback()
        return ('', 500)
    finally:
        cursor.close()
        db.close()

    return ('', 204)

@app.route('/comment/<int:story_id>', methods=['POST'])
@login_required
def add_comment(story_id):
    comment = request.form.get('comment')
    user_id = session['user_id']

    if not comment:
        flash('Comment cannot be empty.', 'danger')
        return redirect(url_for('view_story', story_id=story_id))

    db = get_db_connection()
    if not db:
        flash('Database connection failed.', 'danger')
        return redirect(url_for('view_story', story_id=story_id))

    try:
        cursor = db.cursor()
        cursor.execute(
            "INSERT INTO comments (user_id, story_id, comment) VALUES (%s, %s, %s)",
            (user_id, story_id, comment)
        )
        db.commit()
        flash('Comment added!', 'success')
    except Error as e:
        flash(f'Error adding comment: {e}', 'danger')
    finally:
        cursor.close()
        db.close()

    return redirect(url_for('view_story', story_id=story_id))

if __name__ == '__main__':
    app.run(debug=True)
