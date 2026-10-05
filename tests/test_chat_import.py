import sqlite3
import sys
import json
import subprocess
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
import chat_import


def test_echo_continuation_needs_acknowledgement_and_own_checkpoint():
    script = Path(__file__).resolve().parents[1] / "launcher/static/echo.js"
    subprocess.run(["node", "-e", r'''
const fs=require('fs'), vm=require('vm'), assert=require('node:assert/strict');
async function run(mode, continuous) {
  const fields=new Map(), timers=new Map(); let sequence=0, starts=0, results=0;
  const field=id=> {
    if (!fields.has(id)) fields.set(id, {value:'', hidden:false, checked:false, textContent:'',
      events:{}, addEventListener(kind,fn){this.events[kind]=fn;}, setAttribute(){}, replaceChildren(){}, files:[]});
    return fields.get(id);
  };
  let state={memorize_cursor:-1,history_end_index:2,pending_segment_ids:[],stage:'memorize',error:null};
  const ctx={console,URLSearchParams,FormData,Option:function(){},renderMemorize(){},bindSoulCombobox(){},
    document:{getElementById:field},setTimeout(fn,ms){timers.set(++sequence,{fn,ms});return sequence;},
    clearTimeout(id){timers.delete(id);},fetch:async url=>{
      let data;
      if(url==='/souls') data={souls:[]};
      else if(url.startsWith('/echo/status')) data={stored:true,registered:true,running:false,
        label:url.includes('STRASSE')||url.includes('Stra')?'Stra\u00dfe':'Replika',
        conversation_id:'import:dm:test',import_state:structuredClone(state),progress:{}};
      else if(url==='/echo/process') {
        starts++;
        if(mode!=='unchanged') {state.memorize_cursor++; if(state.memorize_cursor===1)state.stage='complete';}
        if(mode==='lost')throw Error('Lost acknowledgement');
        data={status:'accepted',conversation_id:mode==='wrong'?'import:dm:other':'import:dm:test'};
      } else throw Error(url);
      return {ok:true,json:async()=>data};
    }};
  vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
  await new Promise(resolve=>setImmediate(resolve));
  ctx.loadResults=async()=>{results++;};
  vm.runInContext('selection={soul_id:"TestSoul",label:"Replika"};',ctx);
  field('echo-continuous').checked=continuous;
  await ctx.startWork('process');
  assert.equal(starts,1);
  const next=[...timers.values()].find(timer=>timer.ms===0);
  if(mode==='advance'&&continuous) {assert(next);await next.fn();assert.equal(starts,2);assert.equal(results,2);}
  else {assert(!next);assert.equal(results,mode==='advance'?1:0);}
  if(mode!=='advance')assert.equal(field('echo-continuous').checked,false);
  if(mode==='advance'&&!continuous) {
    vm.runInContext('selectedSoul="TestSoul";knownChats=new Set(["Stra\\u00dfe"]);',ctx);
    ctx.resetSelection();
    field('echo-label').value='STRASSE';
    await field('echo-chat-form').events.submit({preventDefault(){}});
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(vm.runInContext('selection.label',ctx),'Stra\u00dfe');
    assert.equal(field('echo-chat-new').hidden,true);
    assert.equal(field('echo-register').hidden,false);
    assert.equal(field('echo-process').disabled,false);
    vm.runInContext('busy=true;',ctx);
    await field('echo-chat-form').events.submit({preventDefault(){}});
    assert.equal(vm.runInContext('busy',ctx),true);
    vm.runInContext('busy=false;',ctx);
    ctx.showPreview({label:'Stra\u00dfe',saved:false,total_messages:1,duplicates:1,notice:'Messages already exist',
      stats:{skipped_non_text:0,skipped_empty:0},history:{count:0},current:{count:0},guidance:{},possible_overlap:false});
    assert.equal(field('echo-counts').textContent,'Messages already exist');
    assert.equal(field('echo-guidance').textContent,'');
    assert.equal(field('echo-confirm').disabled,true);
  }
}
(async()=>{for(const mode of ['lost','wrong','unchanged','advance'])await run(mode,true);await run('advance',false);})()
  .catch(error=>{console.error(error);process.exitCode=1;});
''', str(script)], check=True)


