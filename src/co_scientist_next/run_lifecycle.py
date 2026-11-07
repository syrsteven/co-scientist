"""Recoverable Run hiding. Never deletes execution history or cancels provider work."""
from .store import now


def initialize(store):
    store.db.execute('CREATE TABLE IF NOT EXISTS run_lifecycle (run_id TEXT PRIMARY KEY REFERENCES runs(id), state TEXT NOT NULL, updated_at TEXT NOT NULL)')
    store.db.commit()


def change(db, run_id, action):
    if action not in ('trash','restore'):
        raise ValueError('Unknown Run action')
    if db.execute('SELECT id FROM runs WHERE id=?',(run_id,)).fetchone() is None:
        raise ValueError('Unknown Run')
    with db:
        if action=='trash':
            db.execute("UPDATE research_runs SET status='stopped',reason='Run moved to Trash; remote work is not cancelled',updated_at=? WHERE run_id=? AND status IN ('running','paused')",(now(),run_id))
        db.execute('INSERT INTO run_lifecycle VALUES(?,?,?) ON CONFLICT(run_id) DO UPDATE SET state=excluded.state,updated_at=excluded.updated_at',(run_id,'trash' if action=='trash' else 'active',now()))
    return {'run_id':run_id,'state':'trash' if action=='trash' else 'active','execution_resumed':False}
