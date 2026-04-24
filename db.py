import sqlite3
import os
import re
import secrets

DB_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'payback.db')


def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


VALID_STATUSES = ('active', 'done', 'dropped', 'archived')
VALID_UNITS = ('once', 'pcm', 'py', 'hours', 'hours_pcm')


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,

            target TEXT,
            strategy TEXT,
            pros_cons TEXT,
            alternatives TEXT,
            notes TEXT,
            pbp_override REAL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS line_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('cost', 'benefit')),
            description TEXT NOT NULL,
            amount REAL NOT NULL,
            unit TEXT NOT NULL CHECK(unit IN ('once', 'pcm', 'py', 'hours', 'hours_pcm')),
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS shares (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id TEXT NOT NULL,
            viewer_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(owner_id, viewer_id)
        );

        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            key TEXT NOT NULL UNIQUE,
            label TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS user_settings (
            user_id TEXT PRIMARY KEY,
            hourly_rate REAL NOT NULL DEFAULT 0
        );
    """)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(projects)").fetchall()]
    if 'status' not in cols:
        conn.execute("ALTER TABLE projects ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
    if 'letter' in cols:
        conn.execute("ALTER TABLE projects DROP COLUMN letter")

    conn.commit()
    conn.close()


def parse_amount(s):
    """Parse amount string like '4.5k', '$200', '1.2k' to float AUD."""
    s = str(s).strip().lower().replace(',', '').replace('$', '').replace(' ', '')
    if s.endswith('k'):
        return float(s[:-1]) * 1000
    return float(s)


def format_amount(amount):
    """Format AUD amount for display."""
    if amount is None:
        return "$0"
    amount = abs(amount)
    if amount >= 1000:
        k = amount / 1000
        if k == int(k):
            return f"${int(k)}k"
        return f"${k:.1f}k"
    if amount == int(amount):
        return f"${int(amount)}"
    return f"${amount:,.0f}"


def _summarize(items, hourly_rate):
    """Sum line items into upfront/monthly $ totals plus raw hours."""
    upfront = (
        sum(i['amount'] for i in items if i['unit'] == 'once') +
        sum(i['amount'] * hourly_rate for i in items if i['unit'] == 'hours')
    )
    monthly = (
        sum(i['amount'] for i in items if i['unit'] == 'pcm') +
        sum(i['amount'] / 12 for i in items if i['unit'] == 'py') +
        sum(i['amount'] * hourly_rate for i in items if i['unit'] == 'hours_pcm')
    )
    upfront_hours = sum(i['amount'] for i in items if i['unit'] == 'hours')
    monthly_hours = sum(i['amount'] for i in items if i['unit'] == 'hours_pcm')
    return upfront, monthly, upfront_hours, monthly_hours


def calculate_pbp(costs, benefits, hourly_rate=0):
    """Calculate payback period in months from line items."""
    upfront_cost, monthly_cost, _, _ = _summarize(costs, hourly_rate)
    upfront_benefit, monthly_benefit, _, _ = _summarize(benefits, hourly_rate)

    net_upfront = upfront_cost - upfront_benefit
    net_monthly = monthly_benefit - monthly_cost

    if net_monthly <= 0:
        return None  # never pays back
    if net_upfront <= 0:
        return 0  # already net positive

    return round(net_upfront / net_monthly, 1)


def _hydrate_project(p, hourly_rate):
    """Compute pbp_months and summary fields on a project dict (mutates)."""
    if p['pbp_override'] is not None:
        p['pbp_months'] = p['pbp_override']
    else:
        p['pbp_months'] = calculate_pbp(p['costs'], p['benefits'], hourly_rate)

    cu, cm, cuh, cmh = _summarize(p['costs'], hourly_rate)
    bu, bm, buh, bmh = _summarize(p['benefits'], hourly_rate)
    p['upfront_cost'], p['monthly_cost'] = cu, cm
    p['upfront_benefit'], p['monthly_benefit'] = bu, bm
    p['net_monthly'] = bm - cm
    p['upfront_hours_cost'], p['monthly_hours_cost'] = cuh, cmh
    p['upfront_hours_benefit'], p['monthly_hours_benefit'] = buh, bmh
    p['net_monthly_hours'] = bmh - cmh
    p['hourly_rate'] = hourly_rate


def get_projects(user_id, status='active'):
    """Get all projects for a user with line items, sorted by PBPm."""
    conn = get_db()
    rate = _get_hourly_rate(conn, user_id)
    if status == 'all':
        rows = conn.execute(
            "SELECT * FROM projects WHERE user_id = ? ORDER BY name", (user_id,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM projects WHERE user_id = ? AND status = ? ORDER BY name", (user_id, status)
        ).fetchall()

    projects = []
    for row in rows:
        p = dict(row)
        items = conn.execute(
            "SELECT * FROM line_items WHERE project_id = ?", (p['id'],)
        ).fetchall()
        p['costs'] = [dict(i) for i in items if i['type'] == 'cost']
        p['benefits'] = [dict(i) for i in items if i['type'] == 'benefit']
        _hydrate_project(p, rate)
        projects.append(p)

    conn.close()

    # Sort: projects with PBP first (ascending), then no-payback projects
    with_pbp = sorted([p for p in projects if p['pbp_months'] is not None], key=lambda p: p['pbp_months'])
    without_pbp = [p for p in projects if p['pbp_months'] is None]
    return with_pbp + without_pbp


def get_project(project_id):
    """Get a single project with line items."""
    conn = get_db()
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        conn.close()
        return None

    p = dict(row)
    rate = _get_hourly_rate(conn, p['user_id'])
    items = conn.execute(
        "SELECT * FROM line_items WHERE project_id = ?", (p['id'],)
    ).fetchall()
    p['costs'] = [dict(i) for i in items if i['type'] == 'cost']
    p['benefits'] = [dict(i) for i in items if i['type'] == 'benefit']
    _hydrate_project(p, rate)

    conn.close()
    return p


def create_project(user_id, data):
    """Create a project with line items. Returns project id."""
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO projects (user_id, name, target, strategy, pros_cons, alternatives, notes, pbp_override)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, data['name'], data.get('target'),
         data.get('strategy'), data.get('pros_cons'), data.get('alternatives'),
         data.get('notes'), data.get('pbp_override'))
    )
    project_id = cur.lastrowid

    for cost in data.get('costs', []):
        amount = parse_amount(cost['amount']) if isinstance(cost['amount'], str) else cost['amount']
        conn.execute(
            "INSERT INTO line_items (project_id, type, description, amount, unit) VALUES (?, 'cost', ?, ?, ?)",
            (project_id, cost['description'], amount, cost['unit'])
        )

    for benefit in data.get('benefits', []):
        amount = parse_amount(benefit['amount']) if isinstance(benefit['amount'], str) else benefit['amount']
        conn.execute(
            "INSERT INTO line_items (project_id, type, description, amount, unit) VALUES (?, 'benefit', ?, ?, ?)",
            (project_id, benefit['description'], amount, benefit['unit'])
        )

    conn.commit()
    conn.close()
    return project_id


def update_project(project_id, data):
    """Update a project and its line items."""
    conn = get_db()

    fields = []
    values = []
    for key in ('name', 'target', 'strategy', 'pros_cons', 'alternatives', 'notes', 'pbp_override', 'status'):
        if key in data:
            fields.append(f"{key} = ?")
            values.append(data[key])

    if fields:
        fields.append("updated_at = CURRENT_TIMESTAMP")
        values.append(project_id)
        conn.execute(f"UPDATE projects SET {', '.join(fields)} WHERE id = ?", values)

    # Replace line items independently - sending costs only leaves benefits untouched and vice versa
    if 'costs' in data:
        conn.execute("DELETE FROM line_items WHERE project_id = ? AND type = 'cost'", (project_id,))
        for cost in data['costs']:
            amount = parse_amount(cost['amount']) if isinstance(cost['amount'], str) else cost['amount']
            conn.execute(
                "INSERT INTO line_items (project_id, type, description, amount, unit) VALUES (?, 'cost', ?, ?, ?)",
                (project_id, cost['description'], amount, cost['unit'])
            )
    if 'benefits' in data:
        conn.execute("DELETE FROM line_items WHERE project_id = ? AND type = 'benefit'", (project_id,))
        for benefit in data['benefits']:
            amount = parse_amount(benefit['amount']) if isinstance(benefit['amount'], str) else benefit['amount']
            conn.execute(
                "INSERT INTO line_items (project_id, type, description, amount, unit) VALUES (?, 'benefit', ?, ?, ?)",
                (project_id, benefit['description'], amount, benefit['unit'])
            )

    conn.commit()
    conn.close()


def set_project_status(project_id, status):
    """Change a project's status."""
    conn = get_db()
    conn.execute(
        "UPDATE projects SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (status, project_id)
    )
    conn.commit()
    conn.close()