def test_echo_http_upload_reuses_source_and_never_starts_processing(tmp_path, monkeypatch):
    import app
    from fastapi import HTTPException
    from fastapi.testclient import TestClient

    monkeypatch.setattr(app.settings, "apps_root", lambda: tmp_path)
    monkeypatch.setattr(app.services, "read_owner", lambda: "TestOwner")
    monkeypatch.setattr(app.services, "list_souls", lambda: ["TestSoul"])
    created = []
    monkeypatch.setattr(app.services, "resolve_soul",
        lambda name, existing: (created.append((name, existing)) or name))
    calls, refuse, register_fail = [], [False], [False]
    pending_day = ["2025-01-03"]
    competing = [[]]
    def mcp(path, payload=None, *, timeout=2):
        calls.append((path, payload, timeout))
        if path == "/imports/validate":
            if refuse[0]:
                raise HTTPException(status_code=400, detail="Context too large")
            if competing[0]:
                normalized, _, _ = chat_import.normalize_messages(competing[0])
                chat_import.store_upload(chat_import.source_path(tmp_path), user_id="TestOwner", soul_id="TestSoul",
                                         label="Replika", messages=normalized, history_count=len(normalized))
                competing[0] = []
            return {"pending_start_day": pending_day[0], "processed_start_day": "2024-01-01",
                    "processed_end_day": "2025-01-01"}
        assert path == "/imports/register"  # Storage must never Process implicitly.
        assert chat_import.list_chats(chat_import.source_path(tmp_path), user_id="TestOwner", soul_id="TestSoul")
        if register_fail[0]:
            raise HTTPException(status_code=503, detail="Offline")
        return {"ok": True}
    monkeypatch.setattr(app.services, "_mcp_request", mcp)
    client = TestClient(app.app, base_url="http://127.0.0.1")
    assert client.post("/echo/soul", data={"soul_id": "TestNewSoul"}).json() == {"soul_id": "TestNewSoul"}
    assert created == [("TestNewSoul", False)]
    assert not chat_import.source_path(tmp_path).exists()
    raw = [{"id": str(i), "meta": {"nature": nature, "timestamp": day}, "content": {"text": "fictional"}}
           for i, (nature, day) in enumerate((("Customer", "2025-01-01"), ("Robot", "2025-01-03")))]
    fields = {"soul_id": "TestSoul", "label": "Replika", "all_history": "false", "history_count": "1",
              "preview_pending_start_day": "2025-01-03"}
    def upload(route, rows=raw, **extra):
        return client.post(route, data={**fields, **extra}, files={"file": ("chat.json", json.dumps(rows), "application/json")})
    preview = upload("/echo/preview")
    assert preview.status_code == 200 and preview.json()["possible_overlap"]
    assert preview.json()["history"]["count"] == preview.json()["current"]["count"] == 1
    assert not chat_import.source_path(tmp_path).exists()
    assert calls[-1][2] == 60 and calls[-1][1]["current_messages"][0]["role"] == "assistant"
    pending_day[0] = "2025-01-04"
    changed = upload("/echo/confirm", confirmed_new="true")
    assert changed.status_code == 409 and "Preview again" in changed.json()["detail"]
    assert not chat_import.source_path(tmp_path).exists()
    pending_day[0] = "2025-01-03"
    assert upload("/echo/confirm").status_code == 409
    refuse[0] = True
    assert upload("/echo/confirm", confirmed_new="true").status_code == 400
    assert not chat_import.source_path(tmp_path).exists()
    refuse[0] = False
    saved = upload("/echo/confirm", confirmed_new="true")
    assert saved.status_code == 200 and saved.json()["saved"]
    before = len(calls)
    replay = upload("/echo/confirm", all_history="true")
    assert replay.json()["notice"] == "Messages already exist" and len(calls) == before
    db = chat_import.source_path(tmp_path)
    with sqlite3.connect(db) as con:
        rows = con.execute("SELECT speaker, historical, raw_json FROM imported_messages ORDER BY position").fetchall()
        assert rows[0][:2] == ("TestOwner", 1) and rows[1][1] == 0
        assert json.loads(rows[0][2]) == raw[0]
    assert client.get("/echo/chats", params={"soul_id": "TestSoul"}).json()["chats"][0]["label"] == "Replika"
    assert client.get("/echo/chats", params={"soul_id": "OtherSoul"}).status_code == 404
    register_fail[0] = True
    more = [*raw, {"id": "2", "role": "user", "timestamp": "2025-01-04", "content": "new fictional row"}]
    assert upload("/echo/preview", more, all_history="true").json()["possible_overlap"] is False
    failure = upload("/echo/confirm", more, all_history="true")
    assert failure.status_code == 503 and "Source saved" in failure.json()["detail"]
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM imported_messages").fetchone()[0] == 3
    register_fail[0] = False
    assert client.post("/echo/register", data=fields).status_code == 200
    assert client.post("/echo/anything", data=fields).status_code == 404
    addition = {"id": "competing", "role": "user", "timestamp": "2025-01-05", "content": "fictional concurrent row"}
    competing[0] = [addition]
    before = len(calls)
    race = upload("/echo/confirm", [*more, addition], all_history="true")
    assert race.status_code == 200 and race.json()["notice"] == "Messages already exist"
    assert [call[0] for call in calls[before:]] == ["/imports/validate"]
    html = client.get("/echo").text
    assert 'src="/static/echo-logo.svg"' in html and 'id="echo-continuous" type="checkbox">' in html


