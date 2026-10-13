"""Bounded NDJSON reply subscription over the SDK's existing Noise transport.

Uses the same /chat/subscribe endpoint as the original CoreS3 firmware. An
HTTP acknowledgment is never treated as an answer. The bridge correlates final
assistant text using the posted message or a dedicated task chat subscription.
"""
import asyncio
import json
import uuid
from collections import OrderedDict
from musegadget.link_client import LinkSession, APP_ID
from musegadget.noise import Header

MAX_LINE = 65536
MAX_TEXT = 24000

class ReplyStream:
    def __init__(self, callback, on_preview=None):
        loop = asyncio.get_running_loop()
        self.done = loop.create_future()
        self.ready = loop.create_future()
        # The SDK consumes done on session shutdown; avoid unobserved exceptions.
        self.done.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
        self.ready.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
        self.callback = callback
        self.on_preview=on_preview
        self.buffer = bytearray()
        self.messages = OrderedDict()
        self.last_sequence = 0
        self.event_counts={}
        self.http_status=None

    def on_frame(self, frame):
        if self.done.done():
            return
        if frame.kind == 'reset':
            self.close(ConnectionError('reply_stream_reset'));return
        if frame.kind == 'response':
            self.http_status=frame.value.status
            if frame.value.status != 200:
                self.close(ConnectionError('reply_stream_rejected'));return
            if not self.ready.done():self.ready.set_result(True)
            data, ended = frame.value.body, frame.value.end_body
        else:
            data, ended = frame.value.data, frame.value.end_body
        try:self.feed(data)
        except ValueError:
            self.close(ValueError('reply_stream_too_large'));return
        if ended:self.close(ConnectionError('reply_stream_ended'))

    def close(self, error):
        self.buffer.clear();self.messages.clear()
        if not self.ready.done():self.ready.set_exception(error)
        if not self.done.done():self.done.set_exception(error)

    def feed(self, data):
        # Bound the incomplete line, even if a body chunk contains many lines.
        for part in data.splitlines(keepends=True):
            self.buffer.extend(part)
            if len(self.buffer)>MAX_LINE:raise ValueError('line_too_large')
            if not self.buffer.endswith(b'\n'):continue
            raw=bytes(self.buffer);self.buffer.clear()
            try:event=json.loads(raw)
            except (ValueError,UnicodeError):continue
            self.event(event)

    def event(self, event):
        if not isinstance(event,dict) or event.get('type')!='event':return
        seq=event.get('seq')
        if isinstance(seq,int) and seq>0:
            if seq<=self.last_sequence:return
            self.last_sequence=seq
        name=event.get('event_name',event.get('event'))
        if isinstance(name,str) and len(name)<64 and (name in self.event_counts or len(self.event_counts)<32):self.event_counts[name]=self.event_counts.get(name,0)+1
        if name not in ('message.assistant','delta.message_start','delta.text_append','delta.message_done'):return
        p=event.get('payload',event)
        if not isinstance(p,dict):return
        mid=p.get('message_id',p.get('id'));parent=p.get('reply_to_message_id',p.get('parent_message_id'))
        if not isinstance(mid,str) or not mid or len(mid)>256:return
        if parent is not None and (not isinstance(parent,str) or len(parent)>256):return
        text=next((p[k] for k in ('display_text','content','text') if isinstance(p.get(k),str)), '')
        old=self.messages.get(mid)
        if old and parent and old.get('parent') and old['parent']!=parent:return
        row=old or {'message_id':mid,'parent':parent,'text':'','final':False,'overflow':False}
        if parent:row['parent']=parent
        if name=='delta.text_append' and not row['final']:row['text']+=text
        elif name in ('message.assistant','delta.message_done'):
            if text:row['text']=text
            row['final']=p.get('display_text_ready',True) is True
        if len(row['text'].encode())>MAX_TEXT:
            row['text']='';row['overflow']=True
        self.messages[mid]=row;self.messages.move_to_end(mid)
        while len(self.messages)>64:self.messages.popitem(last=False)
        if self.on_preview and row['text'].strip() and not row['overflow']:
            self.on_preview(dict(row))
        if row['final'] and row['text'].strip() and not row['overflow']:
            self.callback(dict(row))

class ChatSession(LinkSession):
    def __init__(self, *args, on_reply, on_preview=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.on_reply=on_reply;self.on_preview=on_preview;self.subscriptions={};self.subscription_lock=asyncio.Lock()

    async def subscribe(self, session_id):
        key=session_id
        async with self.subscription_lock:
            existing=self.subscriptions.get(key)
            if existing and not existing[1].done.done():return existing[1]
            if existing:self._requests.pop(existing[0],None);self.subscriptions.pop(key,None)
            if len(self.subscriptions)>=8:raise ValueError('reply_subscription_limit')
            body=json.dumps({'session_id':session_id}).encode()
            headers=[Header('Content-Type','application/json'),Header('Accept','application/x-ndjson'),Header('x-app-id',APP_ID),Header('x-request-id',str(uuid.uuid4()))]
            encrypted=self._transport.encrypt_http_request('POST','/chat/subscribe',body,headers=headers)
            reader=ReplyStream(lambda row:self.on_reply({**row,'stream_session_id':session_id}),lambda row:self.on_preview({**row,'stream_session_id':session_id}) if self.on_preview else None)
            self._requests[encrypted.stream_id]=reader
            self.subscriptions[key]=(encrypted.stream_id,reader)
            try:
                await self._send_frames(encrypted.frames)
                # Muse may delay subscription headers until its first event.
                # Queue the subscription before posting; waiting for headers
                # here would deadlock an otherwise idle chat.
            except BaseException:
                self._requests.pop(encrypted.stream_id,None);self.subscriptions.pop(key,None)
                if not reader.ready.done():reader.ready.cancel()
                reader.close(ConnectionError('reply_subscription_failed'));raise
            return reader

    async def unsubscribe(self, session_id):
        async with self.subscription_lock:
            existing=self.subscriptions.pop(session_id,None)
            if not existing:return
            stream,reader=existing;self._requests.pop(stream,None)
            reader.close(ConnectionError('reply_subscription_closed'))
            await self._send_frames(self._transport.encrypt_reset(stream))

    def reply_health(self):
        return [{'http_status':r.http_status,'headers_received':r.ready.done() and not r.ready.cancelled() and r.ready.exception() is None,'closed':r.done.done(),'events':r.event_counts,'messages':[{'message_id':m['message_id'],'parent':m['parent'],'final':m['final'],'text_bytes':len(m['text'].encode())} for m in list(r.messages.values())[-8:]]} for _,r in self.subscriptions.values()]
