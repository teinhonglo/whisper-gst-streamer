# -*- coding: UTF-8 -*-

"""
Modified on March 13, 2023
@aurhor: Tien-Hong Lo
 (1) connect to master-server and register this worker by using Websocket
 (2) connect to online2-tcp-nnet3-decoder server using Websocket
    _________________         ../worker/ws/speech       __________                            _____________________________
    | master server |  <-------------------------- ---- | worker |   ------ BYTE BUFFER ----> | online-tcp-decoder server |
    ￣￣￣￣￣￣￣￣￣   ---------- BYTE BUFFER --------> ￣￣￣￣￣    <----- transcript ------ ￣￣￣￣￣￣￣￣￣￣￣￣￣￣￣
                                       (1)                                     (2)
"""

import logging
import logging.config
import time
import _thread as thread
import threading
import os
import argparse
from subprocess import Popen, PIPE
from gi.repository import GLib
import yaml
import json
import sys
import locale
import codecs
import zlib
import base64
import time

import asyncio
from tornado.platform.asyncio import AnyThreadEventLoopPolicy
import tornado.gen 
import tornado.process
import tornado.ioloop
import tornado.locks
from ws4py.client.threadedclient import WebSocketClient
import ws4py.messaging
from ws4py.messaging import TextMessage

from decoder import DecoderPipeline

import common

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT = 5
SILENCE_TIMEOUT = 5
FRONTEND_TIMEOUT = 60
DECODER_TIMEOUT = 10