def test_source_replay_split_and_atomic_conflict(tmp_path):
    db = tmp_path / "chats.db"
    scope = {"user_id": "TestOwner", "soul_id": "TestSoul", "label": "Replika"}
    raw = [{"id": str(i), "role": "user", "name": "TestSpeaker", "content": f"message {i}",
            "timestamp": f"2025-01-0{i + 1}"} for i in range(5)]
    messages, title, _ = chat_import.normalize_messages(raw)
    preview = chat_import.prepare_upload(db, **scope, messages=messages, history_count=2)
    assert len(preview["messages"]) == 5 and not db.exists()
    first = chat_import.store_upload(db, **scope, messages=messages, history_count=2, title=title)
    replay = chat_import.store_upload(db, **scope, messages=messages, history_count=5)
    assert replay["chat_id"] == first["chat_id"] and replay["messages"] == []
    older, _, _ = chat_import.normalize_messages([
        {"role": "assistant", "name": "TestCompanion", "content": "older history", "timestamp": "2024-01-01"}])
    added = chat_import.store_upload(db, **scope, messages=older, history_count=1)
    assert added["messages"][0]["position"] == 5 and added["history_end_index"] == 6
    conflict, _, _ = chat_import.normalize_messages([
        {"role": "user", "content": "new", "timestamp": "2026-01-01"},
        {"role": "assistant", "name": "TestCompanion", "content": "changed", "timestamp": "2024-01-01"}])
    with pytest.raises(ValueError, match="Conflicting"):
        chat_import.store_upload(db, **scope, messages=conflict, history_count=2)
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT position, historical FROM imported_messages ORDER BY position").fetchall() == [
            (0, 1), (1, 1), (2, 0), (3, 0), (4, 0), (5, 1)]
        assert con.execute("SELECT COUNT(*) FROM imported_chats").fetchone()[0] == 1
    assert chat_import.store_upload(db, **scope, messages=older, history_count=0)["duplicates"] == 1
    other = chat_import.store_upload(db, **{**scope, "soul_id": "OtherSoul"}, messages=messages, history_count=5)
    assert other["chat_id"] != first["chat_id"]


def test_chat_label_casefold_and_one_app_per_soul(tmp_path, monkeypatch):
    db = tmp_path / "imports.db"
    rows, _, _ = chat_import.normalize_messages([{"id": "one", "role": "user", "content": "fictional",
                                                 "timestamp": "2025-01-01"}])
    scope = {"user_id": "TestOwner", "soul_id": "TestSoul"}
    first = chat_import.store_upload(db, **scope, label="replika", messages=rows, history_count=1)
    replay = chat_import.store_upload(db, **scope, label="REPLIKA", messages=rows, history_count=0)
    assert replay["chat_id"] == first["chat_id"] and replay["label"] == "Replika" and not replay["messages"]
    with pytest.raises(ValueError, match="one chat app"):
        chat_import.store_upload(db, **scope, label="Nomi", messages=rows, history_count=1)
    unicode_scope = {**scope, "soul_id": "UnicodeSoul"}
    original = chat_import.store_upload(db, **unicode_scope, label="Stra\u00dfe", messages=rows, history_count=1)
    assert chat_import.prepare_upload(db, **unicode_scope, label="STRASSE", messages=rows,
                                     history_count=0)["chat_id"] == original["chat_id"]
    dotless = {**scope, "soul_id": "DotlessSoul"}
    first = chat_import.store_upload(db, **dotless, label="\u0131chat", messages=rows, history_count=1)
    assert first["label"] == "\u0131chat"
    assert chat_import.prepare_upload(db, **dotless, label="\u0131chat", messages=rows,
                                     history_count=0)["duplicates"] == 1
    import app
    from fastapi.testclient import TestClient
    monkeypatch.setattr(app, "_echo_scope", lambda sid, label="": (db, {**scope, "soul_id": sid, "label": label}))
    monkeypatch.setattr(app.services, "_mcp_request", lambda *_a, **_kw: {"import_state": {}})
    monkeypatch.setattr(app.services, "memorize_pending", lambda *_a: {})
    status = TestClient(app.app, base_url="http://127.0.0.1").get(
        "/echo/status", params={"soul_id": "UnicodeSoul", "label": "STRASSE"}).json()
    assert status["stored"] and status["registered"] and status["label"] == original["label"]


