import base64
import io
import json
from unittest.mock import AsyncMock

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from app import providers, store, config
from tests.test_application import isolated_store, client


def pdf(text='Example University Computer Science GPA 3.8/4.0 Research assistant 2024'):
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(('BT /F1 12 Tf 50 700 Td (' + text + ') Tj ET').encode())
    page[NameObject('/Contents')] = writer._add_object(stream)
    out = io.BytesIO(); writer.write(out)
    return base64.b64encode(out.getvalue()).decode()


def test_local_extraction_does_not_persist_or_call_model(client, monkeypatch):
    model = AsyncMock(); monkeypatch.setattr(providers, 'complete', model)
    before = store.profile()
    response = client.post('/api/profile/resume/extract', json={'pdf_base64': pdf()})
    assert response.status_code == 200
    assert 'GPA 3.8/4.0' in response.json()['text']
    assert response.json()['pages'] == 1
    assert store.profile() == before and not store.all_of('evidence')
    model.assert_not_called()


def test_bad_and_scanned_pdf(client):
    for encoded in ('broken!', base64.b64encode(b'not a pdf').decode(), pdf('')):
        assert client.post('/api/profile/resume/extract', json={'pdf_base64': encoded}).status_code == 400


def test_model_missing(client):
    assert client.post('/api/profile/resume/analyze', json={'text':'Example University Computer Science GPA 3.8/4.0'}).status_code == 400


def test_grounded_fields_and_no_overwrite(client, monkeypatch):
    config.save({'model':'fixture'})
    client.put('/api/profile', json={'university':'Existing university', 'targets':'Keep target'})
    prior = store.profile()
    mock = AsyncMock(return_value=({'content':json.dumps({'fields':{
        'university':{'value':'Example University','evidence':'Example University'},
        'gpa':{'value':'3.8/4.0','evidence':'GPA 3.8/4.0'},
        'budget':{'value':'100K','evidence':'invented'},
        'display_name':{'value':'Private name','evidence':'Example University'},
        'major':{'value':['bad type'],'evidence':'Computer Science'}}})}, {}))
    monkeypatch.setattr(providers, 'complete', mock)
    response=client.post('/api/profile/resume/analyze', json={'text':'Example University Computer Science GPA 3.8/4.0'})
    assert response.status_code == 200
    assert set(response.json()['fields']) == {'university','gpa'}
    assert response.json()['warnings']
    assert store.profile() == prior
    assert 'Keep target' not in str(mock.call_args)


def test_malformed_model_response(client, monkeypatch):
    config.save({'model':'fixture'})
    monkeypatch.setattr(providers,'complete',AsyncMock(return_value=({'content':'not json'},{})))
    assert client.post('/api/profile/resume/analyze',json={'text':'Example University Computer Science GPA 3.8/4.0'}).status_code == 400
