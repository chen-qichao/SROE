# -*- coding: utf-8 -*-

import os
import time
import pickle
import argparse

import torch
import numpy as np
import torch.nn as nn
import torch.nn.functional as F
import torchvision.datasets as dset
import torch.backends.cudnn as cudnn
import torchvision.transforms as trn

from models.wrn_prime import WideResNet
from models.allconv import AllConvNet


if __package__ is None:
    import sys
    from os import path

    sys.path.append(path.dirname(path.dirname(path.abspath(__file__))))
    from utils.tinyimages_80mn_loader import TinyImages
    from utils.validation_dataset import validation_split

parser = argparse.ArgumentParser(description='Tunes a CIFAR Classifier with OE',
                                 formatter_class=argparse.ArgumentDefaultsHelpFormatter)
parser.add_argument('dataset', type=str, choices=['cifar10', 'cifar100'],
                    help='Choose between CIFAR-10, CIFAR-100.')
parser.add_argument('--model', '-m', type=str, default='wrn',
                    choices=['allconv', 'wrn'], help='Choose architecture.')
parser.add_argument('--calibration', '-c', action='store_true',
                    help='Train a model to be used for calibration. This holds out some data for validation.')

# Optimization options
parser.add_argument('--epochs', '-e', type=int, default=10, help='Number of epochs to train.')
parser.add_argument('--learning_rate', '-lr', type=float, default=0.001, help='The initial learning rate.')
parser.add_argument('--batch_size', '-b', type=int, default=128, help='Batch size.')
parser.add_argument('--oe_batch_size', type=int, default=256, help='Batch size.')
parser.add_argument('--test_bs', type=int, default=200)
parser.add_argument('--momentum', type=float, default=0.9, help='Momentum.')
parser.add_argument('--decay', '-d', type=float, default=0.0005, help='Weight decay (L2 penalty).')

# WRN Architecture
parser.add_argument('--layers', default=40, type=int, help='total number of layers')
parser.add_argument('--widen-factor', default=2, type=int, help='widen factor')
parser.add_argument('--droprate', default=0.3, type=float, help='dropout probability')

# Checkpoints
parser.add_argument('--save', '-s', type=str, default='./snapshots/tune_sr', help='Folder to save checkpoints.')
parser.add_argument('--load', '-l', type=str, default='./snapshots/pretrained', help='Checkpoint path to resume / test.')
parser.add_argument('--test', '-t', action='store_true', help='Test only flag.')

# Acceleration
parser.add_argument('--ngpu', type=int, default=1, help='0 = CPU.')
parser.add_argument('--prefetch', type=int, default=4, help='Pre-fetching threads.')

# EG specific
parser.add_argument('--score', type=str, default='OE', help='OE|energy')
parser.add_argument('--seed', type=int, default=1, help='seed for np(tinyimages80M sampling); 1|2|8|100|107')

parser.add_argument('--machine', type=str, default='local', choices=['remote', 'local'], help='Choose machine.')
parser.add_argument('--alpha', type=float, default=0.02, help='hyperparameter alpha.')
parser.add_argument('--beta', type=float, default=0.5, help='hyperparameter beta.')

args = parser.parse_args()

if os.path.isdir(args.save) == False:
    os.mkdir(args.save)
state = {k: v for k, v in args._get_kwargs()}
print(state)

torch.manual_seed(1)
np.random.seed(args.seed)

if args.machine == 'remote':
    data_path = '/opt/data/private/ood/data/'
    cifar_path = data_path + 'cifar'

if args.machine == 'local':
    data_path = '/data1/church/ood/data/'
    cifar_path = data_path + 'cifar'


# mean and standard deviation of channels of CIFAR-10 images
mean = [x / 255 for x in [125.3, 123.0, 113.9]]
std = [x / 255 for x in [63.0, 62.1, 66.7]]

train_transform = trn.Compose([trn.RandomHorizontalFlip(), trn.RandomCrop(32, padding=0),
                               trn.ToTensor(), trn.Normalize(mean, std)])
test_transform = trn.Compose([trn.ToTensor(), trn.Normalize(mean, std)])

if args.dataset == 'cifar10':
    train_data_in = dset.CIFAR10(cifar_path, train=True, transform=train_transform)
    test_data = dset.CIFAR10(cifar_path, train=False, transform=test_transform)
    num_classes = 10
else:
    train_data_in = dset.CIFAR100(cifar_path, train=True, transform=train_transform)
    test_data = dset.CIFAR100(cifar_path, train=False, transform=test_transform)
    num_classes = 100


