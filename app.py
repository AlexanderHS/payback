import csv
import io
import os
import re
import hashlib
import secrets
from functools import wraps
from flask import Flask, request, jsonify, render_template, redirect, url_for, Response
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from db import (
    init_db, get_projects, get_project, create_project, update_project,
    delete_project, hard_delete_project, set_project_status, parse_amount, format_amount,
    create_api_key, get_api_keys, verify_api_key, delete_api_key,
    add_share, remove_share, get_shares_granted, get_shares_received, can_view,
    get_hourly_rate, set_hourly_rate, has_hourly_rate_set, DEFAULT_HOURLY_RATE,
    touch_user, get_analytics, ValidationError,
    VALID_STATUSES, VALID_UNITS,
)
from project_templates import PROJECT_TEMPLATES

app = Flask(__name__)
app.jinja_env.globals['format_amount'] = format_amount
# SECRET_KEY must be stable across container restarts so CSRF tokens survive.
# Set SECRET_KEY in /opt/payback/.env (mounted via docker-compose env_file).
# Falls back to a fresh random one in dev if unset, which invalidates tokens on restart.
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or secrets.token_urlsafe(32)
csrf = CSRFProtect(app)


def _rate_limit_key():
    """Bucket per presented API key (hashed so the raw value never lands in the
    in-memory limiter store), or per remote IP if no key was sent."""
    auth = request.headers.get('Authorization', '').removeprefix('Bearer ').strip()
    key = auth or request.headers.get('X-API-Key', '').strip()
    if key:
        return 'k:' + hashlib.sha256(key.encode()).hexdigest()[:16]
    return get_remote_address()


limiter = Limiter(key_func=_rate_limit_key, app=app, storage_uri="memory://")

# Separate token, distinct from per-user API keys, for the analytics endpoint.
# Set in /opt/payback/.env. Empty = endpoint refuses everything.
ANALYTICS_TOKEN = os.environ.get('ANALYTICS_TOKEN', '')

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


@app.before_request
def _record_user():
    """Touch the users table on every authenticated web request so we have a
    real record of who's signed in. Skips API and static paths (no email
    header on those) and /docs (public)."""
    if request.path.startswith('/api/') or request.path.startswith('/static/'):
        return
    if request.path == '/docs':
        return
    email = request.headers.get('X-Forwarded-Email', '').strip().lower()
    if email and '@' in email:
        try:
            touch_user(email)
        except Exception:
            pass  # never block a request because of analytics bookkeeping

UNIT_LABELS = {
    'once': '$ one-off',
    'pcm': '$/mo',
    'py': '$/yr',
    'hours': 'h one-off',
    'hours_pcm': 'h/mo',
}
app.jinja_env.globals['format_unit'] = lambda u: UNIT_LABELS.get(u, u)


def get_user():
    """Get current user from oauth2-proxy headers, fallback for local dev.
    Public deploy uses full email so prefix collisions across domains are impossible.
    """
    return (
        request.headers.get('X-Forwarded-Email', '').strip().lower() or
        request.headers.get('X-Forwarded-User') or
        'dev'
    )


def get_api_user():
    """Authenticate API requests via API key. Returns user_id or None."""
    key = request.headers.get('Authorization', '').removeprefix('Bearer ').strip()
    if not key:
        key = request.headers.get('X-API-Key', '')
    if key:
        return verify_api_key(key)
    return None


def api_auth_required(f):
    """Decorator for API routes that require an API key."""
    @wraps(f)
    def decorated(*args, **kwargs):
        user_id = get_api_user()
        if not user_id:
            return jsonify({"error": "Valid API key required. Pass via Authorization: Bearer <key> or X-API-Key header."}), 401
        request.api_user = user_id
        return f(*args, **kwargs)
    return decorated


