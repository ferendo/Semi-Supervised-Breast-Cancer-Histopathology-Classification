#!/bin/sh
#SBATCH -N 1	  # nodes requested
#SBATCH -n 1	  # tasks requested
#SBATCH --partition=Teach-Standard
#SBATCH --gres=gpu:1
#SBATCH --mem=12000  # memory in Mb
#SBATCH --time=0-03:00:00

export CUDA_HOME=/opt/cuda-9.0.176.1/

export CUDNN_HOME=/opt/cuDNN-7.0/

export STUDENT_ID=$(whoami)

export LD_LIBRARY_PATH=${CUDNN_HOME}/lib64:${CUDA_HOME}/lib64:$LD_LIBRARY_PATH

export LIBRARY_PATH=${CUDNN_HOME}/lib64:$LIBRARY_PATH

export CPATH=${CUDNN_HOME}/include:$CPATH

export PATH=${CUDA_HOME}/bin:${PATH}

export PYTHON_PATH=$PATH

mkdir -p /disk/scratch/${STUDENT_ID}


export TMPDIR=/disk/scratch/${STUDENT_ID}/
export TMP=/disk/scratch/${STUDENT_ID}

mkdir -p ${TMP}/datasets/
export DATASET_DIR=${TMP}/datasets

# Activate the relevant virtual environment:
rsync -ua /home/${STUDENT_ID}/Leveraging-Unlabeled-Data-For-Breast-Cancer-Classification/data/BreaKHis_v1.tar.gz "${DATASET_DIR}"
tar -xzf "${DATASET_DIR}/BreaKHis_v1.tar.gz" -C "${DATASET_DIR}"

source /home/${STUDENT_ID}/miniconda3/bin/activate mlp

python ../../../src/main.py --use_gpu "True" --batch_size 20 --num_epochs 100 --continue_from_epoch -1 --seed 0 \
                     --image_num_channels 3 --image_height 224 --image_width 224 \
                     --num_layers 3 --num_filters 24 \
                     --dataset_location "${DATASET_DIR}/BreaKHis_v1" --experiment_name "${1}" \
                     --optim_type "SGD" --momentum 0.9 --nesterov "True" --weight_decay_coefficient ${5} \
                     --sched_type "Step" --learn_rate_max ${6} --learn_rate_min 0.0001 \
                     --drop_rate ${4} \
                     --magnification "${2}" --unlabelled_split ${3} \
                     --use_mix_match "False" --multi_class "False"
