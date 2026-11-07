import copy
import json

import pytest

from co_scientist_next.background_ops import (
    P04_BOUND_PROMPT_VERSION,
    P04_PROMPT_VERSION,
    parse_output,
)


def fixture():
    view={'id':'view-original','text':'Reported observation. No effect in tested context.','source_ref':'fixture:one','source_version':'1','locator':'body:0','access':'excerpt','representation':'test excerpt'}
    card={k:'Reported observation.' for k in ['supporting_quote','biological_context','intervention_comparator','endpoint','reported_observation','author_interpretation']}
    card.update(negative_findings=[],negative_quotes=[],not_established=[],transfer_assumptions=[])
    return {'source_view':view},{'finding_cards':[card],'targeted_reading_requests':[]}


def test_new_binding_is_program_owned_and_legacy_stays_strict():
    payload,value=fixture()
    result=parse_output('P04',json.dumps(value),payload,version=P04_BOUND_PROMPT_VERSION)
    assert result['finding_cards'][0]['source_view_ref']=='view-original'
    assert result['finding_cards'][0]['supporting_quote']=='Reported observation.'
    with pytest.raises(KeyError):parse_output('P04',json.dumps(value),payload,version=P04_PROMPT_VERSION)


def test_actual_repeated_id_failure_shape_is_rejected_not_repaired():
    payload,value=fixture()
    card=value['finding_cards'][0];card['source_view_ref']='view-original-original'
    for version in [P04_PROMPT_VERSION,P04_BOUND_PROMPT_VERSION]:
        with pytest.raises(ValueError,match='source_view_ref'):
            parse_output('P04',json.dumps(value),payload,version=version)


@pytest.mark.parametrize('negative',[False,True])
def test_no_binding_relaxation_allows_fabricated_quotes(negative):
    payload,value=fixture();value=copy.deepcopy(value)
    if negative:value['finding_cards'][0].update(negative_findings=['No effect'],negative_quotes=['invented quote'])
    else:value['finding_cards'][0]['supporting_quote']='invented quote'
    with pytest.raises(ValueError):parse_output('P04',json.dumps(value),payload,version=P04_BOUND_PROMPT_VERSION)
