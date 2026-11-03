#!/usr/bin/env python3
"""Create a private, standalone dashboard config from the measured launch config."""
import argparse
import json
import os
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--launch-config', required=True, help='existing trusted Strata run config to adapt')
p.add_argument('--output', required=True)
p.add_argument('--engine', default='/root/.local/share/strata/components/engine/0.1.55-linux-x86_64-cuda-cuda12/strata')
a = p.parse_args()
c = json.loads(Path(a.launch_config).read_text())
c.update(exe=a.engine, host='127.0.0.1', port=18080, api_key='', open_browser=False)
c['lib_dirs'] = [str(Path(a.engine).parent), *c.get('lib_dirs', [])]
c['log'] = str(Path(a.output).resolve().parent / 'engine.log')
c['shared_defaults'] = {'max_tokens':65536, 'temperature':0.7, 'reasoning_effort':'none'}
c['sampling'] = {**c.get('sampling', {}), 'temperature':0.7}
c['env'] = {**c.get('env', {}), 'STRATA_SM70_TABLE':'1'}
# Never propagate unrelated hooks, network trust, or secrets into a no-key service.
for key in ('before_load', 'mcp', 'trusted_origins', 'cors_origins', 'allowed_hosts'):
    c.pop(key, None)
output=Path(a.output); output.parent.mkdir(parents=True, exist_ok=True)
if output.exists():
    raise SystemExit('Output already exists; refusing to overwrite dashboard settings')
fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as f:json.dump(c,f,indent=2)
print('Dashboard config prepared; no API key included')
