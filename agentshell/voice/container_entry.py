"""Dedicated CPU voice worker. No GPU lease, paid API or host credentials."""
import argparse
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import torch

from server import Handler, Voice


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    cfg = json.loads(Path(args.config).read_text())
    if set(cfg) - {'token_file', 'whisper_path', 'piper_path', 'port', 'kokoro'}:
        raise SystemExit('unsupported_container_configuration')
    token = Path(cfg['token_file']).read_text().strip()
    if len(token) < 32 or not cfg.get('kokoro', {}).get('model_dir'):
        raise SystemExit('invalid_container_configuration')
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    server = ThreadingHTTPServer(('0.0.0.0', cfg.get('port', 9450)), Handler)
    server.daemon_threads = True
    server.slots = threading.BoundedSemaphore(1)
    server.token = token
    server.gpu_broker = None
    server.voice = Voice(cfg['whisper_path'], cfg['piper_path'], cfg)
    server.serve_forever()


if __name__ == '__main__':
    main()
