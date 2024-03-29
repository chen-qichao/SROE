# -*- coding: utf-8 -*-

import os
import time
import shutil
import argparse

import torch
import numpy as np
import torch.nn as nn
import torch.nn.functional as F
import torchvision.datasets as dset
import torch.backends.cudnn as cudnn
import torchvision.transforms as trn

from models.wrn import WideResNet
from models.resnet import ResNet18
from models.resnet import ResNet34
from models.resnet import ResNet50
from models.resnet import ResNet101
from models.resnet import ResNet152
from models.densenet import DenseNet3
from models.allconv import AllConvNet


# go through rigamaroo to do ...utils.display_results import show_performance
if __package__ is None:
    import sys
    from os import path

    sys.path.append(path.dirname(path.dirname(path.abspath(__file__))))
    from utils.validation_dataset import validation_split


parser = argparse.ArgumentParser(description='Trains a CIFAR Classifier',
                                 formatter_class=argparse.ArgumentDefaultsHelpFormatter)
parser.add_argument('dataset', type=str, choices=['cifar10', 'cifar100'],
                    help='Choose between CIFAR-10, CIFAR-100.')
parser.add_argument('--model', '-m', type=str, default='allconv',
                    choices=['allconv', 'wrn', 'resnet', 'densenet'], help='Choose architecture.')
parser.add_argument('--calibration', '-c', action='store_true',
                    help='Train a model to be used for calibration. This holds out some data for validation.')
# Optimization options
parser.add_argument('--epochs', '-e', type=int, default=100, help='Number of epochs to train.')
parser.add_argument('--learning_rate', '-lr', type=float, default=0.1, help='The initial learning rate.')
parser.add_argument('--batch_size', '-b', type=int, default=128, help='Batch size.')
parser.add_argument('--test_bs', type=int, default=200)
parser.add_argument('--momentum', type=float, default=0.9, help='Momentum.')
parser.add_argument('--decay', '-d', type=float, default=0.0005, help='Weight decay (L2 penalty).')

# Resnet Architecture
parser.add_argument('--resnet_layers', default=34, type=int, choices=[18, 34, 50, 101, 152], help='total number of resnet layers')

# WRN Architecture
parser.add_argument('--layers', default=40, type=int, help='total number of layers')
parser.add_argument('--widen-factor', default=2, type=int, help='widen factor')
parser.add_argument('--droprate', default=0.3, type=float, help='dropout probability')

# Checkpoints
parser.add_argument('--save', '-s', type=str, default='./snapshots/test', help='Folder to save checkpoints.')
parser.add_argument('--load', '-l', type=str, default='', help='Checkpoint path to resume / test.')
parser.add_argument('--test', '-t', action='store_true', help='Test only flag.')

# Acceleration
parser.add_argument('--ngpu', type=int, default=1, help='0 = CPU.')
parser.add_argument('--prefetch', type=int, default=4, help='Pre-fetching threads.')

parser.add_argument('--machine', type=str, default='local', choices=['acm', 'local'], help='Choose machine.')

args = parser.parse_args()

state = {k: v for k, v in args._get_kwargs()}
print(state)

torch.manual_seed(1)
np.random.seed(1)

if args.machine == 'acm':
    data_path = '/path/data/'
    cifar_path = data_path + 'cifar'
    # auxiliary_root = '/opt/data/private/ood/data/80million/tiny_images.bin'

if args.machine == 'local':
    data_path = '/path/data/'
    cifar_path = data_path + 'cifar'
    # auxiliary_root = '/data1/church/ood/data/80million/tiny_images.bin'

# mean and standard deviation of channels of CIFAR-10 images
mean = [x / 255 for x in [125.3, 123.0, 113.9]]
std = [x / 255 for x in [63.0, 62.1, 66.7]]

train_transform = trn.Compose([trn.RandomHorizontalFlip(), trn.RandomCrop(32, padding=4),
                               trn.ToTensor(), trn.Normalize(mean, std)])
test_transform = trn.Compose([trn.ToTensor(), trn.Normalize(mean, std)])

if args.dataset == 'cifar10':
    train_data = dset.CIFAR10(cifar_path, train=True, transform=train_transform)
    test_data = dset.CIFAR10(cifar_path, train=False, transform=test_transform)
    num_classes = 10
else:
    train_data = dset.CIFAR100(cifar_path, train=True, transform=train_transform)
    test_data = dset.CIFAR100(cifar_path, train=False, transform=test_transform)
    num_classes = 100