def delete_project(project_id):
    """Soft delete - sets status to archived."""
    set_project_status(project_id, 'archived')


def hard_delete_project(project_id):
    """Permanently delete a project and its line items. Caller must check ownership and archived state."""
    conn = get_db()
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()
    conn.close()


def create_api_key(user_id, label=None):
    """Generate a new API key for a user. Returns the key string."""
    key = f"payback_{secrets.token_urlsafe(32)}"
    conn = get_db()
    conn.execute(
        "INSERT INTO api_keys (user_id, key, label) VALUES (?, ?, ?)",
        (user_id, key, label)
    )
    conn.commit()
    conn.close()
    return key


def get_api_keys(user_id):
    """List API keys for a user (masked)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, label, key, created_at FROM api_keys WHERE user_id = ?", (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def verify_api_key(key):
    """Look up an API key. Returns user_id or None."""
    conn = get_db()
    row = conn.execute("SELECT user_id FROM api_keys WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row['user_id'] if row else None


def delete_api_key(key_id, user_id):
    """Revoke an API key. Only deletes if it belongs to user_id."""
    conn = get_db()
    conn.execute("DELETE FROM api_keys WHERE id = ? AND user_id = ?", (key_id, user_id))
    conn.commit()
    conn.close()


def add_share(owner_id, viewer_id):
    """Grant viewer read access to owner's projects."""
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO shares (owner_id, viewer_id) VALUES (?, ?)",
        (owner_id, viewer_id)
    )
    conn.commit()
    conn.close()


