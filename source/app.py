""" 
STAR "status tracking AI reporting Dashboard" Dashboard - Personal Use Only
Licensed under the Personal Use Source License (PUSL)
Copyright © 2025 Sai Vamsi Karnam
Attribution Required - No Commercial Use Permitted
See LICENSE for full terms
"""

from datetime import datetime, date
from dateutil import tz
import os, sys, time, threading, secrets
from flask import (
    Flask, render_template, request, redirect, url_for, jsonify, abort,
    send_from_directory, g
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, or_
from werkzeug.utils import secure_filename

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, 'data.db')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')  # per-task subfolders
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + DB_PATH
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'dev-secret'  # replace as needed
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

MAX_CONTENT_LENGTH = 1024 * 1024 * 1024  # 1 GB per request for optimal performance
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

db = SQLAlchemy(app)

# Association table for many-to-many Task<->Tag
TaskTag = db.Table(
    'task_tag_assoc',
    db.Column('task_id', db.Integer, db.ForeignKey('tasks.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tags.id'), primary_key=True),
)

class Task(db.Model):
    __tablename__ = 'tasks'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    status = db.Column(db.String(20), default='todo', index=True)  # todo, inprogress, done
    start_date = db.Column(db.Date, nullable=True, index=True)
    due_date = db.Column(db.Date, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    position = db.Column(db.Integer, default=0, index=True)
    archived = db.Column(db.Boolean, default=False, index=True)

    comments = db.relationship('Comment', backref='task', cascade='all, delete-orphan', lazy='dynamic')
    tags = db.relationship('Tag', secondary=TaskTag, backref=db.backref('tasks', lazy='dynamic'))
    attachments = db.relationship('Attachment', backref='task', cascade='all, delete-orphan', lazy='dynamic')

class Comment(db.Model):
    __tablename__ = 'comments'
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Tag(db.Model):
    __tablename__ = 'tags'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False, index=True)

class Attachment(db.Model):
    __tablename__ = 'attachments'
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=False, index=True)
    stored_name = db.Column(db.String(255), nullable=False)      # on disk
    original_name = db.Column(db.String(255), nullable=False)    # user-facing
    mime_type = db.Column(db.String(127), nullable=True)
    size_bytes = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# --- Utilities ---

def init_db():
    with app.app_context():
        db.create_all()

LOCAL_TZ = tz.tzlocal()

def parse_tags(s: str):
    if not s:
        return []
    parts = [p.strip() for p in s.split(',') if p.strip()]
    seen = set(); out = []
    for p in parts:
        k = p.lower()
        if k not in seen:
            seen.add(k); out.append(p)
    return out

def ensure_tags(tag_names):
    tags = []
    for name in tag_names:
        t = Tag.query.filter(func.lower(Tag.name) == name.lower()).first()
        if not t:
            t = Tag(name=name)
            db.session.add(t)
        tags.append(t)
    return tags

def apply_task_filters(base_query):
    q = request.args.get('q', '').strip()
    show_tags = parse_tags(request.args.get('show', ''))
    hide_tags = parse_tags(request.args.get('hide', ''))
    include_archived = request.args.get('archived', '0') == '1'

    if not include_archived:
        base_query = base_query.filter_by(archived=False)
    if q:
        like = f"%{q}%"
        base_query = base_query.filter(or_(Task.title.ilike(like), Task.description.ilike(like)))
    for tag in show_tags:
        base_query = base_query.filter(Task.tags.any(func.lower(Tag.name) == tag.lower()))
    if hide_tags:
        base_query = base_query.filter(~Task.tags.any(func.lower(Tag.name).in_([t.lower() for t in hide_tags])))
    return base_query, show_tags, hide_tags, q, include_archived

# Ajax detection (used to decide JSON vs redirect)
def is_ajax(req):
    return req.headers.get('X-Requested-With') == 'XMLHttpRequest'

SHUTDOWN_TOKEN = secrets.token_urlsafe(24)
LAST_ACTIVITY = time.time()

# --- Routes ---
@app.route('/')
def board():
    base = Task.query
    base, show_tags, hide_tags, q, include_archived = apply_task_filters(base)
    tasks_by_status = {
        'todo': base.filter_by(status='todo').order_by(Task.position.asc(), Task.id.asc()).all(),
        'inprogress': base.filter_by(status='inprogress').order_by(Task.position.asc(), Task.id.asc()).all(),
        'done': base.filter_by(status='done').order_by(Task.position.asc(), Task.id.asc()).all()
    }
    all_tags = Tag.query.order_by(Tag.name.asc()).all()
    return render_template('board.html', tasks_by_status=tasks_by_status, all_tags=all_tags,
                           show_tags=show_tags, hide_tags=hide_tags, q=q, include_archived=include_archived)

@app.route('/calendar')
def calendar_view():
    base = Task.query
    base, show_tags, hide_tags, q, include_archived = apply_task_filters(base)
    tasks = base.order_by(Task.due_date.asc().nulls_last(), Task.id.asc()).all()
    tasks_by_day = {}
    for t in tasks:
        if t.due_date:
            tasks_by_day.setdefault(t.due_date, []).append(t)
    today = date.today()
    all_tags = Tag.query.order_by(Tag.name.asc()).all()
    return render_template('calendar.html', tasks_by_day=tasks_by_day, today=today, all_tags=all_tags,
                           show_tags=show_tags, hide_tags=hide_tags, q=q, include_archived=include_archived)

