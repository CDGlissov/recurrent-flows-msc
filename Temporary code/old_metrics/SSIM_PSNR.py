
import torch 

from pytorch_msssim import ssim
import torch.utils.data
from torch.utils.data import DataLoader
import sys
from tqdm import tqdm 


sys.path.insert(1, './deepflows_16_01/') ## Set version of code


from Utils import set_gpu
device = set_gpu(True)

import matplotlib.pyplot as plt
from RFN.trainer import Solver
import lpips

from data_generators import MovingMNIST
from data_generators import PushDataset
import os
from skimage.metrics import peak_signal_noise_ratio as skPSNR
from skimage.measure import compare_ssim as skSSIM
import numpy as np
import math
### Load model
class Evaluator(object):
    def __init__(self,solver, args, start_predictions, n_frames):
        self.args = args
        self.params = args
        self.n_bits = args.n_bits
        self.solver = solver
        self.n_frames = n_frames
        self.start_predictions = start_predictions # After so many frames it starts conditioning on itself.

        self.verbose = args.verbose
        
        self.path = str(os.path.abspath(os.getcwd())) + args.path

        self.batch_size = args.batch_size

        
        self.choose_data = args.choose_data
        #self.n_frames = args.n_frames
        self.digit_size = args.digit_size
        self.step_length = args.step_length
        self.num_digits = args.num_digits
        self.image_size = args.image_size
        self.preprocess_range = args.preprocess_range
        self.preprocess_scale = args.preprocess_scale
        self.num_workers=args.num_workers
        self.multigpu = args.multigpu

    def build(self):
        self.test_loader = self.create_loaders()
        
        if not os.path.exists(self.path + 'png_folder'):
          os.makedirs(self.path + 'png_folder')
        if not os.path.exists(self.path + 'model_folder'):
          os.makedirs(self.path + 'model_folder')
        
        if self.multigpu and torch.cuda.device_count() > 1:
            print("Using:", torch.cuda.device_count(), "GPUs")
            self.model = self.solver.model.to(device)
        else:
            self.model = self.solver.model.to(device)
        self.model.eval()
        self.lpipsNet = lpips.LPIPS(net='alex').to(device) # best forward scores
    def create_loaders(self):
        
        if self.choose_data=='mnist':
            	testset = MovingMNIST(False, 'Mnist', 
                                                         seq_len=self.n_frames, 
                                                         image_size=self.image_size, 
                                                         digit_size=self.digit_size, 
                                                         num_digits=self.num_digits, 
            												 deterministic=False, 
                                                         three_channels=False, 
                                                         step_length=self.step_length, 
                                                         normalize=False)
        if self.choose_data=='bair':
            	string=str(os.path.abspath(os.getcwd()))
            	testset = PushDataset(split='test',
                                             dataset_dir=string+'/bair_robot_data/processed_data/',
                                             seq_len=self.n_frames)

        test_loader = DataLoader(testset, batch_size=self.batch_size, num_workers=self.num_workers, shuffle=True, drop_last=True)
        return test_loader    
    
    def Evalplotter(self, predictions,true_predicted):
      num_samples = 20 # The number of examples plotted
      time_steps = predictions.shape[1]
      fig, ax = plt.subplots(num_samples*2, time_steps , figsize = (time_steps,5*num_samples))
      for k in range(0,num_samples):
          for i in range(0, time_steps):
            ax[2*(k),i].imshow(self.convert_to_numpy(true_predicted[k, i, :, :, :]))
            ax[2*(k),i].set_title("True Image")
            ax[2*(k)+1,i].imshow(self.convert_to_numpy(predictions[k, i, :, :, :]))
            ax[2*(k)+1,i].set_title(str(i)+"-step Prediction")
      fig.savefig(self.path +'png_folder/eval_samples' +  '.png', bbox_inches='tight')
      plt.close(fig)

    def convert_to_numpy(self, x):
        return x.permute(1,2,0).squeeze().detach().cpu().numpy()
    def PSNRbatch(self, X, Y, n_bits=8):
      # Is communative so [X,Y]=0
      bs, cs, h, w = X.shape
      maxi = 2**n_bits-1
      MSB = torch.mean( (X - Y)**2, dim = [1, 2, 3]) # size batch
      PSNR = 10 * torch.log10(maxi**2 / MSB).mean()
      
      return PSNR
    def mse_metric(self, x1, x2):
        err = np.sum((x1 - x2) ** 2)
        err /= float(x1.shape[0] * x1.shape[1] * x1.shape[2])
        return err
    # Eval From SVG
    def eval_seq(self, gt, pred):
        # Takes a gt of size [bs, time, c,h,w]
        T = gt.shape[1]
        bs = gt.shape[0]
        ssim = torch.zeros((bs, T))
        psnr = torch.zeros((bs, T))
        mse = torch.zeros((bs, T))
        for i in range(bs):
            for t in range(T):
                for c in range(gt.shape[2]):
                    image_gen = np.uint8(gt[i,t,c,:,:].cpu().numpy())
                    image_true = np.uint8(pred[i, t, c,:, :].cpu().numpy())
                    ssim[i, t] += skSSIM(image_gen, image_true)
                    psnr[i, t] += skPSNR(image_gen, image_true)                    
                ssim[i, t] /= gt.shape[2] ## Num channels
                psnr[i, t] /= gt.shape[2] 
                mse[i, t] = torch.mean( (gt[i, t, :, : ,:] - pred[i, t, :, : ,:])**2, dim = [0, 1, 2])

        return mse, ssim, psnr
    
    def ssim_val(self, X,Y,n_bits=8):
      # Is communative so [X,Y]=0
      # Or like it does not matter which one.. :P
      data_range = 2**n_bits-1
      ssim_val = ssim( X, Y, data_range=data_range)
      return ssim_val
    def get_lpips(self,X,Y):
        T = Y.shape[1]
        bs = X.shape[0]
        lpips = torch.zeros((bs, T))
        for i in range(bs):
            for t in range(T):
                # Is range 0,255 needs to be [-1,1]
                img0 = X[i,t,:,:,:].to(device) / 255 * 2 -1
                img1 = Y[i,t,:,:,:].to(device) / 255 * 2 -1
                if img0.shape[0] == 1: # This repeat is done as it needs 3 image channels.
                    img0 = img0.repeat(3,1,1)
                    img1 = img1.repeat(3,1,1)
                lpips[i,t] = self.lpipsNet(img0, img1)
        return lpips
    def plotreconstruct(self, image):
        ## Todo need proper normalized loss 
        recons, recons_flow, averageKLDseq, averageNLLseq = self.model.reconstructPlus(image)
        averageNLLseq = averageNLLseq
        recons  = self.solver.preprocess(recons, reverse=True)
        recons_flow  = self.solver.preprocess(recons_flow, reverse=True)
        image  = self.solver.preprocess(image, reverse=True)
        time_steps = image.shape[1]
        fig, ax = plt.subplots(7, time_steps , figsize = (2*time_steps,2*6))
        for i in range(0, time_steps):
            ax[0,i].imshow(self.convert_to_numpy(image[0, i, :, :, :]))
            ax[0,i].set_title("True Image")
            ax[0,i].axis('off')
            for z, zname in zip(range(0,2),list(['Prior','Encoder'])): 
                ax[1+z,i].imshow(self.convert_to_numpy(recons[z, i, 0, :, :, :]))
                ax[1+z,i].set_title(str(zname))
                ax[1+z,i].axis('off')
                
                ax[3+z,i].imshow(self.convert_to_numpy(recons_flow[z,i, 0, :, :, :]))
                ax[3+z,i].set_title(str(zname)+' flow')
                ax[3+z,i].axis('off')
        plt.subplot(8, 1, 7)
        plt.bar(np.arange(time_steps), averageKLDseq[:,0], align='center', width=0.3)
        plt.xlim((0-0.5, time_steps-0.5))
        plt.xticks(range(0, time_steps), range(0, time_steps))
        plt.xlabel("Frame number")
        plt.ylabel("Average KLD")
        plt.subplot(8, 1, 8)
        
        plt.bar(np.arange(time_steps)-0.15, -averageNLLseq[0, :, 0], align='center', width=0.3,label = 'Prior')
        plt.bar(np.arange(time_steps)+0.15, -averageNLLseq[1, :, 0], align='center', width=0.3,label = 'Posterior')
        plt.xlim((0-0.5, time_steps-0.5))
        low = min(min(-averageNLLseq[0, 1:, 0]),min(-averageNLLseq[1, 1:, 0]))
        high = max(max(-averageNLLseq[0, 1:, 0]),max(-averageNLLseq[1, 1:, 0]))
        plt.ylim([math.ceil(low-0.5*(high-low)), math.ceil(high+0.5*(high-low))])
        plt.xticks(range(0, time_steps), range(0, time_steps))
        plt.xlabel("Frame number")
        plt.ylabel("bits dim ll")
        plt.legend()


        fig.savefig(self.path + 'png_folder/KLDdiagnostic' + '.png', bbox_inches='tight')
        plt.close(fig)
  
    def EvaluatorPSNR_SSIM(self):
      start_predictions = self.start_predictions # After how many frames the the models starts condiitioning on itself.
      times = 1 # This is to loop over the test set more than once, if you want better measures of the prediction....
      SSIM_values = []
      PSNR_values = []
      SSIM_values_sklearn = []
      PSNR_values_sklearn = []
      MSE_values_sklearn = []
      Lpips_values = []
      with torch.no_grad():
          for time in range(0, times):
              for batch_i, image in enumerate(tqdm(self.test_loader, desc="Tester", position=0, leave=True)):
                SSIM_values_batch = []
                PSNR_values_batch = []
                batch_i += 1
                if self.choose_data=='bair':
                    image_unprocessed = image[0].to(device)
                else:
                    image_unprocessed = image.to(device)
                image = self.solver.preprocess(image_unprocessed)

                #self.plotreconstruct(image)
                x_true, predictions = self.model.predict(image, self.n_frames-start_predictions, start_predictions)
                #print(predictions[0,0,0,:,0])
                #print(predictions.permute(1,0,2,3,4).reshape((samples_recon.shape[1],-1)).min(dim=1)[0])
                image  = self.solver.preprocess(image, reverse=True)
                predictions  = self.solver.preprocess(predictions, reverse=True)
                true_predicted = image[:,start_predictions:,:,:,:].type(torch.FloatTensor).to(device)
                predictions = predictions.permute(1,0,2,3,4).type(torch.FloatTensor).to(device)
                mse, ssim, psnr = self.eval_seq(predictions, true_predicted)
                SSIM_values_sklearn.append(ssim)
                PSNR_values_sklearn.append(psnr)
                MSE_values_sklearn.append(mse)
                Lpips_values.append(self.get_lpips(predictions, true_predicted))
                for i in range(0,predictions.shape[1]):
                    SSIM_values_batch.append(self.ssim_val(predictions[:,i,:,:,:], true_predicted[:,i,:,:,:]))
                    PSNR_values_batch.append(self.PSNRbatch(predictions[:,i,:,:,:], true_predicted[:,i,:,:,:]))
                SSIM_values_batch = torch.stack(SSIM_values_batch, dim = 0)
                PSNR_values_batch = torch.stack(PSNR_values_batch, dim = 0)
                SSIM_values.append(SSIM_values_batch)
                PSNR_values.append(PSNR_values_batch)
                
      SSIM_values = torch.stack(SSIM_values)
      PSNR_values = torch.stack(PSNR_values)
      MSE_values_sklearn = torch.cat(MSE_values_sklearn)
      PSNR_values_sklearn = torch.cat(PSNR_values_sklearn)
      SSIM_values_sklearn = torch.cat(SSIM_values_sklearn)
      Lpips_values = torch.cat(Lpips_values)
      
      # Plot some samples to make sure the loader works. And the eval
      self.Evalplotter(predictions,true_predicted)
      
      return SSIM_values, PSNR_values, MSE_values_sklearn, PSNR_values_sklearn, SSIM_values_sklearn, Lpips_values
                
