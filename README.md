# recurrent-flows-msc

This repository will contain the following implementations:

IAF - 2D <br>
RealNVP - 2D and 3D <br>
Glow - 3D <br>
Conditional Glow - 3D <br>
Autoregressive Glow - 4D <br>
Recurrent Flow Networks - 4D (Video generation) <br>

TODO: Add VRNN<br>
TODO: Fix inverse weighting in conditional glow. Maybe also add zero init in norm layers? See if we can reduce noise.<br>
TODO: Two phase training, encoder then glow.<br>
TODO: Longer roll out. <br>
TODO: Make batchnorm for glow when batchsize is large. Actnorm for small batches <br>
