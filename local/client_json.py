# encoding=utf-8
import argparse
from ws4py.client.threadedclient import WebSocketClient
import time
import threading
import sys
import urllib.parse
from queue import Queue
import json
import os

def rate_limited(maxPerSecond):
    minInterval = 1.0 / float(maxPerSecond)
    def decorate(func):
        lastTimeCalled = [0.0]
        def rate_limited_function(*args,**kargs):
            elapsed = time.time() - lastTimeCalled[0]
            leftToWait = minInterval - elapsed
            if leftToWait > 0:
                time.sleep(leftToWait)
            ret = func(*args, **kargs)
            lastTimeCalled[0] = time.time()
            return ret
        return rate_limited_function
    return decorate

class MyClient(WebSocketClient):

    def __init__(self, audiofile, output_json, url, protocols=None, extensions=None, heartbeat_freq=None, byterate=32000,
                 save_adaptation_state_filename=None, send_adaptation_state_filename=None):
        super(MyClient, self).__init__(url, protocols, extensions, heartbeat_freq)
        self.final_hyps = []
        self.audiofile = audiofile
        self.byterate = byterate
        self.final_hyp_queue = Queue()
        self.save_adaptation_state_filename = save_adaptation_state_filename
        self.send_adaptation_state_filename = send_adaptation_state_filename
        self.eos_time = 0.0
        self.output_json = output_json

    @rate_limited(4)
    def send_data(self, data):
        self.send(data, binary=True)

    def opened(self):
        def send_data_to_ws():
            if self.send_adaptation_state_filename is not None:
                print(f"Sending adaptation state from {self.send_adaptation_state_filename}", file=sys.stderr)
                try:
                    adaptation_state_props = json.load(open(self.send_adaptation_state_filename, "r"))
                    self.send(json.dumps(dict(adaptation_state=adaptation_state_props)))
                except Exception as e:
                    print(f"Failed to send adaptation state: {e}", file=sys.stderr)
            
            self.send_time = time.time()  # Start timer
            with self.audiofile as audiostream:
                for block in iter(lambda: audiostream.read(self.byterate // 4), b""):
                    self.send_data(block)
            self.send_end_time = time.time()  # End send time
            self.send("EOS")
            self.eos_time = time.time()  # End of stream time

        t = threading.Thread(target=send_data_to_ws)
        t.start()

    def received_message(self, m):
        response = json.loads(str(m))
        if response['status'] == 0:
            if 'result' in response:
                with open(self.output_json, 'w') as f:
                    json.dump(response, f)
                trans = response['result']['hypotheses'][0]['transcript']
                if response['result']['final']:
                    self.final_hyps.append(trans)
                    print('\r{}'.format(trans.replace("\n", "\\n")), file=sys.stderr)
                else:
                    print_trans = trans.replace("\\n", "\\n")
                    if len(print_trans) > 80:
                        print_trans = f"... {print_trans[-76:]}"
                    print(f'\r{print_trans}', end='', file=sys.stderr)
            if 'adaptation_state' in response:
                if self.save_adaptation_state_filename:
                    print(f"Saving adaptation state to {self.save_adaptation_state_filename}", file=sys.stderr)
                    with open(self.save_adaptation_state_filename, "w") as f:
                        f.write(json.dumps(response['adaptation_state']))
        else:
            print(f"Received error from server (status {response['status']})", file=sys.stderr)
            if 'message' in response:
                print(f"Error message: {response['message']}", file=sys.stderr)

    def get_full_hyp(self, timeout=60):
        return self.final_hyp_queue.get(timeout)

    def closed(self, code, reason=None):
        self.final_hyp_queue.put(" ".join(self.final_hyps))

    def get_eos_time(self):
        return self.eos_time


def main():

    parser = argparse.ArgumentParser(description='Command line client for kaldigstserver')
    parser.add_argument('-u', '--uri', default="wss://smildemo.csie.ntnu.edu.tw:9987/client/ws/speech", dest="uri", help="Server websocket URI")
    parser.add_argument('-r', '--rate', default=32000, dest="rate", type=int, help="Rate in bytes/sec at which audio should be sent to the server. NB! For raw 16-bit audio it must be 2*samplerate!")
    parser.add_argument('--save-adaptation-state', help="Save adaptation state to file")
    parser.add_argument('--send-adaptation-state', help="Send adaptation state from file")
    parser.add_argument('--content-type', default='', help="Use the specified content type (empty by default, for raw files the default is audio/x-raw, layout=(string)interleaved, rate=(int)<rate>, format=(string)S16LE, channels=(int)1")
    parser.add_argument('--prompt', default='a01_01', dest="prompt", help="Prompt for CAPT", type=str)
    parser.add_argument('--user_id', default='test123', dest="user_id", help="User ID", type=str)
    parser.add_argument('audiofile', help="Audio file to be sent to the server", type=argparse.FileType('rb'), default=sys.stdin)
    parser.add_argument('output_json')
    args = parser.parse_args()

    content_type = args.content_type
    if content_type == '' and args.audiofile.name.endswith(".raw"):
        content_type = f"audio/x-raw, layout=(string)interleaved, rate=(int){args.rate // 2}, format=(string)S16LE, channels=(int)1"

    ws = MyClient(args.audiofile, args.output_json, f"{args.uri}?{urllib.parse.urlencode([('content-type', content_type), ('prompt', args.prompt), ('user-id', args.user_id)])}", byterate=args.rate,
                  save_adaptation_state_filename=args.save_adaptation_state, send_adaptation_state_filename=args.send_adaptation_state)
    ws.connect()
    result = ws.get_full_hyp()
    tStart = ws.get_eos_time()  # Get EOS time
    tEnd = time.time()  # End time

    ws.close()
    print(f"It took {tEnd - tStart:.2f} seconds")  # Display the total time taken


if __name__ == "__main__":
    main()
