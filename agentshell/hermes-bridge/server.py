"""Dedicated Hermes API process: existing provider, only policy-backed MCP tools.

Does not modify the user's Hermes installation/configuration or running gateway.
Native Hermes tools and provider fallbacks are excluded in this process.
"""
import argparse, asyncio, hashlib, json, logging, os, re, signal, ssl, sys, uuid
from pathlib import Path
import urllib.request

OPS = ['host_status', 'docker_status', 'docker_logs', 'backup_status', 'git_status',
       'git_worktree', 'git_commit', 'git_test', 'artifact_build', 'docker_restart', 'deploy_register', 'deploy_release']

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    settings = json.loads(Path(parser.parse_args().config).read_text())
    sys.path.insert(0, settings['hermes_path'])
    # Load existing authentication into this dedicated process only.
    from dotenv import load_dotenv
    load_dotenv(Path(os.environ.get('HERMES_HOME', str(Path.home()/'.hermes')))/'.env', override=False)
    logging.basicConfig(level=logging.ERROR)
    from aiohttp import web
    from gateway.config import PlatformConfig
    from gateway.platforms.api_server import APIServerAdapter
    from gateway.run import GatewayRunner
    from hermes_cli import tools_config
    import toolsets
    from tools.registry import registry
    from agent import auxiliary_client
    def no_auxiliary(*args, **kwargs):
        raise RuntimeError('Auxiliary providers disabled by AgentShell policy')
    auxiliary_client.get_text_auxiliary_client = no_auxiliary
    auxiliary_client.get_async_text_auxiliary_client = no_auxiliary
    auxiliary_client.resolve_vision_provider_client = no_auxiliary

    context = ssl.create_default_context(cafile=settings['ca_file'])
    token = Path(settings['tools_token_file']).read_text().strip()
    def action(args, **kwargs):
        # Identity comes from Hermes' execution context, never model arguments.
        task = str(uuid.UUID(str(kwargs.get('task_id', ''))))
        operation = args.get('operation')
        if operation not in OPS:
            return json.dumps({'error': 'unsupported'})
        request = {'jsonrpc':'2.0', 'id':str(uuid.uuid4()), 'method':'tools/call',
                   'params':{'name':operation, 'arguments':{'task_id':task,
                   'node':args.get('node', ''), 'resource':args.get('resource', ''),
                   'params':args.get('params', {})}}}
        try:
            req = urllib.request.Request(settings['mcp_url'], data=json.dumps(request).encode(),
                  headers={'Authorization':'Bearer '+token, 'Content-Type':'application/json',
                           'Accept':'application/json, text/event-stream',
                           'MCP-Protocol-Version':'2026-07-28'})
            with urllib.request.urlopen(req, context=context, timeout=30) as response:
                result = json.loads(response.read(32769))
            return json.dumps(result.get('result', {'error':'action_failed'}), ensure_ascii=False)
        except Exception:
            return json.dumps({'error':'action_unavailable'})
    schema = {'name':'agentshell_action',
              'description':'Consulta o actúa sobre infraestructura mediante permisos del servidor. host_status admite resource vacío. Los cambios requieren autorización; nunca repitas una operación de resultado incierto.',
              'parameters':{'type':'object','additionalProperties':False,
                            'properties':{'operation':{'type':'string','enum':OPS},
                            'node':{'type':'string'},'resource':{'type':'string'},
                            'params':{'type':'object'}},'required':['operation','node','resource']}}
    registry.register(name='agentshell_action', toolset='agentshell', schema=schema,
                      handler=action, check_fn=lambda:True)
    toolsets.TOOLSETS['agentshell']={'description':'AgentShell infrastructure policy',
                                  'tools':['agentshell_action'], 'includes':[]}
    original = tools_config._get_platform_tools
    tools_config._get_platform_tools = lambda config, platform, *a, **kw: {'agentshell'} if platform=='api_server' else original(config, platform, *a, **kw)
    GatewayRunner._load_fallback_model = staticmethod(lambda:None)

    class RestrictedAPI(APIServerAdapter):
        def __init__(self, config):
            super().__init__(config)
            self.records = Path(settings['state_dir'])/'requests'
            self.records.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.submission_lock = asyncio.Lock()
            self.provider_unavailable = False

        def _create_agent(self, *args, **kwargs):
            agent = super()._create_agent(*args, **kwargs)
            names = {tool['function']['name'] for tool in (agent.tools or [])}
            if names != {'agentshell_action'}:
                raise RuntimeError('Unsafe Hermes toolset rejected')
            return agent

        async def _handle_get_run(self, request):
            response = await super()._handle_get_run(request)
            if response.status == 200:
                status = json.loads(response.body)
                error = str(status.get('error', ''))
                if any(part in error.lower() for part in ['401', 'authentication', 'user not found']):
                    self.provider_unavailable = True
                    status.update(status='failed', error='OpenRouter authentication unavailable', output='OpenRouter rechazó la credencial configurada en Lenovo.')
                    return web.json_response(status)
            return response

        async def _handle_capabilities(self, request):
            response = await super()._handle_capabilities(request)
            if response.status == 200 and not getattr(self,'authentication_checked',False):
                self.authentication_checked=True
                def check():
                    route=settings['approved_route']
                    secret=route.get('api_key') or os.environ.get('OPENROUTER_API_KEY','')
                    req=urllib.request.Request('https://openrouter.ai/api/v1/auth/key',headers={'Authorization':'Bearer '+secret})
                    try:
                        with urllib.request.urlopen(req,timeout=10) as result:return result.status==200
                    except Exception:return False
                self.provider_unavailable=not await asyncio.to_thread(check)
            if response.status == 200 and self.provider_unavailable:
                capabilities = json.loads(response.body)
                capabilities['features']['run_submission'] = False
                capabilities['reason'] = 'OpenRouter authentication unavailable'
                return web.json_response(capabilities)
            return response

        def _make_profile_prefix_middleware(self):
            @web.middleware
            async def restrict(request, handler):
                if not re.fullmatch(r'/health|/v1/capabilities|/v1/runs(?:/run_[a-f0-9]+(?:/(?:stop|approval|events))?)?', request.path):
                    return web.json_response({'error':'unsupported'}, status=404)
                if request.content_length and request.content_length>32768:
                    return web.json_response({'error':'message_too_large'}, status=413)
                return await handler(request)
            return restrict

        async def _handle_runs(self, request):
            auth = self._check_auth(request)
            if auth is not None:
                return auth
            if self.provider_unavailable:
                return web.json_response({'error':'provider_authentication_unavailable'},status=503)
            body = await request.json()
            try:
                task = str(uuid.UUID(body.get('client_request_id', '')))
                if body.get('session_id') != task or body.get('model') != 'agentshell-hermes':
                    raise ValueError()
            except (ValueError, TypeError):
                return web.json_response({'error':'invalid_task'}, status=400)
            # The approved provider is locked; per-request provider/model overrides
            # and remembered session model choices cannot select another API.
            allowed = {'input','session_id','client_request_id','model','instructions'}
            if set(body)-allowed:
                return web.json_response({'error':'unsupported_override'}, status=400)
            digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
            record = self.records/(task+'.json')
            async with self.submission_lock:
                if record.exists():
                    prior = json.loads(record.read_text())
                    if prior['digest'] != digest:
                        return web.json_response({'error':'duplicate_mismatch'}, status=409)
                    if not prior.get('reply'):
                        return web.json_response({'error':'uncertain_submission'}, status=409)
                    return web.json_response(prior['reply'], status=202)
                def persist(value):
                    temporary=record.with_suffix('.tmp')
                    with temporary.open('w') as f:
                        os.chmod(temporary, 0o600)
                        json.dump(value,f); f.flush(); os.fsync(f.fileno())
                    temporary.replace(record)
                    descriptor=os.open(self.records,os.O_RDONLY)
                    try: os.fsync(descriptor)
                    finally: os.close(descriptor)
                persist({'digest':digest})
                response = await super()._handle_runs(request)
                if response.status == 202:
                    persist({'digest':digest,'reply':json.loads(response.body)})
                return response

    # Settings contain the approved model/provider names, never API credentials.
    config = PlatformConfig(enabled=True, extra={'host':'127.0.0.1','port':settings.get('port',9453),
             'key':Path(settings['api_token_file']).read_text().strip(),
             'model_routes':{'agentshell-hermes':settings['approved_route']},
             'max_concurrent_runs':2})
    async def serve():
        api = RestrictedAPI(config)
        if not await api.connect():
            raise RuntimeError('Hermes API startup failed')
        stopped=asyncio.Event()
        loop=asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stopped.set)
        await stopped.wait()
        await api.disconnect()
    asyncio.run(serve())

if __name__=='__main__':
    main()
