import json

import pytest

from co_scientist_next.goal import parse_screen, parse_screen_v2

POLICY={'id':'test','version':'1','text':'GJ-1 conceptual use. GJ-2 unknown is not rejection.'}


def output():
    return {'completed':True,'decision':'pass','rationale':['Conceptual use only.','Unknown is not rejection.'],'target_scope':'Conceptual','policy_refs':{'id':'test','version':'1','clauses':['GJ-1','GJ-2']},'limitations':['Nonproduction']}


def test_actual_response_shape_compatibility_preserves_reasons():
    value=output()
    with pytest.raises(ValueError,match='rationale'):parse_screen(json.dumps(value),POLICY)
    result=parse_screen_v2(json.dumps(value),POLICY)
    assert result['rationale']=='\n'.join(value['rationale'])
    assert result['reported_policy_refs']==value['policy_refs']


@pytest.mark.parametrize('reasons',[None,[],[''],['ok',None],''])
def test_missing_reasons_still_invalid(reasons):
    with pytest.raises(ValueError):parse_screen_v2(json.dumps({**output(),'rationale':reasons}),POLICY)


def test_wrong_policy_and_clause_rejected():
    for refs in ({'id':'wrong','version':'1'},{'id':'test','version':'1','clauses':['invented']}):
        with pytest.raises(ValueError):parse_screen_v2(json.dumps({**output(),'policy_refs':refs}),POLICY)


def test_guarded_service_new_start_is_independent(tmp_path):
    import runpy
    from pathlib import Path

    from co_scientist_next.store import Store
    helpers=runpy.run_path(str(Path(__file__).with_name('test_research_controller.py')))
    with Store(tmp_path/'starts.sqlite') as store:
        controller=helpers['controller'](store)
        old=helpers['start'](controller,key='historical-one')
        controller.restart_only=True
        assert not controller.authorized_run(old)
        new=helpers['start'](controller,key='independent-two')
        assert controller.authorized_run(new)
        count=len(store.tasks(old))
        controller.tick(old)
        assert len(store.tasks(old))==count
        assert helpers['drain'](controller,new)['status']=='completed'
