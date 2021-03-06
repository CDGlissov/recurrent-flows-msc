import torch
import torch.nn as nn
from Utils import get_layer_size, Flatten, UnFlatten, set_gpu, batch_reduce
import torch.distributions as td
from Utils import ConvLSTM, NormLayer
from Utils import DiscretizedMixtureLogits, DiscretizedMixtureLogits_1d
import numpy as np
device = set_gpu(True)

#https://medium.com/@aminamollaysa/summary-of-the-recurrent-latent-variable-model-vrnn-4096b52e731
class SRNN(nn.Module):
    def __init__(self, args):
      super(SRNN, self).__init__()

      norm_type = args.norm_type
      self.batch_size = args.batch_size
      self.u_dim = args.condition_dim
      self.a_dim = args.a_dim
      self.x_dim = args.x_dim
      self.enable_smoothing = args.enable_smoothing
      h_dim = args.h_dim
      z_dim = args.z_dim
      self.h_dim = h_dim
      self.z_dim = z_dim
      self.loss_type = args.loss_type
      self.beta = 1
      bu, cu, hu, wu = self.u_dim
      bx, cx, hx, wx = self.x_dim
      self.mse_criterion = nn.MSELoss(reduction='none')
      self.res_q = args.res_q
      self.bits=args.n_bits
      self.dequantize = args.dequantize
      self.preprocess_range = args.preprocess_range
      self.n_logistics = args.n_logistics

      # Remember to downscale more when using 64x64. Overall the net should probably increase in size when using
      # 64x64 images
      self.phi_x_t_channels = 256
      self.phi_x_t = nn.Sequential(
          nn.Conv2d(cx, 64, kernel_size=3, stride=2, padding=1),#32
          NormLayer(64, norm_type),
          nn.ReLU(),
          nn.Conv2d(64, 128, kernel_size=3, stride=2, padding=1),#16
          NormLayer(128, norm_type),
          nn.ReLU(),
          nn.Conv2d(128, 256, kernel_size=3, stride=2, padding=1),#8
          NormLayer(256, norm_type),
          nn.ReLU(),
          nn.Conv2d(256, self.phi_x_t_channels, kernel_size=3, stride=1, padding=1),
          NormLayer(self.phi_x_t_channels, norm_type),
          nn.ReLU(),
        )
      h, w = get_layer_size([hu, wu], kernels=[3, 3,3], paddings=[1, 1, 1], strides=[2, 2,2],
                        dilations=[1, 1,1])
      self.h = h
      self.w = w

      # Extractor of z
      phi_z_channels = 128
      self.phi_z = nn.Sequential(
        nn.Linear(z_dim, phi_z_channels*h*w),
        nn.ReLU(),
        nn.Linear(phi_z_channels*h*w, phi_z_channels*h*w),
        nn.ReLU(),
        UnFlatten(phi_z_channels, h, w),
        nn.Conv2d(phi_z_channels, phi_z_channels, kernel_size = 3, stride = 1, padding = 1),
        NormLayer(phi_z_channels, norm_type),
        nn.ReLU()
        ) #4x4

      # Encoder structure
      if self.enable_smoothing:
          self.enc = nn.Sequential(
            nn.Conv2d(phi_z_channels + self.a_dim, 256,  kernel_size=3, stride=2, padding=1),
            NormLayer(256, norm_type),
            nn.ReLU(),
            Flatten(),
            )
      else:
          self.enc = nn.Sequential(
            nn.Conv2d(phi_z_channels + self.h_dim + self.phi_x_t_channels, 256,  kernel_size=3, stride=2, padding=1),
            NormLayer(256, norm_type),
            nn.ReLU(),
            Flatten(),
            )

      self.enc_mean =  nn.Sequential(
        nn.Linear((256)*h//2*w//2, 512),
        nn.ReLU(),
        nn.Linear(512, 256),
        nn.ReLU(),
        nn.Linear(256, z_dim), #maybe tanh here?
        )

      self.enc_std = nn.Sequential(
        nn.Linear((256)*h//2*w//2, 512),
        nn.ReLU(),
        nn.Linear(512, 256),
        nn.ReLU(),
        nn.Linear(256, z_dim),
        nn.Softplus()
        )

      # Prior structure
      self.prior = nn.Sequential(
        nn.Conv2d(h_dim + phi_z_channels, 256, kernel_size = 3, stride = 2, padding = 1),
        NormLayer(256, norm_type),
        nn.ReLU(),
        Flatten(),
        )

      self.prior_mean = nn.Sequential(
        nn.Linear((256)*h//2*w//2, 512),
        nn.ReLU(),
        nn.Linear(512, 256),
        nn.ReLU(),
        nn.Linear(256, z_dim),
        )

      self.prior_std = nn.Sequential(
        nn.Linear((256)*h//2*w//2, 512),
        nn.ReLU(),
        nn.Linear(512, 256),
        nn.ReLU(),
        nn.Linear(256, z_dim),
        nn.Softplus()
        )

      # Decoder structure
      self.dec = nn.Sequential(
            nn.ConvTranspose2d(h_dim + phi_z_channels, 512, kernel_size=4, stride=2, padding=1, output_padding=0),
            NormLayer(512, norm_type),
            nn.ReLU(),
            nn.Conv2d(512, 256,  kernel_size=3, stride=1, padding=1),
            NormLayer(256, norm_type),
            nn.ReLU(),
            nn.ConvTranspose2d(256, 64, kernel_size=4, stride=2, padding=1, output_padding=0),
            NormLayer(64, norm_type),
            nn.ReLU(),
            nn.Conv2d(64, 64,  kernel_size=3, stride=1, padding=1),
            NormLayer(64, norm_type),
            nn.ReLU(),
            nn.ConvTranspose2d(64, 32, kernel_size=4, stride=2, padding=1, output_padding=0),
            NormLayer(32, norm_type),
            nn.ReLU(),
        )

      #self.dec_std = nn.Sequential(nn.Conv2d(32, cx,  kernel_size=3, stride=1, padding=1),
      #                         nn.Softplus())

      self.z_0 = nn.Parameter(torch.zeros(self.batch_size, z_dim))
      self.z_0x = nn.Parameter(torch.zeros(self.batch_size, z_dim))

      self.h_0 = nn.Parameter(torch.zeros(self.batch_size, self.h_dim, h, w))
      self.c_0 = nn.Parameter(torch.zeros(self.batch_size, self.h_dim, h, w))

      self.a_0 = nn.Parameter(torch.zeros(self.batch_size, self.a_dim, h, w))
      self.ca_0 = nn.Parameter(torch.zeros(self.batch_size, self.a_dim, h, w))

      #LSTM
      self.lstm_h = ConvLSTM(in_channels = self.phi_x_t_channels,
                           hidden_channels=self.h_dim,
                           kernel_size=[3, 3],
                           bias=True,
                           peephole=True)

      self.lstm_a = ConvLSTM(in_channels = self.phi_x_t_channels + self.h_dim,
                           hidden_channels=self.h_dim,
                           kernel_size=[3, 3],
                           bias=True,
                           peephole=True)
      if self.loss_type=="mol":
        if cx > 1:
          self.dec_mean = nn.Sequential(nn.Conv2d(32, self.n_logistics*10,  kernel_size=3, stride=1, padding=1))
          self.likelihood = DiscretizedMixtureLogits(self.n_logistics)
        else:
          self.dec_mean = nn.Sequential(nn.Conv2d(32, self.n_logistics*3,  kernel_size=3, stride=1, padding=1))
          self.likelihood = DiscretizedMixtureLogits_1d(self.n_logistics)
      else:
        self.variance = nn.Parameter(torch.ones([1]))
        if self.preprocess_range =='0.5':
          self.dec_mean = nn.Sequential(nn.Conv2d(32, cx,  kernel_size=3, stride=1, padding=1),
                                  nn.Tanh()
                                  )
        elif self.preprocess_range =='1.0':
          self.dec_mean = nn.Sequential(nn.Conv2d(32, cx,  kernel_size=3, stride=1, padding=1),
                                 nn.Sigmoid()
                                 )

      self.D = args.num_shots + 1 # Plus one as that is more intuative
      self.overshot_w = args.overshot_w #Weight for overshoots.



    def get_inits(self):
      loss = 0
      kl_loss = 0
      nll_loss = 0
      return self.h_0, self.c_0, self.z_0, self.z_0x, self.a_0, self.ca_0, loss, kl_loss, nll_loss

    def uniform_binning_correction(self, x):
        n_bits = self.bits
        b, c, h, w = x.size()
        n_bins = 2 ** n_bits
        chw = c * h * w
        x_noise = x + torch.zeros_like(x).uniform_(0, 1.0 / n_bins)
        objective = -np.log(n_bins) * chw * torch.ones(b, device=x.device)
        return x_noise, objective

    def loss(self, xt):

      b, t, c, h, w = xt.shape
      hprev, cprev, zprev, zprevx, aprev, caprev, loss, kl_loss, nll_loss = self.get_inits()

      store_ht = torch.zeros((t-1, *hprev.shape)).cuda()
      store_at = torch.zeros((t-1, *aprev.shape)).cuda()
      store_x_features = torch.zeros((self.batch_size, t, self.phi_x_t_channels, self.h, self.w)).cuda()
      #Find ht
      for i in range(0, t):
          store_x_features[:, i, :, :, :] = self.phi_x_t(xt[:, i, :, :, :])

      for i in range(1, t):
        ut = store_x_features[:, i-1, :, :, :]
        _, ht, ct = self.lstm_h(ut.unsqueeze(1), hprev, cprev)
        store_ht[i-1,:,:,:,:] = ht
        hprev = ht
        cprev = ct

      if self.enable_smoothing:
          #Find at
          for i in range(1, t):
            xt_features = store_x_features[:, t-i, :, :, :]
            lstm_a_input = torch.cat([store_ht[t-i-1,:,:,:,:], xt_features], 1)
            _, at, c_at = self.lstm_a(lstm_a_input.unsqueeze(1), aprev, caprev)
            aprev = at
            caprev = c_at
            store_at[t-i-1,:,:,:,:] = at

      store_ztx_mean = torch.zeros((t-1, *zprevx.shape)).cuda()
      store_ztx_std = torch.zeros((t-1, *zprevx.shape)).cuda()
      store_ztx = torch.zeros((t-1, *zprev.shape)).cuda()
      for i in range(1, t):
        ht = store_ht[i-1,:,:,:,:]


        if self.enable_smoothing:
            at = store_at[i-1,:,:,:,:]
            enc_t = self.enc(torch.cat([at, self.phi_z(zprevx)], 1))
        else:
            xt_features = self.phi_x_t(xt[:, i, :, :, :])
            enc_t = self.enc(torch.cat([ht, self.phi_z(zprevx), xt_features], 1))
        enc_std_t = self.enc_std(enc_t)

        if self.res_q:
            prior_t = self.prior(torch.cat([ht, self.phi_z(zprevx)],1)) ## Notice zprevx here, this is intentional
            prior_mean_t = self.prior_mean(prior_t)

            enc_mean_t = prior_mean_t + self.enc_mean(enc_t)
        else:
            prior_t = self.prior(torch.cat([ht, self.phi_z(zprev)],1))
            prior_mean_t = self.prior_mean(prior_t)

            enc_mean_t = self.enc_mean(enc_t)


        prior_std_t = self.prior_std(prior_t)
        prior_dist = td.Normal(prior_mean_t, prior_std_t)

        enc_dist = td.Normal(enc_mean_t, enc_std_t)

        z_tx = enc_dist.rsample()
        z_t = prior_dist.rsample()

        store_ztx_mean[i-1,:,:] = enc_mean_t
        store_ztx_std[i-1,:,:] = enc_std_t
        store_ztx[i-1,:,:] = z_tx
        store_ztx[i-1,:,:] = zprevx


        dec_t = self.dec(torch.cat([ht, self.phi_z(z_tx)], 1))
        dec_mean_t = self.dec_mean(dec_t)

        zprevx = z_tx
        zprev = z_t
        if self.D == 1:
            kl_loss = kl_loss + self.beta * td.kl_divergence(enc_dist, prior_dist)


        if self.loss_type == "bernoulli":
            nll_loss = nll_loss - batch_reduce(td.Bernoulli(probs=dec_mean_t).log_prob(xt[:, i, :, :, :]))
        elif self.loss_type == "gaussian":

            if self.dequantize:
              x, nll_unif = self.uniform_binning_correction(xt[:, i, :, :, :])
            else:
              x = xt[:, i, :, :, :]

            nll_loss = nll_loss - batch_reduce(td.Normal(dec_mean_t, nn.Softplus()(self.variance)*torch.ones_like(dec_mean_t)).log_prob(x))
            nll_loss = nll_loss - nll_unif

        elif self.loss_type == "mse":
            nll_loss = nll_loss + batch_reduce(self.mse_criterion(dec_mean_t, xt[:, i, :, :, :]))
        elif self.loss_type == "mol":
            nll_loss = nll_loss - batch_reduce(self.likelihood(logits = dec_mean_t).log_prob(xt[:, i, :, :, :]))
        else:
            print("undefined loss")
      ## Disclaimer is not entirely sure how this connect with res_q inference
      if self.D > 1: # is the number of over samples, if D=1 no over shooting will happen.

          overshot_w = self.overshot_w # Weight of overshot.
          Dinit = self.D
          kl_loss = 0

          for i in range(1, t):
              overshot_loss = 0
              idt = i-1 # index t, Does this to make index less confusing
              zprev = store_ztx[idt, : , :]
              D = min(t-i, Dinit) #Do this so that for ts at t-D still do overshoting but with less overshooting # Dont know if this is the correct way to do it but makes sense
              for d in range(0, D): # D is the number of overshootes in paper 1=< d <= D. We do 0<=d<D so now a index offset, but is still the same..
                  ht = store_ht[idt + d, :, :, :, :] # So find the ht for t + d
                  prior_t = self.prior(torch.cat([ht, self.phi_z(zprev)],1))
                  prior_mean_t = self.prior_mean(prior_t)
                  prior_std_t = self.prior_std(prior_t)
                  prior_dist = td.Normal(prior_mean_t, prior_std_t)
                  zprev = prior_dist.rsample()
                  enc_mean = store_ztx_mean[idt + d, :, :]
                  enc_std = store_ztx_std[idt + d, :, :]
                  if d > 0:
                      # .detach() to stop gradients from encoder, such that the encoder does not conform to the prior, but still to recon loss
                      # They do this in the paper for d>0.
                      enc_mean = enc_mean.detach().clone()
                      enc_std = enc_std.detach().clone()
                  enc_dist = td.Normal(enc_mean, enc_std)
                  overshot_loss = overshot_loss + overshot_w * td.kl_divergence(enc_dist, prior_dist)
              kl_loss = kl_loss + 1/D * overshot_loss * self.beta


      return batch_reduce(kl_loss).mean(), nll_loss.mean()


    def predict(self, xt, n_predictions, n_conditions):
      b, t, c, h, w = xt.shape

      assert n_conditions <= t, "n_conditions > t, number of conditioned frames is greater than number of frames"

      predictions = torch.zeros((n_predictions, *xt[:,0,:,:,:].shape))
      true_x = torch.zeros((n_conditions, *xt[:,0,:,:,:].shape))
      hprev, cprev, zprev, zprevx, aprev, caprev, _, _, _ = self.get_inits()

      store_ht = torch.zeros((t-1, *hprev.shape)).cuda()
      true_x[0,:,:,:,:] = xt[:, 0, :, :, :].detach()

      #Find ht
      for i in range(1, n_conditions):
        ut = self.phi_x_t(xt[:, i-1, :, :, :])
        _, ht, ct = self.lstm_h(ut.unsqueeze(1), hprev, cprev)
        store_ht[i-1,:,:,:,:] = ht
        hprev = ht
        cprev = ct

      #Find encoder samples, should we add res_q here? #add warmup with resq
      for i in range(1, n_conditions):
        ht = store_ht[i-1,:,:,:,:]
        prior_t = self.prior(torch.cat([ht, self.phi_z(zprev)],1))
        prior_mean_t = self.prior_mean(prior_t)
        prior_std_t = self.prior_std(prior_t)
        prior_dist = td.Normal(prior_mean_t, prior_std_t)
        z_t = prior_dist.rsample()
        zprev = z_t
        true_x[i,:,:,:,:] = xt[:, i, :, :, :].detach()

      prediction = xt[:,n_conditions-1,:,:,:]

      for i in range(0, n_predictions):
        ut = self.phi_x_t(prediction)

        _, ht, ct = self.lstm_h(ut.unsqueeze(1), hprev, cprev)

        prior_t = self.prior(torch.cat([ht, self.phi_z(zprev)],1))
        prior_mean_t = self.prior_mean(prior_t)
        prior_std_t = self.prior_std(prior_t)
        prior_dist = td.Normal(prior_mean_t, prior_std_t)

        z_t = prior_dist.rsample()

        dec_t = self.dec(torch.cat([ht, self.phi_z(z_t)], 1))
        dec_mean_t = self.dec_mean(dec_t)
        if self.loss_type == "mol":
          dec_mean_t=self.likelihood(logits = dec_mean_t).sample()
        prediction = dec_mean_t
        zprev = z_t
        hprev = ht
        cprev = ct
        predictions[i,:,:,:,:] = prediction.data
      return true_x, predictions

    def reconstruct(self, xt):
      b, t, c, h, w = xt.shape

      recons = torch.zeros((t, *xt[:,0,:,:,:].shape))
      hprev, cprev, zprev, zprevx, aprev, caprev, _, _, _ = self.get_inits()

      store_ht = torch.zeros((t-1, *hprev.shape)).cuda()
      store_at = torch.zeros((t-1, *hprev.shape)).cuda()

      #Find ht
      for i in range(1, t):
        ut = self.phi_x_t(xt[:, i-1, :, :, :])
        _, ht, ct = self.lstm_h(ut.unsqueeze(1), hprev, cprev)
        store_ht[i-1,:,:,:,:] = ht
        hprev = ht
        cprev = ct

      #Find at
      if self.enable_smoothing:
          for i in range(1, t):
            xt_features = self.phi_x_t(xt[:, t-i, :, :, :])
            lstm_a_input = torch.cat([store_ht[t-i-1,:,:,:,:], xt_features], 1)
            _, at, c_at = self.lstm_a(lstm_a_input.unsqueeze(1), aprev, caprev)
            aprev = at
            caprev = c_at
            store_at[t-i-1,:,:,:,:] = at

      for i in range(1, t):
        ht = store_ht[i-1,:,:,:,:]
        if self.enable_smoothing:
            at = store_at[i-1,:,:,:,:]
            enc_t = self.enc(torch.cat([at, self.phi_z(zprevx)], 1))
        else:
            xt_features = self.phi_x_t(xt[:, i, :, :, :])
            enc_t = self.enc(torch.cat([ht, self.phi_z(zprevx), xt_features], 1))

        if self.res_q:
            prior_t = self.prior(torch.cat([ht, self.phi_z(zprevx)],1))
            prior_mean_t = self.prior_mean(prior_t)
            enc_mean_t = prior_mean_t + self.enc_mean(enc_t)
        else:
            enc_mean_t = self.enc_mean(enc_t)

        enc_std_t = self.enc_std(enc_t)
        enc_dist = td.Normal(enc_mean_t, enc_std_t)
        z_tx = enc_dist.rsample()

        dec_t = self.dec(torch.cat([ht, self.phi_z(z_tx)], 1))
        dec_mean_t = self.dec_mean(dec_t)
        if self.loss_type == "mol":
          dec_mean_t=self.likelihood(logits = dec_mean_t).sample()
        zprevx = z_tx
        recons[i,:,:,:,:] = dec_mean_t.detach()

      return recons

    def sample(self, xt, n_samples):
      b, t, c, h, w = xt.shape

      samples = torch.zeros((n_samples, b,c,h,w))
      hprev, cprev, zprev, zprevx, _, _, _, _, _ = self.get_inits()
      condition = xt[:, 0, :, :, :]

      for i in range(0, n_samples):
        ut = self.phi_x_t(condition)
        _, ht, ct = self.lstm_h(ut.unsqueeze(1), hprev, cprev)
        prior_t = self.prior(torch.cat([ht, self.phi_z(zprev)],1))
        prior_mean_t = self.prior_mean(prior_t)
        prior_std_t = self.prior_std(prior_t)
        prior_dist = td.Normal(prior_mean_t, prior_std_t)

        z_t = prior_dist.rsample()

        dec_t = self.dec(torch.cat([ht, self.phi_z(z_t)], 1))
        dec_mean_t = self.dec_mean(dec_t)
        if self.loss_type == "mol":
          dec_mean_t=self.likelihood(logits = dec_mean_t).sample()
        condition = dec_mean_t
        zprev = z_t
        hprev = ht
        cprev=ct
        samples[i,:,:,:,:] = dec_mean_t.data

      return samples

    def elbo_importance_weighting(self, xt, K):

      b, t, c, h, w = xt.shape
      hprev, cprev, zprev, zprevx, aprev, caprev, _,_,_ = self.get_inits()
      loss = 0
      store_ht = torch.zeros((t-1, *hprev.shape)).cuda()
      store_at = torch.zeros((t-1, *aprev.shape)).cuda()
      store_x_features = torch.zeros((self.batch_size, t, self.phi_x_t_channels, self.h, self.w)).cuda()
      #Find ht
      for i in range(0, t):
          store_x_features[:, i, :, :, :] = self.phi_x_t(xt[:, i, :, :, :])

      for i in range(1, t):
        ut = store_x_features[:, i-1, :, :, :]
        _, ht, ct = self.lstm_h(ut.unsqueeze(1), hprev, cprev)
        store_ht[i-1,:,:,:,:] = ht
        hprev = ht
        cprev = ct

      if self.enable_smoothing:
          #Find at
          for i in range(1, t):
            xt_features = store_x_features[:, t-i, :, :, :]
            lstm_a_input = torch.cat([store_ht[t-i-1,:,:,:,:], xt_features], 1)
            _, at, c_at = self.lstm_a(lstm_a_input.unsqueeze(1), aprev, caprev)
            aprev = at
            caprev = c_at
            store_at[t-i-1,:,:,:,:] = at

      for i in range(1, t):
        logpzs = torch.empty(size=(K, self.batch_size))
        logqzxs = torch.empty(size=(K, self.batch_size))
        lpx_Gz_obss = torch.empty(size=(K, self.batch_size))
        ht = store_ht[i-1,:,:,:,:]
        for k in range(0, K):

          if self.enable_smoothing:
              at = store_at[i-1,:,:,:,:]
              enc_t = self.enc(torch.cat([at, self.phi_z(zprevx)], 1))
          else:
              xt_features = self.phi_x_t(xt[:, i, :, :, :])
              enc_t = self.enc(torch.cat([ht, self.phi_z(zprevx), xt_features], 1))
          enc_std_t = self.enc_std(enc_t)

          if self.res_q:
              prior_t = self.prior(torch.cat([ht, self.phi_z(zprevx)],1)) ## Notice zprevx here, this is intentional
              prior_mean_t = self.prior_mean(prior_t)

              enc_mean_t = prior_mean_t + self.enc_mean(enc_t)
          else:
              prior_t = self.prior(torch.cat([ht, self.phi_z(zprev)],1))
              prior_mean_t = self.prior_mean(prior_t)

              enc_mean_t = self.enc_mean(enc_t)


          prior_std_t = self.prior_std(prior_t)
          prior_dist = td.Normal(prior_mean_t, prior_std_t)

          enc_dist = td.Normal(enc_mean_t, enc_std_t)

          z_tx = enc_dist.rsample()
          z_t = prior_dist.rsample()

          dec_t = self.dec(torch.cat([ht, self.phi_z(z_tx)], 1))

          dec_mean_t = self.dec_mean(dec_t)


          if self.loss_type == "bernoulli":
              lpx_Gz_obs = - batch_reduce(td.Bernoulli(probs=dec_mean_t).log_prob(xt[:, i, :, :, :]))
          elif self.loss_type == "gaussian":

              if self.dequantize:
                  x, nll_unif = self.uniform_binning_correction(xt[:, i, :, :, :])
              else:
                  x = xt[:, i, :, :, :]

              lpx_Gz_obs = - batch_reduce(td.Normal(dec_mean_t, nn.Softplus()(self.variance)*torch.ones_like(dec_mean_t)).log_prob(x))
              lpx_Gz_obs = lpx_Gz_obs - nll_unif

          elif self.loss_type == "mse":
              lpx_Gz_obs =  batch_reduce(self.mse_criterion(dec_mean_t, xt[:, i, :, :, :]))
          elif self.loss_type == "mol":
              lpx_Gz_obs = -batch_reduce(self.likelihood(logits = dec_mean_t).log_prob(xt[:, i, :, :, :]))
          else:
              print("undefined loss")

          logpzs[k] = prior_dist.log_prob(z_t).sum([-1])
          logqzxs[k] = enc_dist.log_prob(z_tx).sum([-1])
          lpx_Gz_obss[k] = lpx_Gz_obs
          zprevx = z_tx
          zprev = z_t

        loss = loss - torch.mean(torch.logsumexp(lpx_Gz_obss + logpzs - logqzxs, 0)-torch.log(torch.tensor(K).float()))


      return loss
