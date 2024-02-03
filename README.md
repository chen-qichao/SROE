# Sparsity-Regularized Out-of-distribution Detection

This repository is the implementation of [Improving Energy-based OOD Detection by Sparsity Regularization](https://link.springer.com/chapter/10.1007/978-3-031-05936-0_42) by Qichao Chen, Wenjie Jiang, Kuan Li and Yi Wang. This method is a simple yet effective for improve Energy-based OOD Detection. Our code is modified from [energy_ood](https://github.com/wetliu/energy_ood).

![image](https://github.com/chen-qichao/SROE/blob/main/demo_fig/framework_v2.png)

## Requirements

It is tested under Ubuntu Linux 18.04 and Python 3.7 environment, and requries some packages to be installed:

- PyTorch 1.4.0
- torchvision 0.5.0
- numpy 1.17.2

## Algorithm

![image](https://github.com/chen-qichao/SROE/blob/main/demo_fig/alg1.png)

## Training Pretrained Models

Please download the datasets in folder

```shell
./data/
```

Training pretrained classifier

```shell
python baseline.py cifar10
python baseline.py cifar100
```

Pretrained models are provided in folder

```shell
./CIFAR/snapshots/
```

## Testing and Fine-tuning

Evaluate the pretrained model using energy-based detector

```shell
python test.py --model cifar10_wrn_pretrained --score energy
python test.py --model cifar100_wrn_pretrained --score energy
```

Fine-tune the pretrained model

```shell
python tune.py cifar10 --save ./snapshots/tune_sr
python tune.py cifar100 --save ./snapshots/tune_sr
```

Testing the detection performance of fine-tuned model 

```shell
python test.py --model cifar10_wrn_s1_tune --score energy
python test.py --model cifar100_wrn_s1_tune --score energy
```



## Performance

Our model achieves the following average performance on 6 OOD datasets:

![image](https://github.com/chen-qichao/SROE/blob/main/demo_fig/tab1.png)

![image](https://github.com/chen-qichao/SROE/blob/main/demo_fig/tab3.png)

![image](https://github.com/chen-qichao/SROE/blob/main/demo_fig/tab4.png)



![image](https://github.com/chen-qichao/SROE/blob/main/demo_fig/acc_auc.png)



## Outlier Datasets

These experiments make use of numerous outlier datasets. Links for less common datasets are as follows, [80 Million Tiny Images](http://horatio.cs.nyu.edu/mit/tiny/data/tiny_images.bin) [Textures](https://www.robots.ox.ac.uk/~vgg/data/dtd/), [Places365](http://places2.csail.mit.edu/download.html), [LSUN-C](https://www.dropbox.com/s/fhtsw1m3qxlwj6h/LSUN.tar.gz), [LSUN-R](https://www.dropbox.com/s/moqh2wh8696c3yl/LSUN_resize.tar.gz), [iSUN](https://www.dropbox.com/s/ssz7qxfqae0cca5/iSUN.tar.gz) and [SVHN](http://ufldl.stanford.edu/housenumbers/).

Our **tiny** dataset available at [here](https://drive.google.com/file/d/1zKzzTkbJjODC_y5ZSY8RQAGzzEGqZhuj/view?usp=sharing)

![image](https://github.com/kuan-li/SparsityRegularization/blob/main/demo_fig/tiny.png)

## Citation

     @article{chen2022sparsity,
          title={Improving Energy-based Out-of-distribution Detection by Sparsity Regularization},
          author={Chen, Qichao and Jiang, Wenjie and Li, Kuan and Wang, Yi},
          journal={Pacific-Asia Conference on Knowledge Discovery and Data Mining},
          year={2022}
     } 
     
      @article{chen2024sroe,
          title={Exploring Feature Sparsity for Out-of-distribution Detection},
          author={Chen Qichao, Kuan Li, Zhiyuan Chen, Tomas Maul and Jianping Yin},
          journal={Under Review
          year={2022}
     }
