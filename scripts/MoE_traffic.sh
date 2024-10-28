#!/bin/bash

cd $(dirname $0)/..

python -u run.py \
--model_id 'traffic' \
--model 'MoLE_DLinear' \
--enc_in 862 \
--learning_rate 0.003
