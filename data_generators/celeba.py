'''CelebA dataset'''
import urllib
import pickle
import numpy as np
from torchvision.utils import make_grid
import matplotlib.pyplot as plt
import torch

def get_celeba(plot_sample=True):
    url = "https://github.com/rll/deepul/raw/master/homeworks/hw2/data/celeb.pkl"
    urllib.request.urlretrieve(url, filename="data\celeba.pkl")

    with open("celeb.pkl", 'rb') as f:
        data = pickle.load(f)

    train_data, test_data = data['train'], data['test']

    # Move dimensions so they fit the channel colors.
    train_data = train_data[:, :, :, [2, 1, 0]].astype(np.float32)
    test_data = test_data[:, :, :, [2, 1, 0]].astype(np.float32)

    if plot_sample == True:
        indices = np.random.choice(len(train_data), replace=False, size=(100,))
        samples = (torch.FloatTensor(train_data[indices]) / 3).permute(0, 3, 1, 2)
        grid_img = make_grid(samples, nrow=10)
        plt.figure()
        plt.title("CelebA samples ")
        plt.imshow(grid_img.permute(1, 2, 0))
        plt.axis('off')

    train_data = np.transpose(train_data, axes=[0, 3, 1, 2]) # NCHW 20000 x 3 x 32 x 32
    test_data = np.transpose(test_data, axes=[0, 3, 1, 2]) # NCHW 6838 x 3 x 32 x 32
    return train_data, test_data

def condition_celeba():
    return "Not implemented yet"

