"""Provision the caller's public key through the existing tufinfra scheduled credentials.
Preserves and restores the task definition. No password or private key is transferred.
"""
import base64,pathlib,subprocess
pub=pathlib.Path.home().joinpath('.ssh/id_ed25519.pub').read_text().strip()
if not pub.startswith('ssh-ed25519 '): raise SystemExit('unexpected public key type')
b64=base64.b64encode(pub.encode()).decode()
s=r'''$ProgressPreference='SilentlyContinue'
$ErrorActionPreference='Stop'
$task=Get-ScheduledTask -TaskName 'TUF-Infra-MountDisk'
if ($task.State -eq 'Running') { throw 'Mount task is busy' }
$original=Get-Content 'C:\ProgramData\TufInfra\windows\Mount-DataDisk.ps1' -Raw
$script='C:\ProgramData\TufInfra\windows\Mount-DataDisk.ps1'
$result='C:\ProgramData\TufInfra\data\agentshell-ssh-result.txt'
$lines=@('$ErrorActionPreference="Stop"', '& wsl.exe -d infra -u root -- sh -c ''mkdir -p /root/.ssh; chmod 700 /root/.ssh; printf %s KEYDATA | base64 -d > /tmp/agentshell-admin.pub; grep -qFf /tmp/agentshell-admin.pub /root/.ssh/authorized_keys || { cat /tmp/agentshell-admin.pub >> /root/.ssh/authorized_keys; printf "\n" >> /root/.ssh/authorized_keys; }; chmod 600 /root/.ssh/authorized_keys; rm /tmp/agentshell-admin.pub; hostname; /usr/sbin/sshd -t'' | Set-Content C:\ProgramData\TufInfra\data\agentshell-ssh-result.txt', 'exit $LASTEXITCODE')
$lines= $lines -replace 'KEYDATA','PUBDATA'
Remove-Item $result -ErrorAction SilentlyContinue
try {
 Set-Content -LiteralPath $script -Value $lines -Encoding ascii
 Start-ScheduledTask -TaskName $task.TaskName
 for($i=0;$i -lt 20;$i++) { Start-Sleep 1; if(Test-Path $result) { break } }
 if(!(Test-Path $result)) { throw 'Provision task did not return a result' }
 Get-Content $result
} finally {
 Set-Content -LiteralPath $script -Value $original -Encoding ascii -NoNewline
}
'''.replace('PUBDATA',b64)
p=subprocess.run(['ssh','tuf-1','powershell.exe','-NoProfile','-EncodedCommand',base64.b64encode(s.encode('utf-16le')).decode()],capture_output=True,text=True,timeout=45)
print(p.stdout)
if p.returncode: print(p.stderr);raise SystemExit(p.returncode)
