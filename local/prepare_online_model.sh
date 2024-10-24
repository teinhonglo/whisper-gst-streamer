
model_urls="https://openaipublic.azureedge.net/main/whisper/models/ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e/base.pt https://openaipublic.azureedge.net/main/whisper/models/9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794/small.pt https://openaipublic.azureedge.net/main/whisper/models/345ae4da62f9b3d59415adc60127b97c714f32e89e936602e85993674d08dcb1/medium.pt https://openaipublic.azureedge.net/main/whisper/models/81f7c96c852ee8fc832187b0132e569d6c3065a3252ed18e56effd0b6a73e524/large-v2.pt"

cif_model_urls="https://raw.githubusercontent.com/backspacetg/simul_whisper/main/cif_models/base.pt https://raw.githubusercontent.com/backspacetg/simul_whisper/main/cif_models/small.pt https://raw.githubusercontent.com/backspacetg/simul_whisper/main/cif_models/medium.pt https://raw.githubusercontent.com/backspacetg/simul_whisper/main/cif_models/large-v2.pt"

whisper_dir=models/stt/whispers
cif_dir=models/stt/cif_models

echo "$0 $@"
. local/parse_options.sh || exit 1;

# whisper
mkdir -p $whisper_dir
for model_url in $model_urls; do
    model_name=$(basename $model_url)
    model_path=$whisper_dir/$model_name
    wget -O $model_path $model_url
done

# cif
mkdir -p $cif_dir
for cif_model_url in $cif_model_urls; do
    cif_model_name=$(basename $cif_model_url)
    cif_model_path=$cif_dir/$cif_model_name
    wget -O $cif_model_path $cif_model_url
done