def analytics_auth_required(f):
    """Decorator for the analytics endpoint. Token is a separate env var, not a per-user key."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization', '').removeprefix('Bearer ').strip()
        if not token:
            token = request.headers.get('X-API-Key', '').strip()
        if not ANALYTICS_TOKEN or not token or not secrets.compare_digest(token, ANALYTICS_TOKEN):
            return jsonify({"error": "Valid analytics token required."}), 401
        return f(*args, **kwargs)
    return decorated


# --- Public routes (oauth2-proxy is configured to skip auth on these) ---

@app.route('/')
def landing():
    """Public marketing landing page. Logged-in visitors are redirected to
    /dashboard client-side via a small fetch against /oauth2/auth — see
    landing.html. We can't detect auth server-side here because oauth2-proxy's
    skip_auth_routes bypasses header injection for this path."""
    return render_template('landing.html')


@app.route('/privacy')
def privacy():
    """Public privacy page. Honest, operational — see also /docs."""
    return render_template('privacy.html')


# --- Web routes (require oauth2-proxy auth in prod; fall back to 'dev' user
#     when running `python app.py` directly without the proxy) ---

@app.route('/dashboard')
def dashboard():
    user_id = get_user()
    view_as = request.args.get('view_as', user_id)
    # Only allow viewing if it's yourself or you have a share
    if view_as != user_id and not can_view(user_id, view_as):
        view_as = user_id
    readonly = view_as != user_id

    status = request.args.get('status', 'active')
    if status not in (*VALID_STATUSES, 'all'):
        status = 'active'
    projects = get_projects(view_as, status=status)
    counts = {}
    for s in VALID_STATUSES:
        counts[s] = len(get_projects(view_as, status=s))

    # Build list of viewable users for the switcher
    shared_from = get_shares_received(user_id)
    viewable = [user_id] + shared_from

    return render_template('dashboard.html', projects=projects, user=user_id,
                           view_as=view_as, readonly=readonly, viewable=viewable,
                           current_status=status, counts=counts,
                           hourly_rate=get_hourly_rate(view_as),
                           hourly_rate_set=has_hourly_rate_set(view_as),
                           default_hourly_rate=DEFAULT_HOURLY_RATE)


@app.route('/new', methods=['GET', 'POST'])
def new_project():
    user_id = get_user()
    if request.method == 'POST':
        data = parse_form(request.form)
        try:
            create_project(user_id, data)
            return redirect(url_for('dashboard'))
        except ValidationError as e:
            return render_template('form.html', project=data, user=user_id, error=str(e))
    # Empty-state prompt chips on the dashboard deep-link here with a
    # template slug; load the worked-example dict so the form opens
    # already populated. Falls through to a legacy ?name= prefill (kept
    # for backward compat) and finally to a blank form.
    template_slug = (request.args.get('template') or '').strip()
    if template_slug in PROJECT_TEMPLATES:
        # Copy so accidental edits to the template dict in this request
        # don't leak into future requests.
        project = dict(PROJECT_TEMPLATES[template_slug])
    else:
        prefill_name = (request.args.get('name') or '').strip()[:200]
        project = {'name': prefill_name} if prefill_name else None
    return render_template('form.html', project=project, user=user_id, error=None)


@app.route('/edit/<int:project_id>', methods=['GET', 'POST'])
def edit_project(project_id):
    user_id = get_user()
    project = get_project(project_id)
    if not project or project['user_id'] != user_id:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        data = parse_form(request.form)
        try:
            update_project(project_id, data)
            return redirect(url_for('dashboard'))
        except ValidationError as e:
            # Re-render with the user's just-typed data merged onto the existing
            # project so they don't lose work
            project = {**dict(project), **data}
            return render_template('form.html', project=project, user=user_id, error=str(e))
    return render_template('form.html', project=project, user=user_id, error=None)


@app.route('/status/<int:project_id>', methods=['POST'])
def change_status(project_id):
    user_id = get_user()
    project = get_project(project_id)
    if not project or project['user_id'] != user_id:
        return redirect(url_for('dashboard'))
    new_status = request.form.get('status')
    if new_status in VALID_STATUSES:
        set_project_status(project_id, new_status)
    return_to = request.form.get('return_status', 'active')
    return redirect(url_for('dashboard', status=return_to))


@app.route('/delete/<int:project_id>', methods=['POST'])
def delete_project_route(project_id):
    user_id = get_user()
    project = get_project(project_id)
    if project and project['user_id'] == user_id:
        delete_project(project_id)
    return redirect(url_for('dashboard'))


@app.route('/purge/<int:project_id>', methods=['POST'])
def purge_project_route(project_id):
    """Permanently delete. Only allowed on projects already archived by the owner."""
    user_id = get_user()
    project = get_project(project_id)
    if project and project['user_id'] == user_id and project.get('status') == 'archived':
        hard_delete_project(project_id)
    return redirect(url_for('dashboard', status='archived'))


@app.route('/sharing', methods=['GET', 'POST'])
@limiter.limit("10/minute", methods=['POST'])
def sharing():
    user_id = get_user()
    error = None
    notice = None
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            viewer_id = request.form.get('email', '').strip().lower()
            if not EMAIL_RE.match(viewer_id):
                error = "Enter a full email address (e.g. alex@example.com)."
            elif viewer_id == user_id:
                error = "That's your own account."
            else:
                # Persist regardless of whether viewer has an account.
                # Constant response avoids leaking who is/isn't a Payback user.
                add_share(user_id, viewer_id)
                notice = (f"Share saved for {viewer_id}. They'll see your projects "
                          "the next time they sign in to Payback (or right now, if "
                          "they already have an account).")
        elif action == 'remove':
            share_id = request.form.get('share_id')
            remove_share(share_id, user_id)
    grants = get_shares_granted(user_id)
    shared_from = get_shares_received(user_id)
    return render_template('sharing.html', user=user_id, grants=grants,
                           shared_from=shared_from, error=error, notice=notice)


@app.route('/settings', methods=['GET', 'POST'])
def settings():
    user_id = get_user()
    saved = False
    if request.method == 'POST':
        rate_str = request.form.get('hourly_rate', '').strip()
        # Empty submission = "no change"; we don't want to upsert a row,
        # because the absence of a row is what flags the user as never-set
        # and triggers the dashboard nudge banner.
        if rate_str:
            try:
                rate = float(rate_str)
                if rate < 0:
                    rate = 0.0
                set_hourly_rate(user_id, rate)
                saved = True
            except ValueError:
                pass
        # Accept-default action on the dashboard banner posts here with
        # next=dashboard. Send them straight back rather than dumping
        # them on /settings just to confirm a value they didn't type.
        if saved and request.form.get('next') == 'dashboard':
            return redirect(url_for('dashboard'))
    return render_template('settings.html', user=user_id,
                           hourly_rate=get_hourly_rate(user_id),
                           hourly_rate_set=has_hourly_rate_set(user_id),
                           default_hourly_rate=DEFAULT_HOURLY_RATE,
                           saved=saved)


@app.route('/keys', methods=['GET', 'POST'])
def manage_keys():
    user_id = get_user()
    new_key = None
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'create':
            label = request.form.get('label', '').strip() or 'default'
            new_key = create_api_key(user_id, label)
        elif action == 'delete':
            key_id = request.form.get('key_id')
            delete_api_key(key_id, user_id)
    keys = get_api_keys(user_id)
    return render_template('keys.html', keys=keys, user=user_id, new_key=new_key)


# --- HTMX partials ---

@app.route('/partials/line-item')
def line_item_partial():
    item_type = request.args.get('type', 'cost')
    index = request.args.get('index', '0')
    return render_template('partials/line_item.html', type=item_type, index=index)


# --- API routes ---

@app.route('/api/projects', methods=['GET'])
@limiter.limit("60/minute")
@csrf.exempt
@api_auth_required
def api_list_projects():
    status = request.args.get('status', 'active')
    if status not in (*VALID_STATUSES, 'all'):
        status = 'active'
    projects = get_projects(request.api_user, status=status)
    fmt = request.args.get('format', 'json')

    if fmt == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['rank', 'name', 'status', 'pbp_months', 'upfront_cost', 'monthly_benefit', 'net_monthly', 'strategy'])
        for i, p in enumerate(projects, 1):
            writer.writerow([
                i, p['name'], p.get('status', 'active'),
                p['pbp_months'] if p['pbp_months'] is not None else 'never',
                p['upfront_cost'], p['monthly_benefit'], p['net_monthly'],
                (p.get('strategy') or '')[:100],
            ])
        return Response(output.getvalue(), mimetype='text/csv',
                        headers={'Content-Disposition': 'attachment; filename=payback_projects.csv'})

    return jsonify({"user": request.api_user, "projects": sanitise_projects(projects)})


@app.route('/api/projects/next', methods=['GET'])
@limiter.limit("60/minute")
@csrf.exempt
@api_auth_required
def api_next_project():
    projects = get_projects(request.api_user)
    if not projects:
        return jsonify({"project": None, "message": "No projects found."})
    return jsonify({"project": sanitise_project(projects[0])})


@app.route('/api/projects/<int:project_id>', methods=['GET'])
@limiter.limit("60/minute")
@csrf.exempt
@api_auth_required
def api_get_project(project_id):
    project = get_project(project_id)
    if not project or project['user_id'] != request.api_user:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"project": sanitise_project(project)})


@app.route('/api/projects', methods=['POST'])
@limiter.limit("60/minute")
@csrf.exempt
@api_auth_required
def api_create_project():
    data = request.get_json(silent=True)
    err = _validate_project_payload(data, require_name=True)
    if err:
        return jsonify({"error": err}), 400
    try:
        project_id = create_project(request.api_user, data)
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400
    project = get_project(project_id)
    return jsonify({"project": sanitise_project(project)}), 201


@app.route('/api/projects/<int:project_id>', methods=['PUT', 'PATCH'])
@limiter.limit("60/minute")
@csrf.exempt
@api_auth_required
def api_update_project(project_id):
    project = get_project(project_id)
    if not project or project['user_id'] != request.api_user:
        return jsonify({"error": "Not found"}), 404
    data = request.get_json(silent=True)
    err = _validate_project_payload(data)
    if err:
        return jsonify({"error": err}), 400
    try:
        update_project(project_id, data)
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400
    project = get_project(project_id)
    return jsonify({"project": sanitise_project(project)})


@app.route('/api/analytics', methods=['GET'])
@limiter.limit("60/minute")
@csrf.exempt
@analytics_auth_required
def api_analytics():
    return jsonify(get_analytics())


@app.route('/api/projects/<int:project_id>/status', methods=['PUT', 'PATCH'])
@limiter.limit("60/minute")
@csrf.exempt
@api_auth_required
def api_set_status(project_id):
    project = get_project(project_id)
    if not project or project['user_id'] != request.api_user:
        return jsonify({"error": "Not found"}), 404
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Body must be a JSON object"}), 400
    new_status = data.get('status')
    if new_status not in VALID_STATUSES:
        return jsonify({"error": f"status must be one of: {', '.join(VALID_STATUSES)}"}), 400
    set_project_status(project_id, new_status)
    project = get_project(project_id)
    return jsonify({"project": sanitise_project(project)})


@app.route('/api/projects/<int:project_id>', methods=['DELETE'])
@limiter.limit("60/minute")
@csrf.exempt
@api_auth_required
def api_delete_project(project_id):
    project = get_project(project_id)
    if not project or project['user_id'] != request.api_user:
        return jsonify({"error": "Not found"}), 404
    hard = request.args.get('hard', '').lower() in ('1', 'true', 'yes')
    if hard:
        if project.get('status') != 'archived':
            return jsonify({"error": "Project must be archived before it can be permanently deleted. Call DELETE without ?hard=true first, or set status to 'archived'."}), 409
        hard_delete_project(project_id)
        return jsonify({"deleted": True, "permanent": True})
    delete_project(project_id)
    return jsonify({"deleted": True})


@app.route('/docs')
def docs():
    user_id = get_user()
    return render_template('docs.html', user=user_id)


@app.route('/health')
def health():
    return jsonify({"status": "ok"})


# --- Helpers ---

def parse_form(form):
    """Parse the web form into the data dict expected by create/update_project.
    Drops line items with invalid units silently."""
    data = {
        'name': form.get('name', '').strip(),
        'target': form.get('target', '').strip() or None,
        'strategy': form.get('strategy', '').strip() or None,
        'pros_cons': form.get('pros_cons', '').strip() or None,
        'alternatives': form.get('alternatives', '').strip() or None,
        'notes': form.get('notes', '').strip() or None,
    }

    data['costs'] = []
    data['benefits'] = []

    # Collect dynamic line items from form
    i = 0
    while True:
        desc = form.get(f'cost_desc_{i}')
        if desc is None:
            break
        amount_str = form.get(f'cost_amount_{i}', '').strip()
        unit = form.get(f'cost_unit_{i}', 'once')
        if desc.strip() and amount_str and unit in VALID_UNITS:
            data['costs'].append({
                'description': desc.strip(),
                'amount': amount_str,
                'unit': unit,
            })
        i += 1

    i = 0
    while True:
        desc = form.get(f'benefit_desc_{i}')
        if desc is None:
            break
        amount_str = form.get(f'benefit_amount_{i}', '').strip()
        unit = form.get(f'benefit_unit_{i}', 'once')
        if desc.strip() and amount_str and unit in VALID_UNITS:
            data['benefits'].append({
                'description': desc.strip(),
                'amount': amount_str,
                'unit': unit,
            })
        i += 1

    return data


def _validate_items(items, kind):
    """Return error string or None."""
    if not isinstance(items, list):
        return f"{kind} must be a list"
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            return f"{kind}[{i}] must be an object"
        if item.get('unit') not in VALID_UNITS:
            return f"{kind}[{i}].unit must be one of {list(VALID_UNITS)}"
        if not isinstance(item.get('description'), str) or not item['description'].strip():
            return f"{kind}[{i}].description is required"
        try:
            parse_amount(item.get('amount'))
        except (ValueError, TypeError):
            return f"{kind}[{i}].amount is not a valid number"
    return None


def _validate_project_payload(data, require_name=False):
    """Return error string or None. require_name=True for create."""
    if not isinstance(data, dict):
        return "Body must be a JSON object"
    if require_name:
        if not isinstance(data.get('name'), str) or not data['name'].strip():
            return "name is required"
    if 'status' in data and data['status'] not in VALID_STATUSES:
        return f"status must be one of {list(VALID_STATUSES)}"
    if 'costs' in data:
        err = _validate_items(data['costs'], 'costs')
        if err:
            return err
    if 'benefits' in data:
        err = _validate_items(data['benefits'], 'benefits')
        if err:
            return err
    return None


def sanitise_project(p):
    """Strip internal fields for API output."""
    return {
        'id': p['id'],
        'name': p['name'],
        'status': p.get('status', 'active'),
        'target': p.get('target'),
        'strategy': p.get('strategy'),
        'pros_cons': p.get('pros_cons'),
        'alternatives': p.get('alternatives'),
        'notes': p.get('notes'),
        'costs': [{'description': c['description'], 'amount': c['amount'], 'unit': c['unit']} for c in p.get('costs', [])],
        'benefits': [{'description': b['description'], 'amount': b['amount'], 'unit': b['unit']} for b in p.get('benefits', [])],
        'pbp_months': p.get('pbp_months'),
        'upfront_cost': p.get('upfront_cost', 0),
        'monthly_cost': p.get('monthly_cost', 0),
        'monthly_benefit': p.get('monthly_benefit', 0),
        'net_monthly': p.get('net_monthly', 0),
    }


def sanitise_projects(projects):
    return [sanitise_project(p) for p in projects]


if __name__ == '__main__':
    init_db()
    from waitress import serve
    serve(app, host='0.0.0.0', port=5000)
