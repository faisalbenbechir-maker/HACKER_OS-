import json
import subprocess
import base64
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 8765

def powershell(script):
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True, text=True, timeout=15,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "PowerShell command failed")[-1500:])
    output = result.stdout.strip()
    if not output:
        return {}
    return json.loads(output)

def network_data():
    script = r'''
    $adapters = @(Get-NetIPConfiguration | ForEach-Object {
      [pscustomobject]@{
        name = $_.InterfaceAlias
        status = (Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -ErrorAction SilentlyContinue).Status.ToString()
        ipv4 = ($_.IPv4Address.IPAddress -join ", ")
        gateway = ($_.IPv4DefaultGateway.NextHop -join ", ")
        dns = ($_.DNSServer.ServerAddresses -join ", ")
      }
    })
    $wifi = (Get-NetConnectionProfile -ErrorAction SilentlyContinue | Where-Object {$_.InterfaceAlias -match "Wi-Fi|Wireless"} | Select-Object -First 1 -ExpandProperty Name)
    @{adapters=$adapters;wifi=$wifi} | ConvertTo-Json -Depth 5 -Compress
    '''
    return powershell(script)

def security_data():
    script = r'''
    $fw = @(Get-NetFirewallProfile -ErrorAction SilentlyContinue | ForEach-Object {
      [pscustomobject]@{profile=$_.Name;enabled=[bool]$_.Enabled}
    })
    $d = Get-MpComputerStatus -ErrorAction SilentlyContinue
    $def = $null
    if ($d) {
      $def = @{
        antivirus=[bool]$d.AntivirusEnabled
        realtime=[bool]$d.RealTimeProtectionEnabled
        antispyware=[bool]$d.AntispywareEnabled
      }
    }
    @{firewall=$fw;defender=$def;note=$(if (!$d) {"Defender status unavailable. Another antivirus or Windows configuration may be responsible."} else {""})} | ConvertTo-Json -Depth 5 -Compress
    '''
    return powershell(script)

def system_data():
    script = r'''
    $os = Get-CimInstance Win32_OperatingSystem
    $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
    $disk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'"
    $load = $cpu.LoadPercentage
    @{
      computer=$env:COMPUTERNAME
      windows=$os.Caption
      cpu=$cpu.Name
      cpu_load=$load
      ram_total=[math]::Round($os.TotalVisibleMemorySize/1MB,2)
      ram_free=[math]::Round($os.FreePhysicalMemory/1MB,2)
      disk_total=[math]::Round($disk.Size/1GB,2)
      disk_free=[math]::Round($disk.FreeSpace/1GB,2)
    } | ConvertTo-Json -Depth 4 -Compress
    '''
    return powershell(script)

def connections_data():
    script = r'''
    $items = @(Get-NetTCPConnection -ErrorAction SilentlyContinue | Select-Object -First 50 | ForEach-Object {
      [pscustomobject]@{
        local=("$($_.LocalAddress):$($_.LocalPort)")
        remote=("$($_.RemoteAddress):$($_.RemotePort)")
        state=$_.State.ToString()
      }
    })
    @{connections=$items;count=$items.Count} | ConvertTo-Json -Depth 4 -Compress
    '''
    return powershell(script)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_data(self, data, status=200, content_type="application/json; charset=utf-8"):
        body = data if isinstance(data, bytes) else json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        try:
            if path == "/" or path == "/index.html":
                self.send_data((ROOT / "index.html").read_bytes(), content_type="text/html; charset=utf-8")
            elif path == "/api/ping":
                self.send_data({"ok": True, "engine": "HACKER OS LOCAL ENGINE"})
            elif path == "/api/network":
                self.send_data(network_data())
            elif path == "/api/security":
                self.send_data(security_data())
            elif path == "/api/system":
                self.send_data(system_data())
            elif path == "/api/connections":
                self.send_data(connections_data())
            elif path == "/api/internet":
                try:
                    with socket.create_connection(("1.1.1.1", 443), timeout=4):
                        self.send_data({"connected": True, "message": "A connection to the test endpoint succeeded."})
                except OSError:
                    self.send_data({"connected": False, "message": "The test endpoint could not be reached."})
            else:
                self.send_data({"error": "Not found"}, 404)
        except Exception as exc:
            self.send_data({"error": str(exc)}, 500)

if __name__ == "__main__":
    print("HACKER OS local engine running at http://127.0.0.1:8765")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
