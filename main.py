'''Main file'''

import argparse

def main(args):
    batch_size = args.batch_size
    verbose = args.verbose
    min_lr = args.min_lr
    dim_x = tuple(args.dim_x)
    extractor_structure = args.extractor_structure
    upscaler_structure = args.upscaler_structure
    print(upscaler_structure)
    print(extractor_structure)
    
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
    
    # Trainer
    parser.add_argument("--batch_size", help="Specify batch size", default=64, type=int)
    parser.add_argument("--n_frames", help="Specify number of frames", default=6, type=int)
    parser.add_argument("--choose_data", help="Specify dataset", choices=['mnist', 'bair'], default='mnist', type=str)
    parser.add_argument("--patience_es", help="Specify patience for early stopping", default=50, type=int)
    parser.add_argument("--patience_lr", help="Specify patience for lr_scheduler", default=5, type=int)
    parser.add_argument("--factor_lr", help="Specify lr_scheduler factor (0..1)", default=0.5, type=restricted_float)
    parser.add_argument("--min_lr", help="Specify minimum lr for scheduler", default=0.00001, type=float)
    parser.add_argument("--n_bits", help="Specify number of bits", default=8, type=int)
    parser.add_argument("--n_epochs", help="Specify number of epochs", default=100, type=int)
    add_bool_arg(parser, "verbose", default=False, help="Specify verbose mode (boolean)")
    parser.add_argument("--path", help="Specify path to experiment", default='/content/', type=str)
    parser.add_argument("--learning_rate", help="Specify learning_rate", default=0.5, type=float)
    parser.add_argument("--preprocess_range", help="Specify the range of the data for preprocessing", choices=['0.5','1.0'], default='0.5', type=str)
    parser.add_argument("--preprocess_scale", help="Specify the scale for preprocessing", default=255, type=int)
    parser.add_argument("--beta_max", help="Specify the maximum value of beta", default=0.01, type=float)
    parser.add_argument("--beta_min", help="Specify the minimum value of beta", default=0.0001, type=float)
    parser.add_argument("--beta_steps", help="Specify the annealing steps", default=2000, type=int)
    
    # RFN
    parser.add_argument('--dim_x', nargs='+', help="Specify data dimensions (b,c,h,w)", default=[32, 1, 32, 32], type=int)
    parser.add_argument('--dim_condition', nargs='+', help="Specify condition dimensions (b,c,h,w)", default=[32, 1, 32, 32], type=int)
    parser.add_argument("--h_dim", help="Specify hidden state (h) channels", default=100, type=int)
    parser.add_argument("--z_dim", help="Specify latent (z) channels", default=30, type=int)
    parser.add_argument("--L", help="Specify flow depth", default=4, type=int)
    parser.add_argument("--K", help="Specify flow recursion", default=10, type=int)
    parser.add_argument("--c_features", help="Specify channels of extracted features", default=128, type=int)
    parser.add_argument('--extractor_structure', nargs='+', help="Specify structure of extractor (int, str)", 
                        default= [32, 'conv', 32, 'conv', 64, 'conv', 64, 'conv'], type=convert_mixed_list)
    parser.add_argument('--norm_type', help="Specify normalization type of layers", default='none', 
                        choices=["instancenorm", "batchnorm", "none"], type=str)
    parser.add_argument('--upscaler_structure', help="Specify upscaler structure, example writing, 32-32-deconv 32-32-upsample, creates 2 blocks", 
                        nargs='+', default=[[128], ['deconv', 64], ['deconv', 64], ['deconv', 32]], type=convert_to_upscaler)
    parser.add_argument("--structure_scaler", help="Specify down/up-sampling channel factor", default=1, type=int)
    parser.add_argument("--temperature", help="Specify temperature", default=0.8, type=restricted_float)
    parser.add_argument("--n_predictions", help="Specify number of predictions", default=6, type=int)
    
    #Glow
    add_bool_arg(parser, "learn_prior", default=True, help="Specify if we want a learned prior (boolean)")
    add_bool_arg(parser, "LU_decomposed", default=True, help="Specify if we want to use LU factorization (boolean)")
    parser.add_argument("--n_units_affine", help="Specify hidden units in affine coupling", default=128, type=int)
    parser.add_argument("--n_units_prior", help="Specify hidden units in prior", default=128, type=int)
    
    args = parser.parse_args()
    
    main(args)