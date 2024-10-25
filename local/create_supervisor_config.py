import os

# Define the variables
default_pwd = os.getcwd()
default_outdir = os.path.join(default_pwd, "supervisor")
pwd = input(f"Please enter the directory path (default: {default_pwd}): ") or default_pwd
port = input("Please enter the port number of the master server (e.g., 9988): ")
outdir = input(f"Please enter the output directory: (default: {default_outdir})") or default_outdir

# Define the content of the file
config_content = f"""
[supervisord]
nodaemon=false
user=teinhonglo
logfile_maxbytes=50MB
logfile={pwd}/supervisor/supervisord.log
pidfile={pwd}/supervisor/supervisord.pid
minfds=65535
minprocs=65535

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

[supervisorctl]
serverurl=unix://{pwd}/supervisor/supervisor.sock ; use a unix:// URL  for a unix socket

[unix_http_server]
file={pwd}/supervisor/supervisor.sock  ; (the path to the socket file)
chmod=0700                       ; socket file mode (default 0700)

[group:capt]
programs=worker,master

; master server config
[program:master]
command=python {pwd}/local/whispergstserver/master_server.py --port={port}
numprocs=1
autostart=true
autorestart=true
stopasgroup=true
stderr_logfile={pwd}/supervisor/log/master.log

; worker (communicate between decoder and master)
[program:worker]
command=python {pwd}/local/whispergstserver/worker.py -c {pwd}/conf/samaple_worker.yaml -p 49%(process_num)03d -u wss://127.0.0.1:{port}/worker/ws/speech
numprocs=2
process_name=%(program_name)s_%(process_num)03d
autostart=true
autorestart=true
stopasgroup=true
stderr_logfile={pwd}/supervisor/log/%(program_name)s_simple_%(process_num)03d.log
"""

# Write the content to the file
config_file_path = os.path.join(outdir, "supervisord.conf")
with open(config_file_path, "w") as f:
    f.write(config_content)

print(f"Configuration file created at {config_file_path}")

## supervisord_worker.conf
default_hostname = "127.0.0.1"
hostname = input(f"Please enter the port of the master server (default: {default_hostname}): ") or default_hostname
# Define the content of the file
config_content = f"""
[supervisord]
nodaemon=false
user=teinhonglo
logfile_maxbytes=50MB
logfile={pwd}/supervisor/supervisord.log
pidfile={pwd}/supervisor/supervisord.pid
minfds=65535
minprocs=65535

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

[supervisorctl]
serverurl=unix://{pwd}/supervisor/supervisor.sock ; use a unix:// URL  for a unix socket

[unix_http_server]
file={pwd}/supervisor/supervisor.sock  ; (the path to the socket file)
chmod=0700                       ; socket file mode (default 0700)

[group:capt]
programs=worker

; worker (communicate between decoder and master)
[program:worker]
command=python {pwd}/local/whispergstserver/worker.py -c {pwd}/conf/samaple_worker.yaml -p 49%(process_num)03d -u wss://{hostname}:{port}/worker/ws/speech
numprocs=2
process_name=%(program_name)s_%(process_num)03d
autostart=true
autorestart=true
stopasgroup=true
stderr_logfile={pwd}/supervisor/log/%(program_name)s_simple_%(process_num)03d.log
"""

# Write the content to the file
config_file_path = os.path.join(outdir, "supervisord_worker.conf")
with open(config_file_path, "w") as f:
    f.write(config_content)

print(f"Configuration file created at {config_file_path}")
