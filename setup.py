from setuptools import setup

setup(name='deephe3', 
      package_dir={'': 'deephe3'}, 
      install_requires=[
          'ase', 
          'pymatgen', 
          'tqdm', 
          'numpy', 
          'torch==1.13.1',  # to support mace
          'torch-scatter', 
          'torch-sparse', 
          'torch-cluster', 
          'torch-spline-conv', 
          'torch-geometric', 
          'e3nn==0.4.4',  # to support mace
          'h5py', 
          'tensorboard', 
          'pathos'
      ]
)
