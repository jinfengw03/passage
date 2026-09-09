import asyncio
import json
from unittest.mock import AsyncMock, patch
import pytest
from app import agent, config, social, store
from tests.test_application import isolated_store, client, call


def test_unavailable_search_does_not_consume_budget():
    run=agent.new_run('测试研究')
    for tool,args in [('search_web',{'query':'test'}),('search_social',{'platform':'xiaohongshu','query':'test'})]:
        with pytest.raises(ValueError, match='未扣除'):
            asyncio.run(agent.dispatch(run,config.DEFAULTS,tool,args))
    assert run['search_count']==0
    offered={t['function']['name'] for t in agent.available_tools(run,config.DEFAULTS)}
    assert 'search_web' not in offered and 'search_social' not in offered


def test_actual_search_failure_counts_as_attempt():
    run=agent.new_run('测试研究')
    with patch.object(agent.providers,'search',AsyncMock(side_effect=ValueError('服务限流'))):
        with pytest.raises(ValueError):
            asyncio.run(agent.dispatch(run,{**config.DEFAULTS,'search_key':'fixture'},'search_web',{'query':'test'}))
    assert run['search_count']==1


def test_bad_report_keeps_partial_result_without_fake_findings():
    run=agent.new_run('测试研究');run['status']='running';run['skills']=['bg-match']
    response={'role':'assistant','tool_calls':[{'id':'bad','function':{'name':'finish_research','arguments':'{"summary":"broken'}}]}
    with patch.object(agent.providers,'complete',AsyncMock(return_value=(response,{}))):
        asyncio.run(agent.run_loop(run,{**config.DEFAULTS,'max_steps':3}))
    assert run['status']=='limited' and run['partial_report']
    assert run['report']['findings']==[]
    assert any('JSON' in e['message'] for e in run['events'])


def test_final_round_uses_compact_evidence_and_real_ids():
    run=agent.new_run('测试研究');run['status']='running';run['skills']=['bg-match'];run['usage']['total_tokens']=config.DEFAULTS['max_total_tokens'] * .85
    item=store.put('evidence',{'title':'fixture','content':'原文' * 5000,'access':'user_import'})
    agent.attach(run,item)
    agent.initialize(run,config.DEFAULTS)
    run['messages'].append({'role':'user','content':'OLD_HISTORY_SENTINEL'})
    async def complete(settings,messages,tools):
        assert {t['function']['name'] for t in tools}=={'load_skill','finish_research'}
        assert 'OLD_HISTORY_SENTINEL' not in json.dumps(messages)
        assert item['id'] in json.dumps(messages)
        return {'role':'assistant','tool_calls':[call('finish_research',{'summary':'资料不足','findings':[],'unknowns':['待核实'],'next_steps':[]})]},{}
    with patch.object(agent.providers,'complete',complete):
        asyncio.run(agent.run_loop(run,config.DEFAULTS))
    assert run['status']=='completed'


def test_limited_resume_is_finish_only(client):
    run=agent.new_run('测试研究');run['status']='limited';agent.checkpoint(run)
    with patch.object(agent,'start') as start:
        assert client.post('/api/runs/'+run['id']+'/resume').status_code==200
    assert store.get(run['id'])['finish_only']
    start.assert_called_once_with(run['id'])
