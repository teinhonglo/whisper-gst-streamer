# whisper-gst-streamer

This project is called **whisper-gst-streamer**.

It references to **kaldi-gstreamer**, **dictate.js** and **simul_whisper**.
1. kaldi-gstreamer: [Link](https://github.com/alumae/kaldi-gstreamer-server)
2. dictate.js: [Link](https://github.com/Kaljurand/dictate.js)
3. simul_whisper: [Link](https://github.com/backspacetg/simul_whisper)

### TODO:
1. Implement batch decoding (shared memory).

## Installation

### Recommended OS: [Ubuntu 22.04](https://www.ubuntu-tw.org/modules/tinyd0/)
To install necessary dependencies, run the following commands:

```bash
sudo apt-get install git
sudo apt-get install supervisor
sudo apt-get install automake autoconf sox subversion
sudo apt-get install zlib1g zlib1g-dev libtool
sudo apt-get install libgstreamer1.0-dev
sudo apt-get install libcairo2-dev
sudo apt-get install libgirepository1.0-dev
sudo apt-get install gstreamer1.0-plugins-good gstreamer1.0-tools gstreamer1.0-pulseaudio
sudo apt-get install python-yaml python-gi
sudo apt-get install apache2
```

### Miniconda 3 Setup

You can download Miniconda from the following link:

- [Miniconda3 Latest - Linux x86_64](https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh)

To set up the environment:

```bash
conda create --name whisper-sys python=3.8
pip install -r conf/requirements.txt
```

### Python 3.8 Dependencies

Install the necessary Python packages with Conda:

```bash
# Python 3.8 environment
conda install -c conda-forge pygobject
conda install -c anaconda gstreamer
```

### Prepare the System
#### Server

```
. ./path.sh
./local/prepare_online_model.sh

python local/create_supervisor_config.py 

# Start Master, Worker, and Decoder
supervisord -c supervisor/supervisord.conf

# Start Worker and Decoder
supervisord -c supervisor/supervisord_worker.conf
```

#### Web demo
```
vim dictate/demos/asr.js

# Change the following codes
const HOSTNAME = "" // Enter the hostname of the master server
const PORT = ""; // Enter the port of the master server
```

#### local demo
```
./test_json.sh --tag $ANY_THING_YOU_WANT --hostname $HOSTNAME
```