calib_indicator = ''
if args.calibration:
    train_data, val_data = validation_split(train_data, val_share=0.1)
    calib_indicator = '_calib'

train_loader = torch.utils.data.DataLoader(
    train_data, batch_size=args.batch_size, shuffle=True,
    num_workers=args.prefetch, pin_memory=True)
test_loader = torch.utils.data.DataLoader(
    test_data, batch_size=args.test_bs, shuffle=False,
    num_workers=args.prefetch, pin_memory=True)


# Create model
if args.model == 'allconv':
    net = AllConvNet(num_classes)
elif args.model == 'resnet':
    # net = ResNet18(num_classes)
    if args.resnet_layers == 18:
        args.model = 'resnet18'
        net = ResNet18(num_classes=num_classes)

    elif args.resnet_layers == 34:
        args.model = 'resnet34'
        net = ResNet34(num_classes=num_classes)

    elif args.resnet_layers == 50:
        args.model = 'resnet50'
        net = ResNet50(num_classes=num_classes)

    elif args.resnet_layers == 101:
        args.model = 'resnet101'
        net = ResNet101(num_classes=num_classes)

    elif args.resnet_layers == 152:
        args.model = 'resnet152'
        net = ResNet152(num_classes=num_classes)

    else:
        raise Exception('invalid resnet_layers')

elif args.model == 'resnext':
    net = resnext29(num_classes=num_classes)

elif args.model == 'densenet':
    net = DenseNet3(100, int(num_classes))
elif args.model == 'wrn':
    net = WideResNet(args.layers, num_classes, args.widen_factor, dropRate=args.droprate)
else:
    raise Exception('unknown network architecture: {}'.format(args.model))


print('\nThe number of model parameters: {}\n'.format(sum([p.data.nelement() for p in net.parameters()])))


start_epoch = 0

# Restore model if desired
if args.load != '':
    for i in range(1000 - 1, -1, -1):
        model_name = os.path.join(args.load, args.dataset + calib_indicator + '_' + args.model +
                                  '_baseline_epoch_' + str(i) + '.pt')
        if os.path.isfile(model_name):
            net.load_state_dict(torch.load(model_name))
            print('Model restored! Epoch:', i)
            start_epoch = i + 1
            break
    if start_epoch == 0:
        assert False, "could not resume"

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
        args.epochs * len(train_loader),
        1,  # since lr_lambda computes multiplicative factor
        1e-6 / args.learning_rate))


# /////////////// Training ///////////////

def train():
    net.train()  # enter train mode
    loss_avg = 0.0
    for data, target in train_loader:
        data, target = data.cuda(), target.cuda()

        # forward
        x = net(data)
        # backward
        optimizer.zero_grad()
        loss = F.cross_entropy(x, target)
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
            output = net(data)
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

with open(os.path.join(args.save, args.dataset + calib_indicator + '_' + args.model +
                                  '_pretrained_training_results.csv'), 'w') as f:
    f.write('epoch,time(s),train_loss,test_loss,test_error(%)\n')

print('Beginning Training\n')

# Main loop
best_acc = 0

for epoch in range(start_epoch, args.epochs):
    state['epoch'] = epoch

    begin_epoch = time.time()

    train()
    test()

    # Save model
    torch.save(net.state_dict(),
               os.path.join(args.save, args.dataset + calib_indicator + '_' + args.model +
                            '_pretrained_epoch_' + str(epoch) + '.pt'))
    # Let us not waste space and delete the previous model
    prev_path = os.path.join(args.save, args.dataset + calib_indicator + '_' + args.model +
                             '_pretrained_epoch_' + str(epoch - 1) + '.pt')
    if os.path.exists(prev_path): os.remove(prev_path)

    # Show results

    with open(os.path.join(args.save, args.dataset + calib_indicator + '_' + args.model +
                                      '_pretrained_training_results.csv'), 'a') as f:
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

    #  Saving best model
    test_acc = state['test_accuracy']
    is_best = test_acc > best_acc
    best_acc = max(test_acc, best_acc)

    save_path = os.path.join(args.save, args.dataset + calib_indicator + '_' + args.model  +
                            '_pretrained_epoch_' + str(epoch) + '.pt')

    if is_best:
        shutil.copyfile(save_path, os.path.join(args.save, args.dataset + calib_indicator + '_' + args.model  +
                            '_pretrained_best' + '.pt'))