@app.route('/tasks', methods=['POST'])
def create_task():
    title = request.form.get('title', '').strip() or 'Untitled Task'
    description = request.form.get('description', '').strip()
    start_raw = request.form.get('start_date', '').strip()
    due_raw = request.form.get('due_date', '').strip()
    tags_raw = request.form.get('tags', '').strip()
    status = 'todo'

    start = None
    if start_raw:
        try:
            start = datetime.strptime(start_raw, '%Y-%m-%d').date()
        except ValueError:
            pass

    due = None
    if due_raw:
        try:
            due = datetime.strptime(due_raw, '%Y-%m-%d').date()
        except ValueError:
            pass

    max_pos = db.session.query(db.func.max(Task.position)).filter_by(status=status).scalar() or 0
    new_task = Task(title=title, description=description, start_date=start, due_date=due, status=status, position=max_pos + 1)

    tag_objs = ensure_tags(parse_tags(tags_raw))
    new_task.tags = tag_objs

    db.session.add(new_task)
    db.session.commit()
    return redirect(url_for('board'))

@app.route('/tasks/<int:task_id>')
def task_detail(task_id):
    task = Task.query.get_or_404(task_id)
    all_tags = Tag.query.order_by(Tag.name.asc()).all()

    # Get plain lists with desired ordering:
    attachments = task.attachments.order_by(Attachment.created_at.desc()).all()
    comments = task.comments.order_by(Comment.created_at.asc()).all()

    return render_template(
        '_task_card.html',
        task=task,
        detail=True,
        all_tags=all_tags,
        attachments=attachments,
        comments=comments,
    )

@app.route('/tasks/<int:task_id>/comments', methods=['POST'])
def add_comment(task_id):
    task = Task.query.get_or_404(task_id)
    # NOTE: your template used "content" (not "comment"); keeping as-is
    content = request.form.get('content', '').strip()
    if not content:
        abort(400, 'Comment content required')
    c = Comment(task_id=task.id, content=content)
    db.session.add(c)
    db.session.commit()

    # AJAX => JSON (no navigation). Non-AJAX => PRG back to where user was.
    if is_ajax(request):
        return jsonify({"ok": True, "task_id": task.id, "content": content})
    return redirect(request.referrer or url_for('board'))

@app.route('/tasks/<int:task_id>/update', methods=['POST'])
def update_task_meta(task_id):
    task = Task.query.get_or_404(task_id)
    title = request.form.get('title')
    description = request.form.get('description')
    start_raw = request.form.get('start_date')
    due_raw = request.form.get('due_date')
    tags_raw = request.form.get('tags')
    archived_raw = request.form.get('archived')

    if title is not None:
        task.title = title.strip() or task.title
    if description is not None:
        task.description = description.strip()
    if start_raw is not None:
        if start_raw == '':
            task.start_date = None
        else:
            try:
                task.start_date = datetime.strptime(start_raw, '%Y-%m-%d').date()
            except ValueError:
                pass
    if due_raw is not None:
        if due_raw == '':
            task.due_date = None
        else:
            try:
                task.due_date = datetime.strptime(due_raw, '%Y-%m-%d').date()
            except ValueError:
                pass
    if tags_raw is not None:
        task.tags = ensure_tags(parse_tags(tags_raw))
    if archived_raw is not None:
        task.archived = archived_raw == 'on'

    db.session.commit()
    return ('', 204)

@app.route('/tasks/<int:task_id>/delete', methods=['POST'])
def delete_task(task_id):
    task = Task.query.get_or_404(task_id)
    # remove files from disk as well
    for a in task.attachments.all():
        try:
            path = os.path.join(app.config['UPLOAD_FOLDER'], str(task.id), a.stored_name)
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
    # remove task (attachments rows cascade)
    db.session.delete(task)
    db.session.commit()
    # optionally remove empty dir
    dir_path = os.path.join(app.config['UPLOAD_FOLDER'], str(task_id))
    if os.path.isdir(dir_path) and not os.listdir(dir_path):
        try: os.rmdir(dir_path)
        except Exception: pass
    return ('', 204)

# --- Attachments ---
@app.route('/tasks/<int:task_id>/attachments', methods=['POST'])
def upload_attachments(task_id):
    task = Task.query.get_or_404(task_id)
    files = request.files.getlist('files')
    if not files:
        abort(400, 'No files uploaded')
    task_dir = os.path.join(app.config['UPLOAD_FOLDER'], str(task.id))
    os.makedirs(task_dir, exist_ok=True)

    for f in files:
        if not f or f.filename == '':
            continue
        safe_name = secure_filename(f.filename)
        if not safe_name:
            continue
        # avoid collisions
        base, ext = os.path.splitext(safe_name)
        stored = safe_name
        i = 1
        while os.path.exists(os.path.join(task_dir, stored)):
            stored = f"{base}_{i}{ext}"
            i += 1
        full_path = os.path.join(task_dir, stored)
        f.save(full_path)
        size = os.path.getsize(full_path)
        att = Attachment(task_id=task.id, stored_name=stored, original_name=f.filename, mime_type=f.mimetype, size_bytes=size)
        db.session.add(att)
    db.session.commit()

    # AJAX to JSON; Non-AJAX to PRG back
    if is_ajax(request):
        return jsonify({"ok": True, "task_id": task.id})
    return redirect(request.referrer or url_for('board'))

