"""Explicit, ten-minute CoreBluetooth setup window using the SDK's pairing v5.

Run from the AgentShell venv. Pair from the Muse phone app; secrets never leave
the encrypted SDK channel or the private host profile.
"""
import argparse,asyncio,json,logging,os,time,urllib.parse,threading
from pathlib import Path
from bless import BlessServer,GATTCharacteristicProperties as Properties,GATTAttributePermissions as Permissions
from musegadget import config,muse_api
from musegadget.identity import load_or_create
from musegadget.pairing import PairingSession
from musegadget.ble_setup import SetupController,ProvisionFailed

SERVICE='7fdd3d1c-38ea-46cf-8b46-314ecf5f240c'
RX='4d593029-28a2-4a6e-a1f0-3c2d5e8f9b01'
TX='d75dc4ca-7b2b-4e9c-8f0a-1d2e3f4a5b6c'
class HostNetwork:
    def is_online(self):return True  # Existing host network; credentials are checked below.
    def current_connection_entry(self):return {'ssid':'AgentShell host network','rssi':-40,'secure':False}

async def pair(state,seconds):
    os.environ['MUSEGADGET_STATE_DIR']=str(state);state.mkdir(parents=True,exist_ok=True,mode=0o700)
    identity=load_or_create(state);token=config.sdk_token(state)
    if not token:raise RuntimeError('Host SDK token missing; copy it into the private host profile.')
    pairing=PairingSession(node_id=identity.node_id,device_id=identity.device_id,mac=identity.mac,firmware_version='0.1.0',sdk_token=token)
    loop=asyncio.get_running_loop();done=asyncio.Event()
    def startup_timeout():
        print(json.dumps({'pairing_open':False,'reason':'macos_bluetooth_not_authorized_or_unavailable'}),flush=True);os._exit(2)
    watchdog=threading.Timer(30,startup_timeout);watchdog.daemon=True;watchdog.start()
    server=BlessServer(name=identity.ble_name,loop=loop)
    watchdog.cancel()
    class Transport:
        def mtu(self):return 23  # Conservative ATT size, valid on every client.
        def send_packets(self,packets):
            async def notify():
                for packet in packets:
                    server.get_characteristic(TX).value=bytearray(packet);until=time.monotonic()+5
                    while not server.update_value(SERVICE,TX):
                        if time.monotonic()>until:raise RuntimeError('ble_notification_timeout')
                        await asyncio.sleep(.01)
                    await asyncio.sleep(.01)
            asyncio.run_coroutine_threadsafe(notify(),loop).result(timeout=30)
        def disconnect(self,delay):
            async def reset():
                await asyncio.sleep(delay);await server.stop();controller.on_disconnect();server.peripheral_manager_delegate.peripheral_manager.removeAllServices();await server.start(prioritize_local_name=False)
            asyncio.run_coroutine_threadsafe(reset(),loop)
    def provision(credentials,commit):
        endpoint=muse_api.api_root(credentials.api_url_v2)
        # A nearby client cannot redirect host credentials to another server.
        if urllib.parse.urlparse(endpoint).hostname!='api.muse.ai' or credentials.noise_host not in ('','hatch.metaaivm.com'):raise ProvisionFailed('auth_failed')
        vms,status=muse_api.fetch_vms_with_status(credentials.access_token,endpoint)
        if status!=200 or not vms:raise ProvisionFailed('auth_failed')
        record={'access_token':credentials.access_token,'refresh_token':credentials.refresh_token,'token_type':'device','username':credentials.username,'api_url_v2':endpoint,'noise_host':credentials.noise_host,'access_token_saved_at':int(time.time())}
        if not commit(lambda:save(record)):raise ProvisionFailed('error_storage')
    def save(record):config.save_json(config.PAIRING_FILE,record,state);return True
    controller=SetupController(pairing=pairing,identity=identity,version='0.1.0',transport=Transport(),network=HostNetwork(),provision=provision,on_complete=lambda:loop.call_soon_threadsafe(done.set))
    await server.add_new_service(SERVICE)
    await server.add_new_characteristic(SERVICE,RX,Properties.write|Properties.write_without_response,None,Permissions.writeable)
    # CoreBluetooth treats a supplied value as a cached, read-only attribute.
    # Notifications need a dynamic characteristic initialized with nil.
    await server.add_new_characteristic(SERVICE,TX,Properties.read|Properties.notify,None,Permissions.readable)
    server.read_request_func=lambda characteristic,**kw:characteristic.value
    server.write_request_func=lambda characteristic,value,**kw:controller.on_write(bytes(value)) if characteristic.uuid.lower()==RX else None
    controller.start()
    try:
        await asyncio.wait_for(server.start(prioritize_local_name=False),timeout=20)
        print(json.dumps({'pairing_open':True,'device_name':identity.ble_name,'expires_in_s':seconds}),flush=True)
        try:await asyncio.wait_for(done.wait(),timeout=seconds)
        except asyncio.TimeoutError:print(json.dumps({'paired':False,'reason':'window_expired'}),flush=True);return False
        await asyncio.sleep(1.5);print(json.dumps({'paired':True,'device_name':identity.ble_name}),flush=True);return True
    finally:controller.stop();await server.stop()
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--state',type=Path,required=True);parser.add_argument('--seconds',type=int,default=600);args=parser.parse_args()
    if not 1<=args.seconds<=600:raise SystemExit('Window must be between 1 and 600 seconds')
    logging.basicConfig(level=logging.ERROR)
    raise SystemExit(0 if asyncio.run(pair(args.state,args.seconds)) else 1)
