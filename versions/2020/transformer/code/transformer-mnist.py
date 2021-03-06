import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import torchvision.datasets as datasets
import torchvision.transforms as transforms
import numpy as np

import datetime
import argparse
import matplotlib.pyplot as plt
import matplotlib

from PIL import Image
from vit_pytorch import ViT
from ui import AverageMeter, accuracy, progress_bar

class CNNModel(nn.Module):

    def __init__(self, n_classes=10):
        super(CNNModel, self).__init__()
        # (channel, filters, kernel_size)
        self.classifier = nn.Sequential(
            nn.Conv2d(1, 64, 3),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(64, 64, 3),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(64, 64, 3),
            nn.Dropout(0.2),
            nn.Flatten(),
            nn.Linear(64 * 3 * 3, n_classes),
        )

    def forward(self, x):
        x = self.classifier(x)
        return x

def train(args,
          model, 
          device, 
          train_loader, 
          test_loader, 
          optimizer, 
          epoch):

    model.train()
    lr = optimizer.param_groups[0]['lr']
    correct = 0
    total = 0
    losses = AverageMeter()
    
    for i, data in enumerate(train_loader):
        inputs, labels = data[0].to(device), data[1].to(device)
        optimizer.zero_grad()
        outputs = model(inputs)
        loss = nn.CrossEntropyLoss()(outputs, labels)
        loss.backward()
        optimizer.step()
        losses.update(loss.float().mean().item())

        _, predicted = outputs.max(1)
        total += labels.size(0)
        correct += predicted.eq(labels).sum().item()
        acc = correct * 100. / total

        progress_bar(i,
                    len(train_loader),
                    '[Epoch %d] CE: %.4f | Top 1 Acc: %0.2f%% | LR: %.2e'
                    % (epoch, losses.avg, acc, lr))

    return test(args, model, device, test_loader)


def test(args, model, device, test_loader):
    model.eval()
    top1 = AverageMeter()
    top5 = AverageMeter()
    with torch.no_grad():
        for i, data in enumerate(test_loader):
            inputs, labels = data[0].to(device), data[1].to(device)
            outputs = model(inputs)

            acc1, acc5 = accuracy(outputs, labels, (1, 5))
            top1.update(acc1[0], inputs.size(0))
            top5.update(acc5[0], inputs.size(0))

            progress_bar(i,
                         len(test_loader),
                         'Test accuracy Top 1: %0.2f%%, Top 5: %0.2f%%'
                         % (top1.avg, top5.avg))
    return top1.avg, top5.avg


class SaveOutput:
    def __init__(self):
        self.outputs = []
                            
    def __call__(self, module, module_in, module_out):
        self.outputs.append(module_out)
                                                    
    def clear(self):
        self.outputs = []

def viz_features(args, model):
    save_output = SaveOutput()
    hook_handles = []
    kernels = []
    n_layers = 0 
    for layer in model.modules():
        if isinstance(layer, torch.nn.modules.conv.Conv2d):
            handle = layer.register_forward_hook(save_output)
            hook_handles.append(handle)
            kernels.append(layer.weight)
            n_layers += 1

    print(f"Total convolutional layers: {n_layers}")

    image = np.array(Image.open(args.image))
    use_cuda = torch.cuda.is_available()
    device = torch.device("cuda" if use_cuda else "cpu")
    transform = transforms.Compose([transforms.ToTensor(),])
    image = transform(image)
    image = image.to(device)
    image = image.unsqueeze(0)
    pred = model(image)
    features = save_output.outputs

    for layer, data in enumerate(zip(features, kernels)):
        maps, kernel = data
        maps = maps.squeeze().detach().cpu().numpy()
        dim = int( np.sqrt( len(maps) ) )
        title = "Feature maps at CNN layer %d" % layer
        plot_data(args, maps, dim, title)

        kernel = kernel.detach().cpu().numpy()
        kernel = kernel[:,args.feature_num,:,:]
        kernel = kernel.squeeze()
        dim = int( np.sqrt( len(kernel) ) )
        title = "Kernel weights layer %d filter %d" % (layer, args.feature_num)
        plot_data(args, kernel, dim, title)


def plot_data(args, maps, dim, title=""):
    fig = plt.figure(figsize=(10, 10))

    maps = maps - np.amin(maps)
    maps = maps / np.amax(maps)

    axes = []
    for i, m in enumerate(maps):
        ax = plt.subplot(dim, dim, i+1)
        axes.append(ax)
        im = plt.imshow(m, cmap="gray")
        plt.axis('off')
    
    fig.colorbar(im, ax=axes)
    plt.suptitle(title, fontsize=14)
    plt.show()