namelist = ['tanh_no_newtemp_newclam_deeper']
pathcd ='./tanhtest/'
overtemperature = True # Toggle if test over diffent temperatures
#temperatures = [0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1]
temperatures = [0.6]
for i in range(0,len(namelist)):
    
    start_predictions = 6 # After how many frames the model starts conditioning on itself.
    n_frames = 30 # Number of frames in the test dataloader.
    pathmodel = pathcd+namelist[i]+'/model_folder/rfn.pt'
    patherrormeasure = pathcd+namelist[i]
    #name_string = 'errormeasures_architecture_'+namelist[i]+'_trained_on_6_frames.pt'
    load_model = torch.load(pathmodel)
    args = load_model['args']

    solver = Solver(args)
    solver.build()
    solver.load(load_model)               
    			   
    				
    MetricEvaluator = Evaluator(solver, args, start_predictions, n_frames)
    MetricEvaluator.build()
    for temp in temperatures:
        MetricEvaluator.model.temperature = temp
        SSIM_values, PSNR_values, MSE_values_sklearn, PSNR_values_sklearn, SSIM_values_sklearn, Lpips_values = MetricEvaluator.EvaluatorPSNR_SSIM()
        Savedict = {"SSIM_values": SSIM_values.cpu(),
                    "PSNR_values": PSNR_values.cpu(),
                    "SSIM_values_sklearn": SSIM_values_sklearn.cpu(),
                    "PSNR_values_sklearn": PSNR_values_sklearn.cpu(),
                    "MSE_values_sklearn": MSE_values_sklearn.cpu(),
                    "LPIPS_values": Lpips_values.cpu(),
                    "SSIM_values_mean": SSIM_values.mean(0).cpu(),  # We dont need to save this, but w.e.
                    "PSNR_values_mean": PSNR_values.mean(0).cpu(),
                    }
        torch.save(Savedict,patherrormeasure+'/temp_'+str(temp).replace('.','_')+'_PSNR_SSIM_LPIPS.pt')    
        print(SSIM_values.mean(0))
        print(PSNR_values.mean(0))
        print(MSE_values_sklearn.mean(0))
        print(PSNR_values_sklearn.mean(0))
        print(SSIM_values_sklearn.mean(0))
       
            