@app.route('/attachments/<int:att_id>/download')
def download_attachment(att_id):
    att = Attachment.query.get_or_404(att_id)
    task_dir = os.path.join(app.config['UPLOAD_FOLDER'], str(att.task_id))
    return send_from_directory(task_dir, att.stored_name, as_attachment=True, download_name=att.original_name)

@app.route('/attachments/<int:att_id>/delete', methods=['POST'])
def delete_attachment(att_id):
    att = Attachment.query.get_or_404(att_id)
    path = os.path.join(app.config['UPLOAD_FOLDER'], str(att.task_id), att.stored_name)
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass
    db.session.delete(att)
    db.session.commit()
    return ('', 204)

@app.route('/update_status', methods=['POST'])
def update_status():
    data = request.get_json(force=True)
    task_id = data.get('task_id')
    new_status = data.get('new_status')
    new_position = data.get('new_position', 1)
    if new_status not in ('todo', 'inprogress', 'done'):
        return jsonify({'error': 'Invalid status'}), 400
    task = Task.query.get(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404

    siblings = Task.query.filter_by(status=new_status).order_by(Task.position.asc()).all()
    for s in siblings:
        if s.position >= new_position:
            s.position += 1
    task.status = new_status
    task.position = new_position
    db.session.commit()

    for status in ('todo', 'inprogress', 'done'):
        items = Task.query.filter_by(status=status).order_by(Task.position.asc(), Task.id.asc()).all()
        for i, item in enumerate(items, start=1):
            item.position = i
    db.session.commit()

    return jsonify({'ok': True})

@app.route('/export')
def export_json():
    tasks = Task.query.order_by(Task.id.asc()).all()
    payload = []
    for t in tasks:
        payload.append({
            'id': t.id,
            'title': t.title,
            'description': t.description,
            'status': t.status,
            'due_date': t.due_date.isoformat() if t.due_date else None,
            'created_at': t.created_at.isoformat(),
            'updated_at': t.updated_at.isoformat() if t.updated_at else None,
            'position': t.position,
            'archived': t.archived,
            'tags': [tag.name for tag in t.tags],
            'attachments': [
                {
                    'id': a.id,
                    'original_name': a.original_name,
                    'stored_name': a.stored_name,
                    'mime_type': a.mime_type,
                    'size_bytes': a.size_bytes,
                    'created_at': a.created_at.isoformat(),
                    'download_url': url_for('download_attachment', att_id=a.id)
                } for a in t.attachments.order_by(Attachment.created_at.asc()).all()
            ],
            'comments': [
                { 'id': c.id, 'content': c.content, 'created_at': c.created_at.isoformat() }
                for c in t.comments.order_by(Comment.created_at.asc()).all()
            ]
        })
    return jsonify({'exported_at': datetime.utcnow().isoformat() + 'Z', 'tasks': payload})

@app.before_request
def _touch_activity():
    global LAST_ACTIVITY
    LAST_ACTIVITY = time.time()

# --- Clean shutdown (no request leakage) ---
def _do_shutdown(shutdown_func):
    """Run outside request context."""
    try:
        time.sleep(0.15)  # time delay for HTTP 200 flush
    except Exception:
        pass
    if shutdown_func:
        try:
            shutdown_func()  # Werkzeug clean shutdown
            return
        except Exception:
            pass
    os._exit(0)  # hard exit fallback

@app.post('/shutdown')
def shutdown():
    if request.headers.get('X-Shutdown-Token') != SHUTDOWN_TOKEN:
        abort(403)
    # capture callable inside request context
    shutdown_func = request.environ.get('werkzeug.server.shutdown')
    threading.Thread(target=_do_shutdown, args=(shutdown_func,), daemon=True).start()
    return 'Shutting down...', 200

# make the token available to templates
@app.context_processor
def inject_shutdown_token():
    return {'SHUTDOWN_TOKEN': SHUTDOWN_TOKEN}

if __name__ == '__main__':
    import os, sys, threading, webbrowser

    init_db()

    host = '0.0.0.0' #'127.0.0.1'
    port = int(os.environ.get('PORT', 51410))
    url  = f'http://127.0.0.1:{port}'

    def open_browser_once():
        # Avoid double-open when the reloader spawns
        if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.debug:
            webbrowser.open(url)

    # If running as a frozen app, disable debug & reloader
    is_frozen = getattr(sys, 'frozen', False)
    debug = False if is_frozen else True
    use_reloader = not is_frozen

    threading.Timer(0.8, open_browser_once).start()
    app.run(host=host, port=port, debug=debug, use_reloader=use_reloader, threaded=True)