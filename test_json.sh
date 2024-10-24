tag=emp
hostname=
concurrency=1

. ./local/parse_options.sh

mkdir -p jsons logs

for i in `seq 1 $concurrency`; do 
    rm -rf json/${tag}.${concurrency}.${i}.a01.json
    python local/client_json.py --uri wss://$hostname:9988/client/ws/speech \
                                --rate 32000 --prompt a01_01 \
                                --user_id test123-${i} demo_wavs/test_en.wav \
                                jsons/${tag}.${concurrency}.a01.${i}.json
done