calib_indicator = ''
if args.calibration:
    train_data_in, val_data = validation_split(train_data_in, val_share=0.1)
    calib_indicator = '_calib'

## tiny-imagenet as ood
# mean and standard deviation of channels of ImageNet images
img_mean = [0.485, 0.456, 0.406]
img_std = [0.229, 0.224, 0.225]

train_out_transform = trn.Compose([trn.RandomHorizontalFlip(), trn.RandomCrop(32, padding=8),
                               trn.ToTensor(), trn.Normalize(img_mean, img_std)])

ood_data = dset.ImageFolder(
    root="../tiny",
    transform=train_out_transform)

# ood_data = TinyImages(transform=trn.Compose(
    # [trn.ToTensor(), trn.ToPILImage(), trn.RandomCrop(32, padding=4),
     # trn.RandomHorizontalFlip(), trn.ToTensor(), trn.Normalize(mean, std)]))


train_loader_in = torch.utils.data.DataLoader(
    train_data_in,
    batch_size=args.batch_size, shuffle=True,
    num_workers=args.prefetch, pin_memory=True)

train_loader_out = torch.utils.data.DataLoader(
    ood_data,
    batch_size=args.oe_batch_size, shuffle=False,
    num_workers=args.prefetch, pin_memory=True)

test_loader = torch.utils.data.DataLoader(
    test_data,
    batch_size=args.batch_size, shuffle=False,
    num_workers=args.prefetch, pin_memory=True)

# Create model
if args.model == 'allconv':
    net = AllConvNet(num_classes)

elif args.model == 'wrn':
    net = WideResNet(args.layers, num_classes, args.widen_factor, dropRate=args.droprate)
else:
    raise Exception('unknown network architecture: {}'.format(args.model))

print('The number of model parameters: {}\n'.format(sum([p.data.nelement() for p in net.parameters()])))

def recursion_change_bn(module):
    if isinstance(module, torch.nn.BatchNorm2d):
        module.track_running_stats = 1
        module.num_batches_tracked = 0
    else:
        for i, (name, module1) in enumerate(module._modules.items()):
            module1 = recursion_change_bn(module1)
    return module

# Restore model
model_found = False
if args.load != '':
    for i in range(1000 - 1, -1, -1):
        
        model_name = os.path.join(args.load, args.dataset + calib_indicator + '_' + args.model +
                                  '_pretrained_epoch_' + str(i) + '.pt')

        # model_name = os.path.join(args.load, args.dataset + calib_indicator + '_' + args.model +
        #                           '_pretrained_best.pt')

        if os.path.isfile(model_name):
            net.load_state_dict(torch.load(model_name))
            print('Model restored! Epoch:', i)
            model_found = True
            break
    if not model_found:
        assert False, "could not find model to restore"

if args.ngpu > 1:
    net = torch.nn.DataParallel(net, device_ids=list(range(args.ngpu)))

if args.ngpu > 0:
    net.cuda()
    torch.cuda.manual_seed(1)

cudnn.benchmark = True  # fire on all cylinders

optimizer = torch.optim.SGD(
    net.parameters(), state['learning_rate'], momentum=state['momentum'],
    weight_decay=state['decay'], nesterov=True)


def cosine_annealing(step, total_steps, lr_max, lr_min):
    return lr_min + (lr_max - lr_min) * 0.5 * (
            1 + np.cos(step / total_steps * np.pi))


scheduler = torch.optim.lr_scheduler.LambdaLR(
    optimizer,
    lr_lambda=lambda step: cosine_annealing(
        step,
        args.epochs * len(train_loader_in),
        1,  # since lr_lambda computes multiplicative factor
        1e-6 / args.learning_rate))


class OELoss(nn.Module):
    def __init__(self):
        super(OELoss, self).__init__()

    def forward(self, x):
        return -(x.mean(1) - torch.logsumexp(x, dim=1)).mean()

oe_criterion = OELoss().cuda()


