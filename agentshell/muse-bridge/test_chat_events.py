import asyncio,json,tempfile,unittest,uuid
from pathlib import Path
from types import SimpleNamespace
from chat_events import ReplyStream, MAX_LINE, MAX_TEXT
from server import Bridge
from musegadget.identity import Identity
from response_policy import greeting_only

def event(name,mid='reply',parent='note',text='',seq=0,ready=True):
    return {'type':'event','event':name,'seq':seq,'payload':{'message_id':mid,'reply_to_message_id':parent,'text':text,'display_text_ready':ready}}

class ReplyTests(unittest.IsolatedAsyncioTestCase):
    async def test_partial_text_is_correlated_display_only_and_canceled_previews_are_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            b=Bridge(Identity('02:00:00:00:00:01'),Path(d));task=str(uuid.uuid4())
            run={'task_id':task,'status':'running','capability':'conversation','chat_session_id':task,'chat_ack':{'message_id':'note'}};b.runs[task]=run
            previews=[];r=ReplyStream(lambda _:self.fail('partial text cannot be final'),lambda row:previews.append(row))
            r.event(event('delta.text_append',text='Una respuesta parcial',parent=None))
            b.on_preview({**previews[0],'stream_session_id':'wrong'});self.assertNotIn('preview',run)
            b.on_preview({**previews[0],'stream_session_id':task});self.assertEqual(run['preview'],'Una respuesta parcial');self.assertEqual(run['status'],'running');self.assertEqual(b.reply_jobs,{})
            run['status']='canceled';b.on_preview({**previews[0],'text':'Texto tardío','stream_session_id':task});self.assertEqual(run['preview'],'Una respuesta parcial')

    def test_fast_greeting_does_not_match_requests_for_actions_or_answers(self):
        for text in ['Hola Muse, buenos días.','¡Buenas tardes, Sagwa!','Hola.']:
            self.assertTrue(greeting_only(text))
        for text in ['Hola Muse reinicia el servidor','Buenos días, revisa mi agenda','Hola, ¿cómo está Lenovo?','Dime hola','Hola Muse 1','']:
            self.assertFalse(greeting_only(text))

    async def test_fragmented_utf8_and_delta_final_are_coalesced(self):
        rows=[];r=ReplyStream(rows.append)
        raw=(json.dumps(event('delta.message_start',seq=1))+'\n'+json.dumps(event('delta.text_append',text='¡Buenos días!',seq=2),ensure_ascii=False)+'\n'+json.dumps(event('delta.message_done',parent=None,seq=3))+'\n').encode()
        for byte in raw:r.feed(bytes([byte]))
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['text'],'¡Buenos días!');self.assertEqual(rows[0]['parent'],'note')
        r.event(event('delta.text_append',text=' duplicate',seq=2));self.assertEqual(len(rows),1)

    async def test_not_ready_text_is_not_delivered_and_parentless_text_retains_missing_parent(self):
        rows=[];r=ReplyStream(rows.append)
        r.event(event('message.assistant',parent=None,text='Wrong'))
        r.event(event('message.assistant',mid='other',text='Draft',ready=False))
        self.assertEqual(len(rows),1);self.assertIsNone(rows[0]['parent'])

    async def test_invalid_and_oversized_input_and_cache_are_bounded(self):
        rows=[];r=ReplyStream(rows.append)
        r.feed(b'invalid\n');r.event(event('message.assistant',text='a'*(MAX_TEXT+1)))
        self.assertEqual(rows,[])
        for i in range(100):r.event(event('delta.message_start',mid=str(i)))
        self.assertEqual(len(r.messages),64)
        with self.assertRaises(ValueError):r.feed(b'a'*(MAX_LINE+1))

    async def test_reset_and_error_responses_close_subscription(self):
        for kind,value in [('reset',SimpleNamespace(reason='gone')),('response',SimpleNamespace(status=403))]:
            r=ReplyStream(lambda _:None);r.on_frame(SimpleNamespace(kind=kind,value=value))
            with self.assertRaises(ConnectionError):await r.ready
            with self.assertRaises(ConnectionError):await r.done

    async def test_exact_ack_parent_finishes_only_live_conversation_once(self):
        with tempfile.TemporaryDirectory() as d:
            b=Bridge(Identity('02:00:00:00:00:01'),Path(d));task=str(uuid.uuid4())
            run={'task_id':task,'status':'running','capability':'conversation','chat_ack':{'message_id':'note'}};b.runs[task]=run
            b.on_reply({'message_id':'unrelated','parent':'old-note','text':'Wrong'})
            self.assertEqual(b.reply_jobs,{})
            row={'message_id':'reply','parent':'note','text':'Buenos días.'}
            b.on_reply(row);b.on_reply(row);self.assertEqual(len(b.reply_jobs),1)
            await asyncio.gather(*b.reply_jobs.values())
            self.assertEqual(run['status'],'completed');self.assertEqual(run['output'],'Buenos días.')
            b.on_reply(row);self.assertEqual(b.reply_jobs,{})

    async def test_cancellation_and_delegate_preambles_cannot_complete(self):
        with tempfile.TemporaryDirectory() as d:
            b=Bridge(Identity('02:00:00:00:00:01'),Path(d));task=str(uuid.uuid4())
            run={'task_id':task,'status':'running','capability':'conversation','chat_ack':{'message_id':'note'}};b.runs[task]=run
            row={'message_id':'reply','parent':'note','text':'Voy a delegar.'}
            b.on_reply(row);run['command_counts']={'agentshell.agents.submit':1}
            await asyncio.gather(*b.reply_jobs.values());self.assertEqual(run['status'],'running')
            b.on_reply(row);run['status']='canceled'
            await asyncio.gather(*b.reply_jobs.values());self.assertEqual(run['status'],'canceled')
            run.update(status='running',capability='code.change');b.on_reply(row);self.assertEqual(b.reply_jobs,{})

    async def test_parentless_reply_requires_dedicated_task_subscription_and_ack(self):
        with tempfile.TemporaryDirectory() as d:
            b=Bridge(Identity('02:00:00:00:00:01'),Path(d));task=str(uuid.uuid4())
            run={'task_id':task,'status':'running','capability':'conversation','chat_session_id':task};b.runs[task]=run
            row={'message_id':'reply','parent':'','text':'Buenos días.','stream_session_id':task}
            b.on_reply(row);self.assertEqual(b.reply_jobs,{})
            run['chat_ack']={'message_id':'note'}
            b.on_reply({**row,'stream_session_id':'another-chat'});self.assertEqual(b.reply_jobs,{})
            b.on_reply(row);await asyncio.gather(*b.reply_jobs.values())
            self.assertEqual(run['status'],'completed')

    async def test_infrastructure_runs_keep_explicit_gadget_completion_without_text_subscription(self):
        with tempfile.TemporaryDirectory() as d:
            b=Bridge(Identity('02:00:00:00:00:01'),Path(d));task=str(uuid.uuid4())
            class Session:
                registered_at=1
                async def send_chat(self,message,session_id):return {'ok':True,'status':200,'response':{'message_id':'note'}}
                async def subscribe(self,session_id):raise AssertionError('execution must keep gadget return path')
            b._current=Session()
            run=await b.submit({'client_request_id':task,'session_id':str(uuid.uuid4()),'input':'Consulta el host.','capability':'infra.diagnose','target':'mac-mini'})
            self.assertEqual(run['status'],'running')
            b.invoke('agentshell.task.complete',{'task_id':task,'text':'Resultado real.'})
            self.assertEqual(run['status'],'completed')

if __name__=='__main__':unittest.main()