class ServerWebsocket(WebSocketClient):
    STATE_CREATED = 0
    STATE_CONNECTED = 1
    STATE_INITIALIZED = 2
    STATE_PROCESSING = 3
    STATE_EOS_RECEIVED = 7
    STATE_CANCELLING = 8
    STATE_FINISHED = 100
    ID_TO_STATE = { 0: "STATE_CREATED", 1: "STATE_CONNECTED", 2: "STATE_INITIALIZED", 3: "STATE_PROCESSING", 7: "STATE_EOS_RECEIVED", 8: "STATE_CANCELLING", 100: "STATE_FINISHED" }

    def __init__(self, uri, decoder_pipeline, post_processor, full_post_processor=None):
        self.uri = uri
        self.decoder_pipeline = decoder_pipeline
        self.post_processor = post_processor
        self.full_post_processor = full_post_processor
        WebSocketClient.__init__(self, url=uri, heartbeat_freq=10)
        self.pipeline_initialized = False
        self.partial_transcript = ""
        self.decoder_pipeline.set_result_handler(self._on_result)
        self.decoder_pipeline.set_full_result_handler(self._on_full_result)
        self.decoder_pipeline.set_error_handler(self._on_error)
        self.decoder_pipeline.set_eos_handler(self._on_eos)
        self.state = self.STATE_CREATED
        self.last_decoder_message = time.time()
        self.request_id = "<undefined>"
        self.timeout_decoder = 5
        self.num_segments = 0
        self.last_partial_result = ""
        asyncio.set_event_loop_policy(AnyThreadEventLoopPolicy())
        self.post_processor_lock = threading.Lock()
        self.processing_condition = threading.Condition()
        self.num_processing_threads = 0
        logger.debug("[DEBUG][INIT] state = {}".format(self.ID_TO_STATE[self.state]))
        
    def opened(self):
        logger.info("Opened websocket connection to master server")
        self.state = self.STATE_CONNECTED
        self.last_partial_result = ""
        logger.debug("[DEBUG][OPEN] state = {}".format(self.ID_TO_STATE[self.state]))
        # self.decoder_pipeline = decoder_pipeline
    
    def guard_timeout(self):
        asyncio.set_event_loop(asyncio.new_event_loop())
        global SILENCE_TIMEOUT
        while self.state in [self.STATE_EOS_RECEIVED, self.STATE_CONNECTED, self.STATE_INITIALIZED, self.STATE_PROCESSING]:
            logger.debug("[DEBUG][GT] state = {}, ({:.4f} > {})".format(self.ID_TO_STATE[self.state], time.time() - self.last_decoder_message, SILENCE_TIMEOUT))
            if time.time() - self.last_decoder_message > SILENCE_TIMEOUT:
                logger.warning("%s: More than %d seconds from last decoder hypothesis update, cancelling" % (self.request_id, SILENCE_TIMEOUT))
                self.finish_request()
                event = dict(status=common.STATUS_NO_SPEECH)
                try:
                    self.send(json.dumps(event))
                except:
                    logger.warning("%s: Failed to send error event to master" % (self.request_id))
                self.close()
                return
            logger.debug("%s: Checking that decoder hasn't been silent for more than %d seconds" % (self.request_id, SILENCE_TIMEOUT))
            time.sleep(1)

    def frontend_timeout(self):
        asyncio.set_event_loop(asyncio.new_event_loop())
        global FRONTEND_TIMEOUT
        while self.state in [self.STATE_CONNECTED, self.STATE_INITIALIZED, self.STATE_PROCESSING]:
            logger.debug("[DEBUG][FT] state = {}, ({:.4f} > {})".format(self.ID_TO_STATE[self.state], time.time() - self.first_connection_time, FRONTEND_TIMEOUT))
            if time.time() - self.first_connection_time > FRONTEND_TIMEOUT:
                logger.warning("%s: More than %d seconds from last decoder hypothesis update, cancelling" % (self.request_id, FRONTEND_TIMEOUT))
                self.finish_request()
                event = dict(status=common.STATUS_NO_SPEECH)
                try:
                    self.send(json.dumps(event))
                except:
                    logger.warning("%s: Failed to send error event to master" % (self.request_id))
                self.close()
                return
            logger.debug("%s: Checking that waveform from frontend hasn't been large than %d seconds" % (self.request_id, FRONTEND_TIMEOUT))
            time.sleep(1)

    def received_message(self, m):
        logger.debug("%s: Got message from server of type %s" % (self.request_id, str(type(m)))) 
        logger.debug("[DEBUG][RECV] state = {}".format(self.ID_TO_STATE[self.state]))

        if isinstance(m, ws4py.messaging.TextMessage):
            logger.debug("%s: [JSON] TextMessage from server is: %s", self.request_id, m.data.decode("utf-8"))
            
        if self.state == self.__class__.STATE_CONNECTED:
            props = json.loads(str(m.data.decode("utf-8")))
            content_type = props['content_type']
            self.request_id = props['id']
            self.user_id = props['user_id']
            self.prompt = props['prompt']
            # for character-based system (Mandarin)
            if props["prons_length"] != "none":
                self.prons_length = [ int(i) for i in props['prons_length'].split("_") ]
            else:
                self.prons_length = None

            self.num_segments = 0
            self.decoder_pipeline.init_request(self.request_id, self.user_id)
            self.last_decoder_message = time.time()
            self.decoder_pipeline.process_prompt(self.prompt)
            logger.info("%s: Initialized request" % self.request_id)
            self.state = self.STATE_INITIALIZED
            logger.info("%s: Starting timeout frontend" % self.request_id)
            self.first_connection_time = time.time()
            thread.start_new_thread(self.frontend_timeout, ())
        elif isinstance(m, ws4py.messaging.TextMessage) and str(m) == "EOS":
            if self.state != self.STATE_CANCELLING and self.state != self.STATE_EOS_RECEIVED and self.state != self.STATE_FINISHED:
                logger.info("%s: Got EOS, worker is in state %s" % (self.request_id, self.ID_TO_STATE[self.state]))
                self.decoder_pipeline.recv_and_rec_data(is_final=True)
                self.decoder_pipeline.end_request()
                # self.state = self.STATE_EOS_RECEIVED
            else:
                logger.info("%s: Ignoring EOS, worker already in state %s" % (self.request_id, self.ID_TO_STATE[self.state]))
        else:
            if self.state != self.STATE_CANCELLING and self.state != self.STATE_EOS_RECEIVED and self.state != self.STATE_FINISHED:
                if isinstance(m, ws4py.messaging.BinaryMessage):
                    logger.warning("%s: Got Binary message from master server" % (self.request_id))
                    self.decoder_pipeline.process_data(m.data)
                    self.decoder_pipeline.recv_and_rec_data()
                    self.state = self.STATE_PROCESSING
                elif isinstance(m, ws4py.messaging.TextMessage):
                    props = json.loads(str(m))
                    logger.warning("%s: Got JSON message: %s" % (self.request_id, props))
            else:
                logger.info("%s: Ignoring data, worker already in state %s" % (self.request_id, self.ID_TO_STATE[self.state]))

    def finish_request(self):
        logger.debug("[DEBUG][FINISH_REQ] state = {}".format(self.ID_TO_STATE[self.state]))
        if self.state == self.STATE_CONNECTED:
            # connection closed when we are not doing anything
            self.decoder_pipeline.finish_request()
            self.state = self.STATE_FINISHED
            return
        if self.state == self.STATE_INITIALIZED:
            # connection closed when request initialized but with no data sent
            self.decoder_pipeline.finish_request()
            self.state = self.STATE_FINISHED
            return
        if self.state != self.STATE_FINISHED:
            logger.info("%s: Master disconnected before decoder reached EOS?" % self.request_id)
            self.state = self.STATE_CANCELLING
            self.decoder_pipeline.cancel()
            counter = 0
            while self.state == self.STATE_CANCELLING:
                counter += 1
                if counter > DECODER_TIMEOUT:
                    # lost hope that the decoder will ever finish, likely it has hung
                    # FIXME: this might introduce new bugs
                    logger.info("%s: Giving up waiting after %d tries" % (self.request_id, counter))
                    self.state = self.STATE_FINISHED
                else:
                    logger.info("%s: Waiting for EOS from decoder" % self.request_id)
                    time.sleep(1)
            self.decoder_pipeline.finish_request()
            logger.info("%s: Finished waiting for EOS" % self.request_id)


    def closed(self, code, reason=None):
        logger.debug("[DEBUG][CLOSE] state = {}".format(self.ID_TO_STATE[self.state]))
        logger.debug("%s: Websocket closed() called" % self.request_id)
        self.finish_request()
        logger.debug("%s: Websocket closed() finished" % self.request_id)
        logger.debug("[DEBUG][CLOSEf] state = {}".format(self.ID_TO_STATE[self.state]))

    def _increment_num_processing(self, delta):
        self.processing_condition.acquire()
        self.num_processing_threads += delta
        logger.info("%s: [increment_num_processing] Num Processing Threads >> %s"  % (self.request_id, self.num_processing_threads))
        self.processing_condition.notify()
        self.processing_condition.release()
        logger.info("%s: [increment_num_processing] Ended"  % (self.request_id))

    @tornado.gen.coroutine
    def _on_result(self, result, final):
        logger.debug("[DEBUG][ON_RSLT] state = {}, (final={}; result={})".format(self.ID_TO_STATE[self.state], final, result))
        try:
            self._increment_num_processing(1)
            if final:
                # final results are handled by _on_full_result()
                return
            self.last_decoder_message = time.time()
            if self.last_partial_result == result:
                return
            self.last_partial_result = result
            logger.info("%s: Postprocessing (final=%s) result.."  % (self.request_id, final))
            processed_transcripts = yield self.post_process([result], blocking=False)
            if processed_transcripts:
                logger.info("%s: Postprocessing done." % self.request_id)
                event = dict(status=common.STATUS_SUCCESS,
                             segment=self.num_segments,
                             result=dict(hypotheses=dict(transcript=processed_transcripts[0]), final=final))
                try:
                    self.send(json.dumps(event))
                except:
                    e = sys.exc_info()[1]
                    logger.warning("Failed to send event to master: %s" % e)
        finally:
            self._increment_num_processing(-1)

    @tornado.gen.coroutine
    def _on_full_result(self, full_result_json):
        logger.debug("[DEBUG][ON_FULL] state = {}, (result_json={})".format(self.ID_TO_STATE[self.state], full_result_json))
        try:
            self._increment_num_processing(1)
            
            self.last_decoder_message = time.time()
            full_result = json.loads(full_result_json)
            full_result['segment'] = self.num_segments
            full_result['id'] = self.request_id
            if full_result.get("status", -1) == common.STATUS_SUCCESS:
                logger.debug(u"%s: Before postprocessing: %s" % (self.request_id, repr(full_result)))
                full_result = yield self.post_process_full(full_result)
                logger.info("%s: Postprocessing done." % self.request_id)
                logger.debug(u"%s: After postprocessing: %s" % (self.request_id, repr(full_result)))

                try:
                    logger.debug("[SUCCESS][status0] full_request is {}".format(full_result))
                    self.send(json.dumps(full_result))
                except:
                    e = sys.exc_info()[1]
                    logger.warning("Failed to send event to master: %s" % e)
                if full_result.get("result", {}).get("final", True):
                    self.num_segments += 1
                    self.last_partial_result = ""
            else:
                logger.info("%s: Result status is %d, forwarding the result to the server anyway" % (self.request_id, full_result.get("status", -1)))
                try:
                    logger.debug("[UNK][status!=0] full_request is {}".format(full_result))
                    self.send(json.dumps(full_result))
                except:
                    e = sys.exc_info()[1]
                    logger.warning("Failed to send event to master: %s" % e)
        finally:
            self._increment_num_processing(-1)
            logger.debug("[DEBUG][ON_FULLf] state = {}, (result_json={})".format(self.ID_TO_STATE[self.state], full_result_json))
    
    @tornado.gen.coroutine
    def _on_word(self, word):
        logger.debug("[DEBUG][ON_W] state = {}".format(self.ID_TO_STATE[self.state]))
        try:
            self._increment_num_processing(1)
            
            self.last_decoder_message = time.time()
            if word != "<#s>":
                if len(self.partial_transcript) > 0:
                    self.partial_transcript += " "
                self.partial_transcript += word
                logger.debug("%s: Postprocessing partial result.."  % self.request_id)
                processed_transcript = (yield self.post_process([self.partial_transcript], blocking=False))[0]
                if processed_transcript:
                    logger.debug("%s: Postprocessing done." % self.request_id)

                    event = dict(status=common.STATUS_SUCCESS,
                                 segment=self.num_segments,
                                 result=dict(hypotheses=[dict(transcript=processed_transcript)], final=False))
                    self.send(json.dumps(event))
            else:
                logger.info("%s: Postprocessing final result.."  % self.request_id)
                processed_transcript = (yield self.post_process(self.partial_transcript, blocking=True))[0]
                logger.info("%s: Postprocessing done." % self.request_id)
                event = dict(status=common.STATUS_SUCCESS,
                             segment=self.num_segments,
                             result=dict(hypotheses=[dict(transcript=processed_transcript)], final=True))
                self.send(json.dumps(event))
                self.partial_transcript = ""
                self.num_segments += 1
        finally:
            self._increment_num_processing(-1)


    def _on_eos(self, data=None):
        logger.debug("[DEBUG][ON_EOS] state = {}".format(self.ID_TO_STATE[self.state]))
        self.last_decoder_message = time.time()
        # Make sure we won't close the connection before the 
        # post-processing has finished
        self.processing_condition.acquire()
        logger.info("%s: [DEBUG][ON_EOS] Num Processing Threads >> %s"  % (self.request_id, self.num_processing_threads))
        while self.num_processing_threads > 0:
            self.processing_condition.wait()
        self.processing_condition.release()
        
        logger.debug("[DEBUG][ON_EOSr] state = {}".format(self.ID_TO_STATE[self.state]))
        self.state = self.STATE_FINISHED
        self.send_adaptation_state()
        self.close()
        logger.debug("[DEBUG][ON_EOSf] state = {}".format(self.ID_TO_STATE[self.state]))

    def _on_error(self, err_msg, err_type = "oov"):
        logger.debug("[DEBUG][ON_Error] state = {}".format(self.ID_TO_STATE[self.state]))
        self.state = self.STATE_FINISHED
        if err_type == "oov":
            event = dict(status=common.STATUS_NOT_ALLOWED, message=err_msg)
        elif err_type == "align":
            event = dict(status=common.STATUS_NOT_ALLOWEDALIGN, message=err_msg)
        else:
            event = dict(status=common.STATUS_SERVICE_NOT_ALLOWED, message=err_msg)
            

        try:
            self.send(json.dumps(event))
        except:
            e = sys.exc_info()[1]
            logger.warning("Failed to send event to master: %s" % e)
        self.close()
        logger.debug("[DEBUG][ON_Error] state = {}".format(self.ID_TO_STATE[self.state]))

    def send_adaptation_state(self):
        logger.debug("[DEBUG][SEND_ADP] state = {}".format(self.ID_TO_STATE[self.state]))
        if hasattr(self.decoder_pipeline, 'get_adaptation_state'):
            logger.info("%s: Sending adaptation state back to master server..." % (self.request_id))
            adaptation_state = self.decoder_pipeline.get_adaptation_state()
            event = dict(status=common.STATUS_SUCCESS,
                         adaptation_state=dict(id=self.request_id,
                                               value=base64.b64encode(zlib.compress(adaptation_state)),
                                               type="string+gzip+base64",
                                               time=time.strftime("%Y-%m-%dT%H:%M:%S")))
            try:
                self.send(json.dumps(event))
            except:
                e = sys.exc_info()[1]
                logger.warning("Failed to send event to master: " + str(e))
        else:
            logger.info("%s: Adaptation state not supported by the decoder, not sending it." % (self.request_id))    

    @tornado.gen.coroutine
    def post_process(self, texts, blocking=False):
        if self.post_processor:
            if self.post_processor_lock.acquire(blocking):
                result = []
                for text in texts:
                    self.post_processor.stdin.write("%s\n" % text.encode("utf-8"))
                    self.post_processor.stdin.flush()
                    logging.debug("%s: Starting postprocessing: %s"  % (self.request_id, text))
                    text = yield self.post_processor.stdout.read_until('\n')#.decode("utf-8")
                    text = text.decode("utf-8")
                    text = text.strip()
                    text = text.replace("\\n", "\n")
                    logging.debug("%s: Postprocessing returned: %s"  % (self.request_id, text))
                    result.append(text)
                self.post_processor_lock.release()
                raise tornado.gen.Return(result)
            else:
                logging.debug("%s: Skipping postprocessing since post-processor already in use"  % (self.request_id))
                raise tornado.gen.Return(None)
        else:
            raise tornado.gen.Return(texts)
            
    @tornado.gen.coroutine
    def post_process_full(self, full_result):
        if self.full_post_processor:
            self.full_post_processor.stdin.write("%s\n\n" % json.dumps(full_result))
            self.full_post_processor.stdin.flush()
            lines = []
            while True:
                l = self.full_post_processor.stdout.readline()
                if not l: break # EOF
                if l.strip() == "":
                    break
                lines.append(l)
            full_result = json.loads("".join(lines))

        elif self.post_processor:
            transcripts = []
            for hyp in full_result.get("result", {}).get("hypotheses", []):
                transcripts.append(hyp["transcript"])
            processed_transcripts = yield self.post_process(transcripts, blocking=True)
            for (i, hyp) in enumerate(full_result.get("result", {}).get("hypotheses", [])):
                hyp["original-transcript"] = hyp["transcript"]
                hyp["transcript"] = processed_transcripts[i]
        raise tornado.gen.Return(full_result) 