def train_oe():
    net.train()  # enter train mode
    loss_avg = 0.0

    # start at a random point of the outlier dataset; this induces more randomness without obliterating locality
    # train_loader_out.dataset.offset = np.random.randint(len(train_loader_out.dataset))
    for in_set, out_set in zip(train_loader_in, train_loader_out):
        data = torch.cat((in_set[0], out_set[0]), 0)
        target = in_set[1]
        
        # 正常样本的长度
        in_len = len(in_set[0]) 

        data, target = data.cuda(), target.cuda()

        # forward
        x, vector_feature = net(data)

        optimizer.zero_grad()

        loss = F.cross_entropy(x[:in_len], target)

        sum_feature = torch.sum(abs(vector_feature), dim=1)

        l1_term = torch.mean(sum_feature)
 
        loss += args.alpha* l1_term
   
        # loss += args.beta * -(x[len(in_set[0]):].mean(1) - torch.logsumexp(x[len(in_set[0]):], dim=1)).mean()
        loss += args.beta * oe_criterion(x[len(in_set[0]):])

        # backward
        loss.backward()
        optimizer.step()
        scheduler.step()

        # exponential moving average
        loss_avg = loss_avg * 0.8 + float(loss) * 0.2
    state['train_loss'] = loss_avg


def train():
    net.train()  # enter train mode
    loss_avg = 0.0
    for data, target in train_loader_in:
        data, target = data.cuda(), target.cuda()

        # forward
        x, vector_feature = net(data)

        optimizer.zero_grad()
        loss = F.cross_entropy(x, target)

        sum_feature = torch.sum(abs(vector_feature), dim=1)

        l1_term = torch.mean(sum_feature)
 
        loss += args.alpha* l1_term

        # backward
        loss.backward()
        optimizer.step()
        scheduler.step()

        # exponential moving average
        loss_avg = loss_avg * 0.8 + float(loss) * 0.2

    state['train_loss'] = loss_avg


# test function
def test():
    net.eval()
    loss_avg = 0.0
    correct = 0
    with torch.no_grad():
        for data, target in test_loader:
            data, target = data.cuda(), target.cuda()

            # forward
            output,_ = net(data)
            loss = F.cross_entropy(output, target)

            # accuracy
            pred = output.data.max(1)[1]
            correct += pred.eq(target.data).sum().item()

            # test loss average
            loss_avg += float(loss.data)

    state['test_loss'] = loss_avg / len(test_loader)
    state['test_accuracy'] = correct / len(test_loader.dataset)


if args.test:
    test()
    print(state)
    exit()

# Make save directory
if not os.path.exists(args.save):
    os.makedirs(args.save)
if not os.path.isdir(args.save):
    raise Exception('%s is not a dir' % args.save)

# with open(os.path.join(args.save, args.dataset + calib_indicator + '_' + args.model + '_s' + str(args.seed) + 
#                                   '_' + save_info+'_training_results.csv'), 'w') as f:

with open(os.path.join(args.save, args.dataset + calib_indicator + '_' + args.model + '_s' + str(args.seed) + 
                                  '_tune_training_results.csv'), 'w') as f:

    f.write('epoch,time(s),train_loss,test_loss,test_error(%)\n')

print('Beginning Training\n')

# Main loop
for epoch in range(0, args.epochs):
    state['epoch'] = epoch

    begin_epoch = time.time()

    # tune with Sparsity Regularization
    train()

    # tune with SROE
    # train_oe()

    test()
 
    # Save model
    torch.save(net.state_dict(),
               os.path.join(args.save, args.dataset + calib_indicator + '_' + args.model + '_s' + str(args.seed) +  
                            '_tune_epoch_' + str(epoch) + '.pt'))
    
               # Let us not waste space and delete the previous model
    prev_path = os.path.join(args.save, args.dataset + calib_indicator + '_' + args.model + '_s' + str(args.seed) +  
                             '_tune_epoch_'+ str(epoch - 1) + '.pt')
    if os.path.exists(prev_path): os.remove(prev_path)

    # Show results
    with open(os.path.join(args.save, args.dataset + calib_indicator + '_' + args.model + '_s' + str(args.seed) +  
                                      '_tune_training_results.csv'), 'a') as f:
        f.write('%03d,%05d,%0.6f,%0.5f,%0.2f\n' % (
            (epoch + 1),
            time.time() - begin_epoch,
            state['train_loss'],
            state['test_loss'],
            100 - 100. * state['test_accuracy'],
        ))

    # # print state with rounded decimals
    # print({k: round(v, 4) if isinstance(v, float) else v for k, v in state.items()})

    print('Epoch {0:3d} | Time {1:5d} | Train Loss {2:.4f} | Test Loss {3:.3f} | Test Error {4:.2f}'.format(
        (epoch + 1),
        int(time.time() - begin_epoch),
        state['train_loss'],
        state['test_loss'],
        100 - 100. * state['test_accuracy'])
    )
