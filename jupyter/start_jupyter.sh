#!/bin/bash

# Add environment variables
echo "export MLFLOW_TRACKING_URI=$MLFLOW_TRACKING_URI" >> /etc/profile.d/mlflow.sh
echo "export DASK_SCHEDULER_ADDRESS=$DASK_SCHEDULER_ADDRESS" >> /etc/profile.d/dask.sh

# Add read and write permissions to /notebooks
chmod 755 /notebooks

# Start JupyterHub
jupyterhub -f /srv/jupyter/jupyterhub_config.py --ip 0.0.0.0