def test_conversion_date_identity_and_metadata(tmp_path):
    raw = [{"id": "a", "meta": {"nature": "Customer", "timestamp": "2025-01-01T00:30:00+02:00"},
            "name": "TestSpeaker", "content": {"type": "text", "text": "hello"}},
           {"id": "b", "meta": {"nature": "Robot", "timestamp": "2025-01-01T00:31:00+02:00"},
            "content": {"type": "text", "text": "hi"}}]
    messages, _, _ = chat_import.normalize_messages(raw)
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["timestamp"] == "2024-12-31T22:30:00+00:00"
    assert messages[0]["source_day"] == "2025-01-01"
    assert messages[0]["metadata"] == raw[0] and messages[1]["name"] == ""
    native_preview = chat_import.prepare_upload(tmp_path / "native.db", user_id="TestOwner", soul_id="TestSoul",
                                               label="Replika", messages=messages, history_count=0)
    assert native_preview["messages"][0]["name"] == "TestOwner"
    assert native_preview["messages"][0]["metadata"] == raw[0]
    scope = {"user_id": "TestOwner", "soul_id": "TestSoul", "label": "Nomi"}
    db = tmp_path / "chats.db"
    no_ids, _, _ = chat_import.normalize_messages([{"role": "user", "content": "hi", "timestamp": "2025-01-01T01:00:00+01:00"}])
    chat_import.store_upload(db, **scope, messages=no_ids, history_count=0)
    replay, _, _ = chat_import.normalize_messages([{"role": "user", "content": "hi", "timestamp": "2025-01-01T00:00:00Z"}])
    assert chat_import.store_upload(db, **scope, messages=replay, history_count=1)["duplicates"] == 1
    day_only, _, _ = chat_import.normalize_messages([{"role": "user", "content": "hi", "timestamp": "2025-01-01"}])
    assert day_only[0]["timestamp"] == replay[0]["timestamp"]
    assert chat_import.store_upload(db, **scope, messages=day_only, history_count=1)["duplicates"] == 1
    with pytest.raises(ValueError, match="Ambiguous"):
        chat_import.store_upload(db, **scope, messages=replay * 2, history_count=1)
    dated, _, _ = chat_import.normalize_messages([{"id": str(i), "role": "user", "content": "same",
                                                 "timestamp": "2025-02-01"} for i in range(2)])
    chat_import.store_upload(db, **scope, messages=dated, history_count=2)
    ambiguous, _, _ = chat_import.normalize_messages([{"role": "user", "content": "same", "timestamp": "2025-02-01"}])
    with pytest.raises(ValueError, match="ambiguous"):
        chat_import.store_upload(db, **scope, messages=ambiguous, history_count=0)
    aliases, _, _ = chat_import.normalize_messages([
        {"id": primary, "source_message_id": str(i), "role": "user", "content": f"alias {i}",
         "timestamp": "2025-03-01"} for i, primary in enumerate((None, "", "  ", 0))])
    assert [m["source_message_id"] for m in aliases] == ["0", "1", "2", "0"]
    distinct = aliases[:3]
    added = chat_import.store_upload(db, **{**scope, "label": "Kindroid", "user_id": " TestOwner ", "soul_id": " OtherSoul "},
                                     messages=distinct, history_count=3)
    assert added["user_id"] == "TestOwner" and added["soul_id"] == "OtherSoul"
    assert chat_import.store_upload(db, **{**scope, "label": "Kindroid", "soul_id": "OtherSoul"}, messages=distinct, history_count=0)["duplicates"] == 3
    with pytest.raises(ValueError, match="Conflicting messages for ID"):
        chat_import.store_upload(db, **scope, messages=[aliases[0], aliases[3]], history_count=2)


@pytest.mark.parametrize("message", [
    {"role": "user", "content": "hello"},
    {"role": "user", "content": "hello", "timestamp": "2025-01-01T12:00:00"},
    {"role": "user", "content": "hello", "timestamp": "2025-02-30"},
    {"role": "system", "content": "hello", "timestamp": "2025-01-01"},
    {"content": "hello", "meta": {"timestamp": "2025-01-01"}},
])
def test_invalid_input_is_refused(message):
    with pytest.raises(ValueError):
        chat_import.normalize_messages([message])
