import csv
import io
from functools import wraps
from flask import Flask, request, jsonify, render_template, redirect, url_for, Response
from db import (
    init_db, get_projects, get_project, create_project, update_project,
    delete_project, hard_delete_project, set_project_status, parse_amount, format_amount,
    create_api_key, get_api_keys, verify_api_key, delete_api_key,
    add_share, remove_share, get_shares_granted, get_shares_received, can_view,
    get_hourly_rate, set_hourly_rate,
    VALID_STATUSES, VALID_UNITS,
)

app = Flask(__name__)
app.jinja_env.globals['format_amount'] = format_amount

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


# --- Web routes ---

@app.route('/')
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
                           hourly_rate=get_hourly_rate(view_as))


@app.route('/new', methods=['GET', 'POST'])
def new_project():
    user_id = get_user()
    if request.method == 'POST':
        data = parse_form(request.form)
        create_project(user_id, data)
        return redirect(url_for('dashboard'))
    return render_template('form.html', project=None, user=user_id)


@app.route('/edit/<int:project_id>', methods=['GET', 'POST'])
def edit_project(project_id):
    user_id = get_user()
    project = get_project(project_id)
    if not project or project['user_id'] != user_id:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        data = parse_form(request.form)
        update_project(project_id, data)
        return redirect(url_for('dashboard'))
    return render_template('form.html', project=project, user=user_id)


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
def sharing():
    user_id = get_user()
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            viewer_id = request.form.get('email', '').strip().lower()
            if viewer_id and viewer_id != user_id:
                add_share(user_id, viewer_id)
        elif action == 'remove':
            share_id = request.form.get('share_id')
            remove_share(share_id, user_id)
    grants = get_shares_granted(user_id)
    shared_from = get_shares_received(user_id)
    return render_template('sharing.html', user=user_id, grants=grants, shared_from=shared_from)


@app.route('/settings', methods=['GET', 'POST'])
def settings():
    user_id = get_user()
    saved = False
    if request.method == 'POST':
        rate_str = request.form.get('hourly_rate', '').strip()
        try:
            rate = float(rate_str) if rate_str else 0.0
            if rate < 0:
                rate = 0.0
            set_hourly_rate(user_id, rate)
            saved = True
        except ValueError:
            pass
    return render_template('settings.html', user=user_id,
                           hourly_rate=get_hourly_rate(user_id), saved=saved)


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
@api_auth_required
def api_next_project():
    projects = get_projects(request.api_user)
    if not projects:
        return jsonify({"project": None, "message": "No projects found."})
    return jsonify({"project": sanitise_project(projects[0])})


@app.route('/api/projects/<int:project_id>', methods=['GET'])
@api_auth_required
def api_get_project(project_id):
    project = get_project(project_id)
    if not project or project['user_id'] != request.api_user:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"project": sanitise_project(project)})


@app.route('/api/projects', methods=['POST'])
@api_auth_required
def api_create_project():
    data = request.get_json()
    if not data or not data.get('name'):
        return jsonify({"error": "name is required"}), 400
    project_id = create_project(request.api_user, data)
    project = get_project(project_id)
    return jsonify({"project": sanitise_project(project)}), 201


@app.route('/api/projects/<int:project_id>', methods=['PUT', 'PATCH'])
@api_auth_required
def api_update_project(project_id):
    project = get_project(project_id)
    if not project or project['user_id'] != request.api_user:
        return jsonify({"error": "Not found"}), 404
    data = request.get_json()
    update_project(project_id, data)
    project = get_project(project_id)
    return jsonify({"project": sanitise_project(project)})


@app.route('/api/projects/<int:project_id>/status', methods=['PUT', 'PATCH'])
@api_auth_required
def api_set_status(project_id):
    project = get_project(project_id)
    if not project or project['user_id'] != request.api_user:
        return jsonify({"error": "Not found"}), 404
    data = request.get_json()
    new_status = data.get('status') if data else None
    if new_status not in VALID_STATUSES:
        return jsonify({"error": f"status must be one of: {', '.join(VALID_STATUSES)}"}), 400
    set_project_status(project_id, new_status)
    project = get_project(project_id)
    return jsonify({"project": sanitise_project(project)})


@app.route('/api/projects/<int:project_id>', methods=['DELETE'])
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

    pbp_override = form.get('pbp_override', '').strip()
    data['pbp_override'] = float(pbp_override) if pbp_override else None

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