def remove_share(share_id, owner_id):
    """Revoke a share. Only owner can revoke."""
    conn = get_db()
    conn.execute("DELETE FROM shares WHERE id = ? AND owner_id = ?", (share_id, owner_id))
    conn.commit()
    conn.close()


def get_shares_granted(owner_id):
    """List users the owner has shared with."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, viewer_id, created_at FROM shares WHERE owner_id = ?", (owner_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_shares_received(viewer_id):
    """List users who have shared with this viewer."""
    conn = get_db()
    rows = conn.execute(
        "SELECT owner_id FROM shares WHERE viewer_id = ?", (viewer_id,)
    ).fetchall()
    conn.close()
    return [r['owner_id'] for r in rows]


def can_view(viewer_id, owner_id):
    """Check if viewer has access to owner's projects."""
    if viewer_id == owner_id:
        return True
    conn = get_db()
    row = conn.execute(
        "SELECT 1 FROM shares WHERE owner_id = ? AND viewer_id = ?",
        (owner_id, viewer_id)
    ).fetchone()
    conn.close()
    return row is not None


def _get_hourly_rate(conn, user_id):
    row = conn.execute(
        "SELECT hourly_rate FROM user_settings WHERE user_id = ?", (user_id,)
    ).fetchone()
    return row['hourly_rate'] if row else 0.0


def get_hourly_rate(user_id):
    """Return the user's hourly rate (0 if unset)."""
    conn = get_db()
    rate = _get_hourly_rate(conn, user_id)
    conn.close()
    return rate


def set_hourly_rate(user_id, rate):
    """Upsert the user's hourly rate."""
    conn = get_db()
    conn.execute(
        """INSERT INTO user_settings (user_id, hourly_rate) VALUES (?, ?)
           ON CONFLICT(user_id) DO UPDATE SET hourly_rate = excluded.hourly_rate""",
        (user_id, rate)
    )
    conn.commit()
    conn.close()
