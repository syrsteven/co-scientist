import runpy
from pathlib import Path

from co_scientist_next.run_lifecycle import change
from co_scientist_next.store import Store

H=runpy.run_path(str(Path(__file__).with_name('test_research_controller.py')))


def test_run_trash_preserves_history_and_restore_never_resumes(tmp_path):
    with Store(tmp_path/'runs.sqlite') as s:
        c=H['controller'](s);run=H['start'](c)
        c.tick(run)
        original=s.rows('SELECT * FROM attempts')
        change(s.db,run,'trash')
        assert c.row(run)['status']=='stopped'
        assert not c.authorized_run(run)
        c.tick(run)
        assert s.rows('SELECT * FROM attempts')==original
        change(s.db,run,'restore')
        assert c.row(run)['status']=='stopped'
        assert s.rows('SELECT * FROM attempts')==original
        change(s.db,run,'restore')
        assert len(s.rows('SELECT * FROM runs'))==1


def test_hidden_project_cannot_poison_new_independent_start(tmp_path):
    from co_scientist_next.research_projects import change as project_change
    with Store(tmp_path/'hidden.sqlite') as s:
        c=H['controller'](s);old=H['start'](c,key='old-hidden')
        project_change(s,s.run(old)['project_id'],'trash')
        new=H['start'](c,key='new-independent')
        assert s.run(new)['project_id']!=s.run(old)['project_id']
        assert H['drain'](c,new)['status']=='completed'
        assert c.row(old)['status']=='stopped'
