# -*- coding: UTF-8 -*-
"""
Modified on Oct 20, 2024
@aurhor: Tien-Hong Lo
  * ACCEPT binary buffer
  * RETURN transcripts (str) 
"""

import wave
import os
import _thread as thread
from collections import OrderedDict
import common
import re
import gi
import gc

gi.require_version('Gst', '1.0')
from gi.repository import GObject, Gst

GObject.threads_init()
Gst.init(None)

import logging
logger = logging.getLogger(__name__)
import io
import pdb
# from ws4py.client.threadedclient import WebSocketClient
import socket
import requests
import time
import sys
import json
import numpy as np

# others
import wer
import subprocess
import base64

import os
import sys
import torch

from local.whispergstserver.simul_whisper.transcriber.config import AlignAttConfig
from local.whispergstserver.simul_whisper.transcriber.segment_loader import SegmentWrapper
from local.whispergstserver.simul_whisper.transcriber.simul_whisper import PaddedAlignAttWhisper, DEC_PAD
from local.whispergstserver.simul_whisper.whisper.audio import N_FFT, HOP_LENGTH, SAMPLE_RATE

from io import StringIO
log_stream = StringIO()
stream_handler = logging.StreamHandler(log_stream)

class DecoderPipeline(object):
    def __init__(self, sys_conf={}, port=8899, args=None):
        logger.info("Creating decoder using conf: {}".format(sys_conf))
        
        self.decoder_timeout = str(int(sys_conf.get("decoder-timeout", 10)) + 2)
        self.return_scorers = ["transcript", "weighted_score", "content", "pronunciation", "vocabulary"]
        
        self.result_handler = None
        self.full_result_handler = None
        self.eos_handler = None
        self.error_handler = None
        self.request_id = "<undefined>"
        self.user_id = "<undefined>"
        self.whole_data = b""
        self.obj = object
        self.port = int(port)
        self.prompt = ""
        self.transcript = ""
        self.model_config = sys_conf["model_config"]
        self._init_model(self.model_config)
        logger.info("Listen on Port: {}".format(self.port))
    
    def _init_model(self, model_config):
        '''
        if_ckpt_path: align with the whisper model. e.g., using small.pt for whisper small
        segment_length: chunk length, in seconds
        frame_threshold: threshold for the attention-guided decoding, in frames
        buffer_len: the lengths for the context buffer, in seconds
        min_seg_len: transcibe only when the context buffer is larger than this threshold. Useful when the segment_length is small
        '''
        model_path = model_config["model_path"]
        if_ckpt_path = model_config["if_ckpt_path"]
        segment_length = model_config["segment_length"]
        frame_threshold = model_config["frame_threshold"]
        buffer_len = model_config["buffer_len"]
        min_seg_len = model_config["min_seg_len"]
        language = model_config["language"]
        
        # https://github.com/backspacetg/simul_whisper/blob/main/transcribe.py
        # config
        cfg = AlignAttConfig(
            model_path=model_path, 
            segment_length=segment_length,
            frame_threshold=frame_threshold,
            language=language,
            buffer_len=buffer_len, 
            min_seg_len=min_seg_len,
            if_ckpt_path=if_ckpt_path,
        )
        # stt model
        self.speech2text = PaddedAlignAttWhisper(cfg, stream_handler)
        ## warmup
        #audio_path = "demo_wavs/A01_u254_t9_p4_i15_1-1_20220928.wav"
        #segmented_audio = SegmentWrapper(audio_path=audio_path, segment_length=segment_length)
        #for seg_id, (seg, is_last) in enumerate(segmented_audio):
        #    self.speech2text.infer(seg, is_last)
        
        # https://github.com/backspacetg/simul_whisper/blob/main/simul_whisper/transcriber/segment_loader.py#L36
        frames_to_read = int((segment_length * SAMPLE_RATE) / HOP_LENGTH)
        self.samples_to_read = frames_to_read * HOP_LENGTH
        self.samples_in_chunk = self.samples_to_read + N_FFT - HOP_LENGTH
        self.buffer_len = self.samples_in_chunk - self.samples_to_read

    def _on_partial_result(self, hyp):
        logger.info("{}: Getting partial result: {}".format(self.request_id, hyp))
        if self.result_handler:
            self.result_handler(hyp, False)
        logger.info("{}: Got partial result: {}".format(self.request_id, hyp))

    def _on_final_result(self, hyp):
        logger.info("{}: Getting final result: {}".format(self.request_id, hyp))
        if self.result_handler:
            logger.info("Transfer hyp to result-handler")
            self.result_handler(hyp, True)
        logger.info("{}: Got final result: {}".format(self.request_id, hyp))

    def _on_full_final_result(self, result):
        result_json = {}
        result_json["status"] = 0
        result_json["result"] = {}
        result_json["result"]["hypotheses"] = {}

        for rs in self.return_scorers:
            if rs in result:
                result_json["result"]["hypotheses"][rs] = result[rs]

        result_json["result"]["final"] = True
        full_result_json = json.dumps(result_json)
        logger.info("{}: Getting FULL final result: {}".format(self.request_id, full_result_json))
        if self.full_result_handler: 
            logger.info("Transfer hyp to full-result-handler")
            self.full_result_handler(full_result_json)
        logger.info("{}: Got FULL final result: {}".format(self.request_id, full_result_json))
        self._on_eos("send EOS inside decoder without socket")
    
    def _on_error(self, err_msg, err_type):
        self.finish_request()
        if self.error_handler:
            self.error_handler(err_msg=err_msg, err_type=err_type)

    def _on_eos(self, msg):
        logger.info('{}: Pipeline receiving eos signal'.format(self.request_id))
        # self.finish_request()
        if self.eos_handler:
            self.eos_handler[0](self.eos_handler[1])
        logger.info('{}: Pipeline received eos signal OK'.format(self.request_id))

    def finish_request(self):
        logger.info("{}: Resetting decoder state".format(self.request_id))
        self.request_id = "<undefined>"
        self.speech2text.refresh_segment(complete=True)
        # self._on_eos("send EOS inside decoder without socket")
        logger.info("{}: Resetting decoder state OK".format(self.request_id))

    def init_request(self, request_id, user_id):
        self.request_id = request_id
        self.user_id = user_id
        self.whole_data = b""
        self.partial_data = b""
        logger.info("{}: Initializing request".format(self.request_id))
        logger.info("{}: connect to decoder server".format(self.request_id))
        self.transcript = ""
        self.tmp_transcript = ""
        self.audio_buffer = torch.tensor([])
        self.speech2text.refresh_segment(complete=True)
        logger.info("{}: Initialized request".format(self.request_id))

    def process_prompt(self, full_prompt):
        self.prompt = full_prompt
        logger.debug('{}: Receieved prompt {} to pipeline'.format(self.request_id, self.prompt))

    def process_data(self, data):
        logger.debug('{}: Pushing buffer of size {} and type {} to pipeline'.format(self.request_id, len(data), type(data)))
        self.whole_data += data
        self.partial_data += data
        speech = np.frombuffer(self.partial_data, dtype='int16').astype(np.float16) / 32767.0
        speech = torch.from_numpy(speech)
        logger.debug(f'{self.request_id}: Audio buffer size {self.audio_buffer.shape} adn speech size {speech.shape}')
        self.audio_buffer = torch.cat((self.audio_buffer, speech))
        self.partial_data = b""
        
        logger.debug('{}: Pushing buffer done'.format(self.request_id))
       
    def recv_and_rec_data(self, is_final=False):
        logger.debug(f'{self.request_id}: The parameter is_final is {is_final}')
        logger.debug(f'{self.request_id}: Audio buffer size {self.audio_buffer.shape} and sample in chunk {self.samples_in_chunk}')
        # Get the audio from the audio buffer 
        if not is_final and len(self.audio_buffer) >= self.samples_in_chunk:
            audio_buffer = self.audio_buffer
            self.audio_buffer = self.audio_buffer[-self.buffer_len:]
        elif is_final and len(self.audio_buffer) > 0:
            audio_buffer = self.audio_buffer
            self.audio_buffer = torch.tensor([])
        else:
            return
        
        log_stream.truncate(0)
        log_stream.seek(0)
        
        with torch.no_grad():
            results = self.speech2text.infer(audio_buffer, is_last=is_final)
        
        log_data = log_stream.getvalue()
        
        pattern = r'current token.*?\((.*?)\)'
        results_tmp = re.findall(pattern, log_data)
        
        logger.debug(f'{self.request_id}: results {results}')
        logger.debug(f'{self.request_id}: results_tmp {results_tmp}')
        
        if results is not None and len(results) > 0:
            text = self.speech2text.tokenizer.decode(results)
            text = re.sub("<\|notimestamps\|>", "", text)
            self.transcript += text
            self._on_partial_result(self.transcript)
        elif len(results_tmp) > 0:
            transcript_tmp = " ".join(results_tmp)
            transcript_tmp = re.sub("<\|notimestamps\|>", "", transcript_tmp)
            self._on_partial_result(self.transcript + transcript_tmp)
        
        log_stream.truncate(0)
        log_stream.seek(0)
        
    def end_request(self):
        logger.info("{}: Ending Request to pipeline".format(self.request_id))
        logger.info("{}: Got transcript: >>{}<<".format(self.request_id, self.transcript))
        logger.info("{}: Ended Request to pipeline".format(self.request_id))
        transcript = " ".join(self.transcript.split())
        result = {}
        result["transcript"] = transcript
        self._on_full_final_result(result)
        # self.__save_waveform(os.getcwd() + '/wavs/' + self.user_id + '.wav')
        self.whole_data = b""

    def __save_text(self, filename, transcript):
        with open(filename, "w") as fn:
            fn.write(transcript)
            
    def __save_waveform(self, filename):
        try:
            f = wave.open(filename, 'wb')
            f.setparams((1,2,16000,0,'NONE','NONE'))
            f.writeframes(self.whole_data)
            f.close()
        except IOError as e:
            logger.info(e)
        
    def set_result_handler(self, handler):
        self.result_handler = handler

    def set_full_result_handler(self, handler):
        self.full_result_handler = handler

    def set_eos_handler(self, handler, user_data=None):
        self.eos_handler = (handler, user_data)

    def set_error_handler(self, handler):
        self.error_handler = handler

    def cancel(self):
        logger.info("{}: Sending EOS to pipeline in order to cancel processing".format(self.request_id)) 
        self.speech2text.refresh_segment(complete=True)
        logger.info("{}: Cancelled pipeline".format(self.request_id))