def main():
    parser = argparse.ArgumentParser(description='PyTorch MNIST Example')
    parser.add_argument('--image',
                        default='dataset/test/0_000.png',
                        help='image to be classified')
    parser.add_argument('--lr',
                        type=float,
                        default=1e-3,
                        metavar='S',
                        help='learning rate (default: 1e-3)')
    parser.add_argument('--batch-size',
                        type=int,
                        default=128,
                        metavar='N',
                        help='input batch size for training (default: 128)')
    parser.add_argument('--epochs',
                        type=int,
                        default=10,
                        metavar='N',
                        help='number of epochs to train (default: 10)')
    parser.add_argument('--layer-num',
                        type=int,
                        default=0,
                        metavar='N',
                        help='which layer to visualize (default: 0)')
    parser.add_argument('--feature-num',
                        type=int,
                        default=0,
                        metavar='N',
                        help='which feature of a layer to visualize (default: 0)')
    parser.add_argument('--train',
                        action='store_true',
                        default=False,
                        help='train the model (default: False)')
    parser.add_argument('--save-model',
                        action='store_true',
                        default=False,
                        help='save the current model (default: False)')
    parser.add_argument('--restore-model',
                        default=None,
                        help='restore & eval this model file (default: False)')
    parser.add_argument('--normalize',
                        action='store_true',
                        default=False,
                        help='normalize input dataset (default: False)')
    parser.add_argument('--cnn',
                        action='store_true',
                        default=False,
                        help='use cnn model instead of transformer (default: False)')
    parser.add_argument('--visualize',
                        action='store_true',
                        default=False,
                        help='plot kernel and feature maps (default: False)')
    
    args = parser.parse_args()
    use_cuda = torch.cuda.is_available()

    kwargs = {'num_workers': 4, 'pin_memory': True} if use_cuda else {}

    if args.normalize:
        transform = transforms.Compose([transforms.ToTensor(),
                                       transforms.Normalize((0.1307,), (0.3081,))])
    else:
        transform = transforms.Compose([transforms.ToTensor()])

    x_train = datasets.MNIST(root='./data',
                             train=True,
                             download=True,
                             transform=transform)

    x_test = datasets.MNIST(root='./data',
                            train=False,
                            download=True,
                            transform=transform)

    DataLoader = torch.utils.data.DataLoader
    train_loader = DataLoader(x_train,
                              shuffle=True,
                              batch_size=args.batch_size,
                              **kwargs)

    test_loader = DataLoader(x_test,
                             shuffle=False,
                             batch_size=args.batch_size,
                             **kwargs)


    use_cuda = torch.cuda.is_available()
    device = torch.device("cuda" if use_cuda else "cpu")
    if args.cnn:
        model = CNNModel().to(device)
    else:
        model = ViT(image_size=28,
                    patch_size=14,
                    num_classes=10,
                    dim=128,
                    depth=6,
                    heads=8,
                    mlp_dim=128,
                    channels=1,
                    ).to(device)

    if torch.cuda.device_count() > 1:
        print("Available GPUs:", torch.cuda.device_count())
        model = nn.DataParallel(model)
    print("Model:", model)
    print("Device:", device)
    optimizer = optim.Adam(model.parameters())
    
    start_time = datetime.datetime.now()
    best_top1 = 0
    best_top5 = 0
    if args.restore_model is not None:
        model.load_state_dict(torch.load(args.restore_model)) 
        best_top1, best_top5 = test(args, model, device, test_loader)
        print("Best Top 1: %0.2f%%, Top 5: %0.2f%%" % (best_top1, best_top5))

    if args.train:
        for epoch in range(1, args.epochs + 1):
            top1, top5 = train(args, model, device, train_loader, test_loader, optimizer, epoch)
            if top1 > best_top1:
                print("New best Top 1: %0.2f%%, Top 5: %0.2f%%" % (top1, top5))
                best_top1 = top1
                best_top5 = top5
                if args.save_model:
                    filename = "cnn-mnist.pth" if args.cnn else "transformer-mnist.pth"
                    torch.save(model.state_dict(), filename)
                    print("Saving best model on file: ", filename)

        print("Best Top 1: %0.2f%%, Top 5: %0.2f%% in %d epochs" % (best_top1, best_top5, args.epochs))

    elapsed_time = datetime.datetime.now() - start_time
    print("Elapsed time (train): %s" % elapsed_time)

    if args.visualize:
        viz_features(args, model)


if __name__ == '__main__':
    main()