def main_loop(uri, decoder_pipeline, post_processor, full_post_processor=None):
    while True:
        ws = ServerWebsocket(uri, decoder_pipeline, post_processor, full_post_processor=full_post_processor)
        try:
            logger.info("Opening websocket connection to master server")
            ws.connect()
            ws.run_forever()
        except Exception:
            logger.error("Couldn't connect to server, waiting for %d seconds", CONNECT_TIMEOUT)
            time.sleep(CONNECT_TIMEOUT)
        # fixes a race condition
        time.sleep(1)



def main():
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)8s %(asctime)s %(message)s ")
    logging.debug('Starting up worker')
    parser = argparse.ArgumentParser(description='Worker for kaldigstserver')
    parser.add_argument('-u', '--uri', default="ws://localhost:8888/worker/ws/speech", dest="uri", help="Server<-->worker websocket URI")
    parser.add_argument('-f', '--fork', default=1, dest="fork", type=int)
    parser.add_argument('-p', '--port', default=8899, dest="port", help="Decoder Server TCP port")
    parser.add_argument('-c', '--conf', dest="conf", help="YAML file with decoder configuration")
    parser.add_argument('-gu', '--grader_url', default="http://localhost:21991/text_grading", dest="grader_url")
    parser.add_argument('-lu', '--lider_url', default="http://localhost:21992/liding", dest="lider_url")

    args = parser.parse_args()

    if args.fork > 1:
        logging.info("Forking into %d processes" % args.fork)
        tornado.process.fork_processes(args.fork)

    conf = {}
    if args.conf:
        with open(args.conf) as f:
            conf = yaml.safe_load(f)

    if "logging" in conf:
        logging.config.dictConfig(conf["logging"])

    # fork off the post-processors before we load the model into memory
    post_processor = None
    if "post-processor" in conf:
        STREAM = tornado.process.Subprocess.STREAM
        post_processor = tornado.process.Subprocess(conf["post-processor"], shell=True, stdin=PIPE, stdout=STREAM)

    full_post_processor = None
    if "full-post-processor" in conf:
        full_post_processor = Popen(conf["full-post-processor"], shell=True, stdin=PIPE, stdout=PIPE)

    global SILENCE_TIMEOUT
    SILENCE_TIMEOUT = conf.get("silence-timeout", 5)

    global FRONTEND_TIMEOUT
    FRONTEND_TIMEOUT = conf.get("frontend-timeout", 60)
    
    global DECODER_TIMEOUT
    DECODER_TIMEOUT = conf.get("decoder-timeout", 10)

    decoder_pipeline = DecoderPipeline(sys_conf=conf, port=args.port, args=args)

    loop = GLib.MainLoop()
    thread.start_new_thread(loop.run, ())
    thread.start_new_thread(tornado.ioloop.IOLoop.instance().start, ())
    main_loop(args.uri, decoder_pipeline, post_processor, full_post_processor)  

if __name__ == "__main__":
    main()
