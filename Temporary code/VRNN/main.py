'''Main file'''

import argparse
from trainer import Solver

def main(args):
    solver = Solver(args)
    solver.build()
    #TODO: Check if this loader works
    if args.load_model:
        path_model = args.path + 'model_folder/vrnn.pt'
        solver.load(path_model)
    solver.train()   

    
def add_bool_arg(parser, name, help, default=False):
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument('--' + name, dest=name, action='store_true', help=help)
    group.add_argument('--no-' + name, dest=name, action='store_false', help=help)
    parser.set_defaults(**{name:default})


def restricted_float(x):
    try:
        x = float(x)
    except ValueError:
        raise argparse.ArgumentTypeError("%r not a floating-point literal" % (x,))

    if x < 0.0 or x > 1.0:
        raise argparse.ArgumentTypeError("%r not in range [0.0, 1.0]"%(x,))
    return x


def convert_mixed_list(x):
    if x.isdigit():
        return int(x)
    else:
        return x


def convert_to_upscaler(x):
    block = [convert_mixed_list(i) for i in x.split("-")]
    return block

        
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    
    #DATA
    parser.add_argument("--batch_size", help="Specify batch size", 
                        default=128, type=int)
    parser.add_argument("--n_frames", help="Specify number of frames", 
                        default=6, type=int)
    parser.add_argument("--choose_data", help="Specify dataset", 
                        choices=['mnist', 'bair'], default='mnist', type=str)
    parser.add_argument("--image_size", help="Specify the image size of mnist", 
                        default=32, type=int)
    parser.add_argument("--digit_size", help="Specify the size of mnist digit", 
                        default=21, type=int)
    parser.add_argument("--step_length", help="Specify the step size of mnist digit", 
                        default=2, type=int)
    parser.add_argument("--num_digits", help="Specify the number of mnist digits", 
                        default=1, type=int)
    parser.add_argument("--num_workers", help="Specify the number of workers in dataloaders", 
                        default=0, type=int)
    
    
    # Trainer
    parser.add_argument("--patience_es", help="Specify patience for early stopping", 
                        default=50, type=int)
    parser.add_argument("--patience_lr", help="Specify patience for lr_scheduler", 
                        default=5, type=int)
    parser.add_argument("--factor_lr", help="Specify lr_scheduler factor (0..1)", 
                        default=0.5, type=restricted_float)
    parser.add_argument("--min_lr", help="Specify minimum lr for scheduler", 
                        default=0.00001, type=float)
    parser.add_argument("--n_bits", help="Specify number of bits", 
                        default=8, type=int)
    parser.add_argument("--n_epochs", help="Specify number of epochs", 
                        default=200, type=int)
    add_bool_arg(parser, "verbose", default=False, help="Specify verbose mode (boolean)")
    parser.add_argument("--path", help="Specify path to experiment", 
                        default='/content/', type=str)
    parser.add_argument("--learning_rate", help="Specify learning_rate", 
                        default=0.0001, type=float)
    parser.add_argument("--preprocess_range", help="Specify the range of the data for preprocessing", 
                        choices=['0.5','1.0', 'minmax'], default='minmax', type=str)
    parser.add_argument("--preprocess_scale", help="Specify the scale for preprocessing", 
                        default=255, type=int)
    parser.add_argument("--beta_max", help="Specify the maximum value of beta", 
                        default=0.001, type=float)
    parser.add_argument("--beta_min", help="Specify the minimum value of beta", 
                        default=0.00001, type=float)
    parser.add_argument("--beta_steps", help="Specify the annealing steps", 
                        default=2000, type=int)
    parser.add_argument("--n_predictions", help="Specify number of predictions", 
                        default=6, type=int)
    add_bool_arg(parser, "multigpu", default=False, help="Specify if we want to use multi GPUs")
    add_bool_arg(parser, "load_model", default=False, 
                 help="Specify if we want to load a pre-existing model (boolean)")
    add_bool_arg(parser, "variable_beta", default=True, 
                 help="Specify if we want a linear decreasing beta value (boolean)")
    
    # VRNN
    parser.add_argument('--x_dim', nargs='+', help="Specify data dimensions (b,c,h,w)", 
                        default=[128, 1, 32, 32], type=int)
    parser.add_argument('--condition_dim', nargs='+', help="Specify condition dimensions (b,c,h,w)", 
                        default=[128, 1, 32, 32], type=int)
    parser.add_argument("--h_dim", help="Specify hidden state (h) channels", 
                        default=100, type=int)
    parser.add_argument("--z_dim", help="Specify latent (z) channels", 
                        default=16, type=int)
    parser.add_argument("--loss_type", help="Specify the type of loss used", 
                        default="bernoulli", choices = ["bernoulli", "mse", "gaussian"], type=str)
    parser.add_argument("--norm_type", help="Specify the type of loss used", 
                        default="none", choices = ["batchnorm", "instancenorm", "none"], type=str)
    
    
    args = parser.parse_args()
    
    main(args)
