const HOSTNAME = "" // Enter the hostname of the master server
const PORT = ""; // Enter the port of the master server
var gDetect_error = false; //if occur error diable record button
var tt = new Transcription();

var dictate = new Dictate({
    server : "wss://" + HOSTNAME + ":" + PORT + "/client/ws/speech",
    serverStatus : "wss://" + HOSTNAME + ":" + PORT + "/client/ws/status",
    recorderWorkerPath : '../lib/recorderWorker.js',
    onReadyForSpeech : function() {
        __status('<i class="fa fa-spinner fa-pulse fa-3x fa-fw"></i>');
        errMsg.innerHTML = "";
    },
    onEndOfSpeech : function() {
        __updatePrompt("Wait a minute ... ");
    },
    onEndOfSession : function() {
        __status("");
    },
    onServerStatus : function(json) {
        __serverStatus(json.num_workers_available + ':' + json.num_requests_processed);
        console.log("Available workers", json.num_workers_available);
        //check if worker amount
        if (json.num_workers_available == 0 || gDetect_error) {
            $("#buttonStart").prop("disabled", true);
            $("#serverStatusBar").addClass("highlight");
        } else {
            $("#buttonStart").prop("disabled", false);
            $("#serverStatusBar").removeClass("highlight");
        }
    },
    onPartialResults : function(transcript) {
        // TODO: demo the case where there are more hypos
        tt.add(transcript, false);
        //__updateTranscript(tt.toString());
		__updatePrompt(transcript);
    },
    onResults : function(transcript) {
        if (typeof(diff) == "function") {
            diff();
        }
	    __SetFinalPrompt(transcript);
    },
    onError : function(code, data) {
        //console.log("onError:", code,data);
        $("#buttonStart").prop("disabled", true);
        document.getElementById("buttonStart").style.cursor="not-allowed";
        // __error(code, data);
        __status("Error: " + code);
        dictate.cancel();
    },
    onEvent : function(code, data) {
        $("#buttonStart").prop("disabled", false);
        document.getElementById("buttonStart").style.cursor=null;
        if(code==8){
            var data = JSON.parse(data);
            console.log(data);
        }
    }
});

// Private methods (called from the callbacks)
function __message(data) {
    return data;
}

function __error(code, data) {
    if(code == 5){
        gDetect_error = true;
        $("#buttonStart").prop("disabled", true);
        console.log("Please insert your microphone!");
        errMsg.innerHTML = "Please insert your microphone!";
    }else if (code == 6){
        console.log("ERR: " + code + ": " + data);
        var start = document.getElementById("buttonStart");
        var stop = document.getElementById("buttonStop");
        start.style.display = "block";
        stop.style.display = "none";
        errMsg.innerHTML = data;
    }else if (code == 12){
        console.log("ERR: " + code + ": " + data);
        var start = document.getElementById("buttonStart");
        var stop = document.getElementById("buttonStop");
        start.style.display = "block";
        stop.style.display = "none";
        errMsg.innerHTML = data;
    }else{
        console.log("ERR: " + code + ": " + data);
    }
}

function __status(msg) {
    statusBar.innerHTML = msg;
}

function __serverStatus(msg) {
    serverStatusBar.innerHTML = msg;
}

function __updateTranscript(text) {
    $("#transcript").val(text);
}

function __updatePrompt(text) {
    console.log(text);
    var trans = document.getElementById("transcript");
    if(transcript!="..."){
    trans.innerHTML = text;
    }
}

function __SetFinalPrompt(transcript){
    console.log(transcript);
    var trans = document.getElementById("transcript");
    if(transcript!="..."){
        trans.innerHTML = ""
        for(i=0; i<transcript.length; i++){
            if(transcript[i]!=""){
                trans.innerHTML += transcript[i] + " ";
            }
        }
    }
}

// Public methods (called from the GUI)
function toggleLog() {
    $(log).toggle();
}

function clearLog() {
    log.innerHTML = "";
}

function clearTranscription() {
    tt = new Transcription();
    $("#transcript").val("");
}

function startListening() {
    var start = document.getElementById("buttonStart");
    var stop = document.getElementById("buttonStop");
    start.style.display = "none"
    stop.style.display = "block"
    __SetFinalPrompt("...");
    dictate.startListening();
}

function stopListening() {
    var start = document.getElementById("buttonStart");
    var stop = document.getElementById("buttonStop");
    start.style.display = "block"
    stop.style.display = "none"
    dictate.stopListening();
}

function cancel() {
    dictate.cancel();
}

function init() {
    dictate.init();
}

function showConfig() {
    var pp = JSON.stringify(dictate.getConfig(), undefined, 2);
    $("#log").text(pp);
    $("#transcript").text("I am living in an apartment.")
}

window.onload = function() {
    init();
};
