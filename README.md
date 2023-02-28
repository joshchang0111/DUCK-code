# DUCK
This repository is forked from the official implementation of DUCK. Since the original project contains plenty of errors and unspecified parameters, I modify the code and further state the dataset preparation more clearly so that this project can be run.

## Dependencies:
- Python 3.8.10
```
$ pip install transformers==4.2.1
$ pip install Cython
$ pip install scikit-learn==0.21.3
$ pip install networkx==3.0
$ pip install pyro-ppl==0.3.0
$ pip install numpy==1.24.2
$ pip install pandas==1.4.4
$ pip install matplotlib
$ pip install ipdb
```
Install pytorch and pytorch-geometric as follows.
```
## Env: NVIDIA GeForce GTX 1080
$ pip install torch==1.9.0+cu102 -f https://download.pytorch.org/whl/torch_stable.html
$ pip install torch-scatter==2.0.8 -f https://data.pyg.org/whl/torch-1.9.0+cu102.html
$ pip install torch-sparse==0.6.11 -f https://data.pyg.org/whl/torch-1.9.0+cu102.html
$ pip install torch-geometric==2.2.0

## Env: NVIDIA GeForce RTX 3090
$ pip install torch==1.11.0+cu113 -f https://download.pytorch.org/whl/torch_stable.html
$ pip install torch-scatter==2.0.9 -f https://data.pyg.org/whl/torch-1.11.0+cu113.html
$ pip install torch-sparse==0.6.15 -f https://data.pyg.org/whl/torch-1.11.0+cu113.html
$ pip install torch-geometric==2.2.0
```

## Dataset
All datasets are publicly accessible.
- [Twitter15](https://www.dropbox.com/s/7ewzdrbelpmrnxu/rumdetect2017.zip?dl=0)
- [Twitter16](https://www.dropbox.com/s/7ewzdrbelpmrnxu/rumdetect2017.zip?dl=0)
- [CoAID](https://github.com/cuilimeng/CoAID) version 0.4
- [WEIBO](https://alt.qcri.org/~wgao/data/rumdect.zip)

### Data crawling tool
[twarc](https://github.com/DocNow/twarc)

### Data preparation
Since Twitter15 and Twitter16 datasets only provide the tweet IDs of the responses under each thread, you need to crawl the textual content of these responses via Twitter API. I use the dataset version of [yunzhusong/AARD](https://github.com/yunzhusong/AARD), where those content has already been crawled.

For training the model, you need to prepare several files in the following structure.
```
|__ data
    |__ {$DATASET_NAME}_5fold
        |__ data.label.txt
        |__ fold0
            |__ _x_train.pkl
            |__ _x_test.pkl
        |__ fold1
        |__ fold2
        |__ fold3
        |__ fold4
    |__ {$DATASET_NAME}graph
        |__ {$TWEET_ID_0}.npz
        |__ ...
```
Each fold directory (e.g. fold0) contains `_x_train.pkl` and `_x_test.pkl`. Both pickle files contain a list of tweet IDs, indicating the threads for training and testing respectively.

Also, `{$DATASET_NAME}graph` contains `.npz` files where the file names are the tweet IDs listed in `_x_train.pkl` and `_x_test.pkl`. Each `.npz` file contains the following information.
```
{
    "root":        , ## textual content of the source post
    "rootindex":   , ## 0
    "nodecontent": , ## textual content of all the responses
    "edgematrix":  , ## edge index for the conversational graph
    "y":             ## label of the root (in number format)
}
```
These files can be generated by running the following commands.
```
$ python preprocess.py --make_label --dataset $DATASET_NAME
$ python preprocess.py --split_5_fold --dataset $DATASET_NAME
$ python preprocess.py --build_graph --dataset $DATASET_NAME
```

## How to run the code?
### Train BERT+GAT with Comment Tree
```
python train.py \
    --datasetName $dataset \
    --baseDirectory ./data \
    --n_classes $n_classes \
    --foldnum $fold \
    --mode CommentTree \
    --modelName Simple_GAT_BERT \
    --batchsize $batch_size \
    --learningRate $lr_bert \
    --learningRateGraph $lr_gnn \
    --dropout_gat $dropout \
    --n_epochs 20 \
```
Can adjust the argument `--max_tree_len` if GPU memory is not enough.

### Train BERT+GAT with Comment Tree & Two-Tier Transformer with Comment Chain
```
python train.py \
    --datasetName $dataset \
    --baseDirectory ./data \
    --n_classes $n_classes \
    --foldnum $fold \
    --mode CommentTree \
    --modelName CCCTNet \
    --batchsize $batch_size \
    --learningRate $lr_bert \
    --learningRateGraph $lr_gnn \
    --dropout_gat $dropout \
    --n_epochs 20 \
    --max_tree_len 40 \
    --result_path ./result/CCCT
```
Detailed arguments can be found in `scripts/run.sh` & `scripts/run_ccct.sh`.

## publicaton
This is the source code for [DUCK: Rumour Detection on Social Media by Modelling User and Comment Propagation Networks](https://aclanthology.org/2022.naacl-main.364/).


If you find this code useful, please let us know and cite our paper.  
If you have any question, please contact Lin at: s3795533 at student dot rmit dot edu dot au.
