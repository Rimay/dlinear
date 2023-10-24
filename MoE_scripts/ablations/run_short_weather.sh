script_full_path=$(dirname "$0")

GRAM=32

PRED_LEN=100

seq_len_list="6 88 170 254 336"
# seq_len_list="6 254"

# for seed in 2021
# for seed in 2022
# all previous 2 done, 2023 yet to do
# for seed in 2023
for seed in 2021 2022 2023
do
# Weather (no dropout)
for ablation in original_routing random_bypass random_routing
do

for pred_len in $PRED_LEN
do

for lr in 0.005 0.01 0.05
do

# for t_dim in 1 2 3 4 5
for t_dim in 2 3 4 5 6
do

for seq_len in $seq_len_list
do


sbatch -p GPU-shared -t 00:45:00 --gpus=v100-$GRAM:1 -A cis230033p --export=SEQ_LEN=$seq_len,SEED=$seed $script_full_path/$ablation/DLinear/MoE_weather.sh $pred_len $lr $t_dim

done
done
done
done
done

# Weather (dropout)

for ablation in random_bypass_dropout random_routing_dropout head_dropout
do

for pred_len in $PRED_LEN
do

for lr in 0.005 0.01 0.05
do

# for t_dim in 1 2 3 4 5
for t_dim in 2 3 4 5 6
do


for head_dropout in 0.2
do

for seq_len in $seq_len_list
do

sbatch -p GPU-shared -t 00:45:00 --gpus=v100-$GRAM:1 -A cis230033p --export=SEQ_LEN=$seq_len,SEED=$seed $script_full_path/$ablation/DLinear/MoE_weather.sh $pred_len $lr $t_dim $head_dropout

done
done
done
done
done
done

done